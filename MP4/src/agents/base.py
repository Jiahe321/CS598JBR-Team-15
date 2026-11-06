import re
from pathlib import Path

from harness import truncate

HEAD = re.compile(r'<action((?:\s+\w+="[^"]*")*)\s*(/?)>')
ATTR = re.compile(r'(\w+)="([^"]*)"')
FENCE = re.compile(r"^\s*```[\w+-]*\n(.*?)\n```\s*$", re.S)


def parse_actions(text):
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
        for step in range(1, self.max_steps + 1):
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
            idle = 0
            obs, finished = [], False
            for i, a in enumerate(actions, 1):
                if a["name"] == "done":
                    summary, finished = (a["body"] or "").strip() or "(done)", True
                    break
                result = self.execute(a)
                ctx.logger.log("tool_call", agent=self.name, step=step, action=a["name"], attrs=a["attrs"],
                               result=truncate(result, 3000))
                obs.append(f"[result {i}: {a['name']} {a['attrs'].get('path', a['attrs'].get('cmd', ''))}]\n"
                           + truncate(result, cfg["obs_limit_chars"]))
            if finished:
                break
            messages.append({"role": "user", "content": "\n\n".join(obs)})
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
                return ws.run_cargo(at.get("cmd", "check"), self.name)
            if name == "run_c_oracle":
                return ws.run_c_oracle(at.get("driver", "notes/oracle.c"), a["body"])
        except KeyError as e:
            return f"ERROR: missing attribute {e} for {name}"
        except PermissionError as e:
            return f"DENIED: {e}"
        except Exception as e:
            return f"ERROR: {type(e).__name__}: {e}"
        return f"ERROR: unknown tool {name}"
