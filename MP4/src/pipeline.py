#!/usr/bin/env python3
import argparse
import json
import shutil
import sys
from pathlib import Path

from agents.base import Agent
from agents.orchestrator import Orchestrator
from harness import Harness, interface_signatures
from llm import LLM, LLMError
from logger import Logger
from state import State
from tools import Workspace

MP4 = Path(__file__).resolve().parent.parent
PROMPTS = MP4 / "configs" / "prompts"


class Ctx:
    pass


def load_cfg():
    cfg = json.loads((MP4 / "configs" / "pipeline.json").read_text())
    return cfg, json.loads((MP4 / "configs" / "model.json").read_text())


def normalize_layout(crate):
    import re
    src, moved = crate / "src", []
    lib = (src / "lib.rs").read_text()
    for mod in re.findall(r"^\s*pub\s+mod\s+(\w+)\s*;", lib, re.M):
        stub = src / "interfaces" / f"{mod}.rs"
        if stub.is_file() and not (src / f"{mod}.rs").exists() and not (src / mod / "mod.rs").exists():
            shutil.move(str(stub), str(src / f"{mod}.rs"))
            moved.append(f"src/interfaces/{mod}.rs -> src/{mod}.rs")
    leftover = src / "interfaces"
    if leftover.is_dir() and not any(leftover.iterdir()):
        leftover.rmdir()
    return moved


def setup(args, llm=None):
    cfg, mcfg = load_cfg()
    if args.max_iterations:
        cfg["max_iterations"] = args.max_iterations
    root = Path(args.out_root).resolve() if getattr(args, "out_root", None) else MP4
    traj = root / "trajectories" / f"project_{args.project}"
    crate = root / "translations" / f"project_{args.project}"
    template = Path(args.rust_template).resolve()
    if not (template / "Cargo.toml").is_file():
        sys.exit(f"--rust-template must be the CRUST-Bench Rust crate (Cargo.toml + interface + tests): {template}")
    moved = []
    if not crate.exists() or not any(crate.iterdir()):
        shutil.copytree(template, crate, ignore=shutil.ignore_patterns("target", ".git"))
        moved = normalize_layout(crate)
    ctx = Ctx()
    ctx.cfg = cfg
    ctx.logger = Logger(traj)
    ctx.logger.log("setup", layout_moves=moved, template=str(template), c_dir=str(args.c_dir))
    ctx.llm = llm or LLM(mcfg, ctx.logger)
    ctx.harness = Harness(crate, cfg)
    ctx.harness.interface_sigs = interface_signatures(template / "src")
    ctx.ws = Workspace(crate, args.c_dir, traj / "notes", cfg, ctx.harness)
    ctx.ws.snapshot_protected()
    ctx.state = State(crate, traj)
    ctx.crate, ctx.traj = crate, traj
    ctx.state.snapshot("original")
    return ctx


def build_agents(ctx):
    steps, P = ctx.cfg["agent_max_steps"], PROMPTS
    common = [P / "actions.md"]
    mk = lambda name, tools, globs: Agent(name, ctx, tools, globs, common + [P / f"{name}.md"], steps[name])
    return {
        "reader": mk("reader", {"read_file", "list_dir", "grep", "write_file"}, ["notes/spec*.md"]),
        "writer": mk("writer", {"read_file", "list_dir", "grep", "write_file", "run_cargo"}, ["src/*"]),
        "tester": mk("tester", {"read_file", "list_dir", "grep", "write_file", "run_cargo", "run_c_oracle"},
                     ["tests/extra_*.rs", "notes/*"]),
    }, Orchestrator(ctx, P / "orchestrator.md")


def over_budget(ctx):
    return ctx.llm.total_tokens >= ctx.cfg["max_total_tokens"]


def run(args, llm=None):
    ctx = setup(args, llm)
    agents, orch = build_agents(ctx)
    cfg, st, h, log = ctx.cfg, ctx.state, ctx.harness, ctx.logger
    status, phase, analysed_sig = "max_iterations", "A", None
    tester_done = b_used = 0
    good_score, reader_escalated = None, False
    try:
        agents["reader"].run("Read the C project, the Rust interface and the tests, then write the spec "
                             "(notes/spec.md plus one notes/spec_<module>.md per module).")
        agents["writer"].run("Create the initial Rust translation. Read notes/spec.md first, then the Rust "
                             "interface in src/ and the tests. Get `run_cargo cmd=\"check\"` to pass, then "
                             "`cmd=\"test\"`.")
        for it in range(1, cfg["max_iterations"] + 1):
            if over_budget(ctx):
                status = "token_budget"
                break
            rep = h.evaluate(full=(phase == "B"))
            st.record(it, phase, rep)
            bad = ctx.ws.enforce_protected()
            if bad:
                log.log("integrity_violation", files=bad)
            rendered = h.render(rep, cfg["obs_limit_chars"])
            log.log("iteration", it=it, phase=phase, build_ok=rep["build_ok"], core=rep["core"],
                    extra=rep["extra"], clippy=rep["clippy"], unsafe=rep["unsafe"], score=rep["score"])
            print(f"[iter {it} phase {phase}] build={'ok' if rep['build_ok'] else 'FAIL'} "
                  f"core={rep['core'] and (rep['core']['passed'], rep['core']['total'])} "
                  f"score={rep['score']} tokens={ctx.llm.total_tokens}", flush=True)

            if phase == "A":
                if rep["core_ok"] and rep["extra_ok"]:
                    if tester_done < cfg["tester_rounds"]:
                        tester_done += 1
                        agents["tester"].run(
                            "GENERATE: write additional edge-case tests in tests/extra_<name>.rs using the C oracle "
                            "for expected values, then run them.\n\nCurrent state:\n" + rendered)
                        continue
                    phase = "B"
                    st.snapshot("good")
                    st.reset_stall()
                    log.log("phase_change", to="B")
                    continue
                if st.stalled(cfg["stall_rounds"]):
                    if reader_escalated:
                        status = "stalled"
                        break
                    reader_escalated = True
                    agents["reader"].run("The writer is stuck on the same failure. Re-read the relevant C code and "
                                         "extend notes/spec*.md with the exact missing behaviour.\n\n" + rendered)
                    st.reset_stall()
                    continue
                d = orch.decide(it, phase, rep, rendered, analysed_sig)
                brief = f"{d['task']}\n\nHarness feedback:\n{rendered}"
                if d["next_agent"] == "tester":
                    analysed_sig = rep["sig"]
                    agents["tester"].run("ANALYZE: " + brief)
                elif d["next_agent"] == "reader":
                    agents["reader"].run(brief)
                else:
                    agents["writer"].run(brief)
            else:
                if not rep["core_ok"] or not rep["extra_ok"]:
                    st.restore("good")
                    log.log("revert", reason="tests broke", it=it)
                elif good_score is None or (rep["score"] is not None and rep["score"] < good_score):
                    good_score = rep["score"]
                    st.snapshot("good")
                    log.log("accept", score=good_score, it=it)
                else:
                    st.restore("good")
                    log.log("revert", reason="no improvement", it=it)
                if good_score == 0:
                    status = "success"
                    break
                if b_used >= cfg["phase_b_rounds"]:
                    status = "phase_b_done"
                    break
                b_used += 1
                task = (PROMPTS / "phase_b.md").read_text() + "\n\nCurrent metrics:\n" + rendered
                agents["writer"].run(task)
    except LLMError as e:
        status = f"llm_error: {e}"
        log.log("fatal", error=str(e))
    finally:
        if phase == "B":
            st.restore("good")
        final = h.evaluate(full=True)
        ctx.ws.enforce_protected()
        result = {
            "status": status, "iterations": len(st.history), "phase": phase,
            "build_ok": final["build_ok"], "core": final["core"], "extra": final["extra"],
            "clippy": final["clippy"], "unsafe": final["unsafe"],
            "interface_missing": final["interface_missing"],
            "tokens": ctx.llm.usage,
        }
        log.write_json("final_status.json", result)
        print(json.dumps(result, indent=2, default=str))
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=int, required=True, choices=[1, 2])
    ap.add_argument("--c-dir", required=True, help="original C project directory")
    ap.add_argument("--rust-template", required=True,
                    help="CRUST-Bench Rust crate (Cargo.toml, src/ interface stubs, tests/)")
    ap.add_argument("--max-iterations", type=int)
    ap.add_argument("--out-root", help="override output root (default: MP4/); used by tests")
    run(ap.parse_args())


if __name__ == "__main__":
    main()
