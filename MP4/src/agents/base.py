import re
from pathlib import Path

from harness import truncate

HEAD = re.compile(r'<action((?:\s+\w+="[^"]*")*)\s*(/?)>')
ATTR = re.compile(r'(\w+)="([^"]*)"')
FENCE = re.compile(r"^\s*```[\w+-]*\n(.*?)\n```\s*$", re.S)


def parse_actions(text):
    # DeepSeek may expose its DSML wrapper alongside the XML action syntax.
    # Normalize invoke/parameter entries so they do not trigger empty retries.
    text = re.sub(
        r'<[^>]*DSML[^>]*?\s+(?:invoke|parameter)\s+name="([^"]+)"',
        r'<action name="\1"',
        text,
    )
    actions, pos = [], 0
    while True:
        m = HEAD.search(text, pos)
        if not m:
            return actions
        attrs = dict(ATTR.findall(m.group(1)))
        truncated = False
        if m.group(2) == "/":
            body, pos = None, m.end()
        else:
            end = text.find("</action>", m.end())
            if end == -1:
                body, pos, truncated = text[m.end():], len(text), True
            else:
                body, pos = text[m.end():end], end + len("</action>")
        actions.append({"name": attrs.get("name", ""), "attrs": attrs, "body": body, "truncated": truncated})


def clean_body(body):
    body = body.strip("\n")
    m = FENCE.match(body)
    if m:
        body = m.group(1)
    return body.rstrip() + "\n"


class Agent:
    def __init__(self, name, ctx, tools, write_globs, prompt_files, max_steps):
        self.name, self.ctx, self.tools, self.write_globs, self.max_steps = name, ctx, tools, write_globs, max_steps
        self.system = "\n\n".join(Path(p).read_text() for p in prompt_files)

    def run(self, task):
        ctx, cfg = self.ctx, self.ctx.cfg
        messages = [{"role": "system", "content": self.system}, {"role": "user", "content": task}]
        ctx.logger.log("agent_start", agent=self.name, task=task)
        summary, idle = "(agent ended without calling done)", 0
        invalid_path_count = 0
        invalid_path_limit = max(1, int(cfg.get("max_invalid_path_actions", 2)))
        step_limit = self.max_steps
        focused_reader = self.name == "reader" and any(
            marker in task.lower() for marker in ("re-read", "writer is stuck")
        )
        read_limit = None
        if self.name == "reader":
            reader_limit = "reader_focus_max_steps" if focused_reader else "reader_initial_max_steps"
            step_limit = min(step_limit, int(cfg.get(reader_limit, step_limit)))
            read_limit_key = "reader_focus_read_limit" if focused_reader else "reader_initial_read_limit"
            read_limit = max(1, int(cfg.get(read_limit_key, 4 if focused_reader else 18)))
        focused_writer = (
            self.name == "writer"
            and "harness feedback:" in task.lower()
        )
        if self.name == "writer":
            writer_read_key = "writer_repair_read_limit" if focused_writer else "writer_initial_read_limit"
            read_limit = max(1, int(cfg.get(writer_read_key, 4 if focused_writer else 12)))
        read_actions, blocked_read_steps = 0, 0
        for step in range(1, step_limit + 1):
            text = ctx.llm.chat(messages)
            messages.append({"role": "assistant", "content": text})
            ctx.logger.log("agent_message", agent=self.name, step=step, content=text)
            actions = parse_actions(text)
            if not actions:
                idle += 1
                if idle >= 3:
                    summary = "(agent stopped: no valid <action> in 3 consecutive replies)"
                    break
                messages.append({"role": "user", "content": "No valid <action> found. Reply with one or more "
                                 "<action .../> blocks as described in the protocol."})
                continue
            action_limit = max(1, int(cfg.get("max_actions_per_reply", 8)))
            excess_actions = max(0, len(actions) - action_limit)
            if excess_actions:
                ctx.logger.log("action_batch_limited", agent=self.name, step=step,
                               received=len(actions), executing=action_limit,
                               ignored=excess_actions)
                actions = actions[:action_limit]
            idle = 0
            obs, finished, stop_for_invalid_paths = [], False, False
            blocked_read_this_step, wrote_this_step = False, False
            for i, a in enumerate(actions, 1):
                if a["name"] == "done":
                    summary, finished = (a["body"] or "").strip() or "(done)", True
                    break
                is_read = a["name"] in {"read_file", "list_dir", "grep"}
                if read_limit is not None and is_read and read_actions >= read_limit:
                    blocked_read_this_step = True
                    if self.name == "reader":
                        result = ("READ LIMIT REACHED: stop inspecting files. Write or update the behavioral "
                                  "spec from the evidence already gathered, mark unknown details as unclear, "
                                  "and call done.")
                    elif focused_writer:
                        result = ("READ LIMIT REACHED: stop inspecting. Use the harness feedback and any spec "
                                  "already available, implement the focused Rust repair now, then run the failing test.")
                    else:
                        result = ("READ LIMIT REACHED: stop inspecting and implement the Rust translation from "
                                  "the evidence already gathered, then run cargo check and test.")
                    ctx.logger.log("read_action_limited", agent=self.name, step=step, attrs=a["attrs"],
                                   read_actions=read_actions, read_limit=read_limit)
                else:
                    result = self.execute(a)
                    if read_limit is not None and is_read:
                        read_actions += 1
                    if a["name"] == "write_file" and result.startswith("wrote "):
                        wrote_this_step = True
                ctx.logger.log("tool_call", agent=self.name, step=step, action=a["name"], attrs=a["attrs"],
                               result=truncate(result, 3000))
                obs.append(f"[result {i}: {a['name']} {a['attrs'].get('path', a['attrs'].get('cmd', ''))}]\n"
                           + truncate(result, cfg["obs_limit_chars"]))
                if a["name"] in {"read_file", "list_dir", "grep"} and result.startswith(
                        ("ERROR: no such file:", "ERROR: no such path:", "ERROR: not a directory:")
                ):
                    invalid_path_count += 1
                    ctx.logger.log("invalid_path_action", agent=self.name, step=step,
                                   path=a["attrs"].get("path"), count=invalid_path_count,
                                   limit=invalid_path_limit)
                    if invalid_path_count >= invalid_path_limit:
                        summary = f"(agent stopped after {invalid_path_count} invalid path actions)"
                        stop_for_invalid_paths = True
                        break
            if finished:
                break
            if stop_for_invalid_paths:
                ctx.logger.log("agent_guardrail_stop", agent=self.name, step=step, reason="invalid_paths")
                break
            if excess_actions:
                obs.append("[protocol] This reply exceeded the per-reply action limit. Only the first "
                           f"{action_limit} actions were executed; the rest were ignored. Continue in a new "
                           "reply using paths confirmed by list_dir, and do not guess or enumerate filenames.")
            messages.append({"role": "user", "content": "\n\n".join(obs)})
            if blocked_read_this_step and not wrote_this_step:
                blocked_read_steps += 1
            else:
                blocked_read_steps = 0
            if blocked_read_steps >= 2:
                if self.name == "reader":
                    summary = "(reader stopped after exhausting the inspection read limit)"
                else:
                    summary = "(writer stopped after exhausting the inspection read limit)"
                break
            keep = cfg["history_keep"]
            if len(messages) > 2 + keep:
                messages = messages[:2] + messages[-keep:]
        ctx.logger.log("agent_end", agent=self.name, summary=summary, tokens_total=ctx.llm.total_tokens)
        return summary

    def execute(self, a):
        name, at, ws = a["name"], a["attrs"], self.ctx.ws
        if name not in self.tools:
            return f"ERROR: tool '{name}' is not available to the {self.name}. Available: {', '.join(sorted(self.tools))}, done"
        try:
            if name == "read_file":
                return ws.read_file(at["path"], at.get("start"), at.get("end"))
            if name == "list_dir":
                return ws.list_dir(at.get("path", "."))
            if name == "grep":
                return ws.grep(at["pattern"], at.get("path", "."))
            if name == "write_file":
                if a["body"] is None or a["truncated"]:
                    return "ERROR: write_file needs a body closed with </action>. Your output was cut off; write smaller files."
                return ws.write_file(at["path"], clean_body(a["body"]), self.write_globs)
            if name == "run_cargo":
                return ws.run_cargo(at.get("cmd", "check"), self.name,
                                    target=at.get("target"), test_filter=at.get("filter"))
            if name == "run_c_oracle":
                return ws.run_c_oracle(at.get("driver", "notes/oracle.c"), a["body"])
        except KeyError as e:
            return f"ERROR: missing attribute {e} for {name}"
        except PermissionError as e:
            return f"DENIED: {e}"
        except Exception as e:
            return f"ERROR: {type(e).__name__}: {e}"
        return f"ERROR: unknown tool {name}"
