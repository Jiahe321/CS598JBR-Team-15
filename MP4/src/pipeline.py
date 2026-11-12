#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

from agents.base import Agent
from agents.orchestrator import Orchestrator
from harness import Harness, interface_signatures
from llm import LLM, LLMError, RequestBudgetReached, TokenBudgetReached
from logger import Logger
from state import State
from tools import Workspace

MP4 = Path(__file__).resolve().parent.parent
PROMPTS = MP4 / "configs" / "prompts"


def load_local_env():
    """Load simple KEY=value entries from MP4/.env without overriding the shell."""
    env_file = MP4 / ".env"
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if value and not os.environ.get(key):
            os.environ[key] = value


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
    load_local_env()
    cfg, mcfg = load_cfg()
    if args.max_iterations:
        cfg["max_iterations"] = args.max_iterations
    max_llm_requests = getattr(args, "max_llm_requests", None)
    if max_llm_requests is not None:
        if max_llm_requests < 1:
            sys.exit("--max-llm-requests must be at least 1")
        cfg["max_llm_requests_per_run"] = max_llm_requests
    if getattr(args, "cargo_target", None):
        cfg["cargo_target"] = args.cargo_target
    root = Path(args.out_root).resolve() if getattr(args, "out_root", None) else MP4
    protected_data_dirs = (MP4 / "subjects", MP4 / "trajectories", MP4 / "newmetrics")
    if any(root == path or path in root.parents for path in protected_data_dirs):
        sys.exit("--out-root must not point into MP4/subjects, MP4/trajectories, or MP4/newmetrics")
    traj = root / "trajectories" / f"project_{args.project}"
    crate = root / "translations" / f"project_{args.project}"
    cfg["assertion_diagnostics_path"] = str(traj / "assertion_diagnostics.tsv")
    template = Path(args.rust_template).resolve()
    if not (template / "Cargo.toml").is_file():
        sys.exit(f"--rust-template must be the CRUST-Bench Rust crate (Cargo.toml + interface + tests): {template}")
    if getattr(args, "clean", False) and getattr(args, "resume", False):
        sys.exit("--clean cannot be combined with --continue/--resume")
    if getattr(args, "resume", False) and not (crate / "src").is_dir():
        sys.exit(f"--continue requested, but no saved translation exists at {crate}; run once without --continue first")
    if getattr(args, "clean", False):
        # These paths are derived from the validated project number and output root.
        # Keep cleanup scoped to this project's generated artifacts.
        for path in (crate, traj):
            if path.exists():
                shutil.rmtree(path)
    moved = []
    if not crate.exists() or not any(crate.iterdir()):
        # A placeholder output directory may already exist in a clone. Remove
        # only that verified-empty directory before copying the template.
        if crate.exists():
            crate.rmdir()
        shutil.copytree(template, crate, ignore=shutil.ignore_patterns("target", ".git"))
        moved = normalize_layout(crate)
    ctx = Ctx()
    ctx.cfg = cfg
    ctx.logger = Logger(traj)
    ctx.logger.log("setup", project=args.project, layout_moves=moved,
                   template=str(template), c_dir=str(Path(args.c_dir).resolve()),
                   model=mcfg.get("model"), toolchain=cfg.get("toolchain"),
                   resume=bool(getattr(args, "resume", False)),
                   cargo_target=cfg.get("cargo_target"),
                   max_iterations=cfg.get("max_iterations"),
                   max_llm_requests=cfg.get("max_llm_requests_per_run"),
                   token_budget=cfg.get("max_total_tokens"))
    mcfg["max_total_tokens"] = cfg["max_total_tokens"]
    mcfg["max_llm_requests_per_run"] = cfg["max_llm_requests_per_run"]
    ctx.llm = llm or LLM(mcfg, ctx.logger)
    ctx.harness = Harness(crate, cfg)
    ctx.harness.interface_sigs = interface_signatures(template / "src")
    ctx.ws = Workspace(crate, args.c_dir, traj / "notes", cfg, ctx.harness)
    ctx.ws.snapshot_protected()
    ctx.state = State(crate, traj, resume=bool(getattr(args, "resume", False)))
    ctx.crate, ctx.traj = crate, traj
    if not (ctx.state.snap_dir / "original").exists():
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
    good_score = None
    try:
        if over_budget(ctx):
            status = "token_budget"
        elif getattr(args, "resume", False):
            log.log("resume", note="continue from the existing translation and saved specifications")
        else:
            agents["reader"].run("Read the C project, the Rust interface and the tests, then write the spec "
                                 "(notes/spec.md plus one notes/spec_<module>.md per module).")
            if over_budget(ctx):
                status = "token_budget"
            else:
                agents["writer"].run("Create the initial Rust translation. Read notes/spec.md first, then the Rust "
                                     "interface in src/ and the tests. Get `run_cargo cmd=\"check\"` to pass, then "
                                     "`cmd=\"test\"`.")
                if over_budget(ctx):
                    status = "token_budget"
        for it in range(1, cfg["max_iterations"] + 1) if status != "token_budget" else ():
            if over_budget(ctx):
                status = "token_budget"
                break
            iteration_number = st.iteration_offset + it
            rep = h.evaluate(
                full=(phase == "B"),
                safety=cfg.get("unsafe_metrics_every_iteration", False),
            )
            if rep.get("assertion_diagnostics"):
                log.log("assertion_diagnostics", **rep["assertion_diagnostics"])
                diag = rep["assertion_diagnostics"]
                if diag.get("status") == "complete":
                    print(f"[assertions] {diag['passed']}/{diag['executions']} passed, "
                          f"{diag['failed']} failed; report={diag['report']}", flush=True)
                    for site in diag.get("failed_sites", [])[:20]:
                        print(f"[assertions] line {site['line']} {site['macro']}: "
                              f"{site['failed']}/{site['executions']} failed; "
                              f"{site['first_failure']}", flush=True)
            if st.failure_was_analyzed(rep["sig"]):
                analysed_sig = rep["sig"]
            st.record(it, phase, rep)
            bad = ctx.ws.enforce_protected()
            if bad:
                log.log("integrity_violation", files=bad)
            rendered = h.render(rep, cfg["obs_limit_chars"])
            log.log("iteration", it=iteration_number, phase=phase, build_ok=rep["build_ok"], core=rep["core"],
                    extra=rep["extra"], clippy=rep["clippy"], unsafe=rep["unsafe"], score=rep["score"])
            print(f"[iter {iteration_number} phase {phase}] build={'ok' if rep['build_ok'] else 'FAIL'} "
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
                if not rep["build_ok"]:
                    repair_task = (
                        "BUILD-ERROR REPAIR. Fix every compiler error shown in Harness feedback in the Rust "
                        "implementation. Read only compiler-reported Rust files and the exact type or callback "
                        "definition needed to resolve them. Do not route back to Reader or Tester for a compile "
                        "error. Do not guess or change public signatures. Make the code edit now, then run "
                        "run_cargo cmd=\"check\"; if it passes, run cmd=\"test\". If the compiler output shows "
                        "a mismatch involving Option<Card>, preserve that exact optional type through helper "
                        "methods and call sites."
                    )
                    log.log("build_error_writer_route", failure_sig=rep["sig"], iteration=iteration_number,
                            errors=len(rep.get("build_errors") or []))
                    agents["writer"].run(f"{repair_task}\n\nHarness feedback:\n{rendered}")
                    continue
                if st.stalled(cfg["stall_rounds"]):
                    if st.reader_was_reviewed(rep["sig"]):
                        status = "stalled"
                        break
                    st.mark_reader_reviewed(rep["sig"])
                    log.log("reader_escalation", failure_sig=rep["sig"], iteration=iteration_number,
                            reason="repeated identical harness failure")
                    agents["reader"].run("The writer is stuck on the same failure. Re-read the relevant C code and "
                                         "extend notes/spec*.md with the exact missing behaviour.\n\n" + rendered)
                    st.reset_stall()
                    continue
                d = orch.decide(iteration_number, phase, rep, rendered, analysed_sig)
                if over_budget(ctx):
                    status = "token_budget"
                    break
                if d["next_agent"] == "stop":
                    status = "orchestrator_stop"
                    break
                if d["next_agent"] == "tester" and st.failure_was_analyzed(rep["sig"]):
                    log.log("tester_route_override", requested="tester", selected="writer",
                            failure_sig=rep["sig"], reason="failure analysis already exists for this unchanged failure")
                    d = {"next_agent": "writer", "task": "Use the existing failure analysis and behavioral spec. "
                         "Make a focused repair in the Rust implementation, then run the failing test."}
                elif d["next_agent"] == "reader" and st.reader_was_reviewed(rep["sig"]):
                    log.log("reader_route_override", requested="reader", selected="writer",
                            failure_sig=rep["sig"], reason="reader already reviewed this unchanged failure")
                    d = {"next_agent": "writer", "task": "Use the existing failure analysis and behavioral spec. "
                         "Make a focused repair in the Rust implementation, then run the failing test."}
                elif d["next_agent"] == "reader":
                    st.mark_reader_reviewed(rep["sig"])
                    log.log("reader_escalation", failure_sig=rep["sig"], iteration=iteration_number,
                            reason="orchestrator selected reader")
                brief = f"{d['task']}\n\nHarness feedback:\n{rendered}"
                if d["next_agent"] == "tester":
                    analysed_sig = rep["sig"]
                    agents["tester"].run("ANALYZE: " + brief)
                    st.mark_failure_analyzed(rep["sig"])
                    log.log("failure_analysis_reviewed", failure_sig=rep["sig"], iteration=iteration_number)
                elif d["next_agent"] == "reader":
                    agents["reader"].run(brief)
                else:
                    agents["writer"].run(brief)
            else:
                if not rep["core_ok"] or not rep["extra_ok"]:
                    st.restore("good")
                    log.log("revert", reason="tests broke", it=iteration_number)
                elif good_score is None or (rep["score"] is not None and rep["score"] < good_score):
                    good_score = rep["score"]
                    st.snapshot("good")
                    log.log("accept", score=good_score, it=iteration_number)
                else:
                    st.restore("good")
                    log.log("revert", reason="no improvement", it=iteration_number)
                if good_score == 0:
                    status = "success"
                    break
                if b_used >= cfg["phase_b_rounds"]:
                    status = "phase_b_done"
                    break
                b_used += 1
                task = (PROMPTS / "phase_b.md").read_text() + "\n\nCurrent metrics:\n" + rendered
                agents["writer"].run(task)
    except RequestBudgetReached as e:
        status = "request_budget"
        log.log("request_budget_stop", error=str(e))
    except TokenBudgetReached as e:
        status = "token_budget"
        log.log("budget_stop", error=str(e))
    except LLMError as e:
        status = f"llm_error: {e}"
        log.log("fatal", error=str(e))
    except KeyboardInterrupt:
        status = "interrupted"
        log.log("interrupted", note="run interrupted by user")
    finally:
        if phase == "B":
            st.restore("good")
        final = h.evaluate(full=True)
        ctx.ws.enforce_protected()
        result = {
            "status": status, "iterations": len(st.history), "phase": phase,
            "build_ok": final["build_ok"], "core": final["core"], "extra": final["extra"],
            "clippy": final["clippy"], "unsafe": final["unsafe"],
            "assertion_diagnostics": final.get("assertion_diagnostics"),
            "interface_missing": final["interface_missing"],
            "core_ok": final["core_ok"], "extra_ok": final["extra_ok"],
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
    ap.add_argument("--max-iterations", type=int, help="maximum outer repair iterations")
    ap.add_argument("--max-llm-requests", type=int,
                    help="hard cap on provider HTTP requests for this run, including retries")
    ap.add_argument("--cargo-target", help="optional Cargo target triple (useful for Windows GNU builds)")
    ap.add_argument("--continue", "--resume", dest="resume", action="store_true",
                    help="continue from the saved translation/specs and iteration history")
    ap.add_argument("--clean", action="store_true",
                    help="replace this project's translation from the template and clear its trajectory")
    ap.add_argument("--out-root", help="override output root (default: MP4/); used by tests")
    run(ap.parse_args())


if __name__ == "__main__":
    main()
