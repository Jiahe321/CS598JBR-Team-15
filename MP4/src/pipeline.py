#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from agents.base import Agent
from agents.orchestrator import Orchestrator
from harness import Harness, interface_signatures, _matching_delimiter
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


def archive_and_clean(root, project):
    """Keep the preceding source/results before rebuilding this project's outputs."""
    targets = [root / kind / f"project_{project}" for kind in ("translations", "trajectories")]
    for path in targets:
        # Reject redirected targets before any recursive copy or removal.
        if path.resolve() != path or not path.is_relative_to(root) or path.is_symlink():
            sys.exit(f"Refusing --clean for a redirected output directory: {path}")
        if path.exists() and not path.is_dir():
            sys.exit(f"Expected a generated output directory: {path}")
    existing = [path for path in targets if path.exists()]
    if not existing:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    backup = root / "backups" / f"project_{project}_{stamp}"
    if backup.resolve() != backup or not backup.resolve().is_relative_to(root):
        sys.exit(f"Backup directory escapes the output root: {backup}")
    backup.mkdir(parents=True, exist_ok=False)
    (backup / ".gitignore").write_text("*\n", encoding="utf-8")
    for path in existing:
        shutil.copytree(path, backup / path.parent.name / path.name,
                        ignore=shutil.ignore_patterns("target", ".git", "__pycache__"))
    # Only remove originals after every source/results copy completed successfully.
    for path in existing:
        shutil.rmtree(path)
    print(f"Previous project {project} source and results archived at {backup}", flush=True)
    return backup


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
    backup = archive_and_clean(root, args.project) if getattr(args, "clean", False) else None
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
    # Read saved review state before appending this run's setup event.
    ctx.state = State(crate, traj, resume=bool(getattr(args, "resume", False)))
    ctx.logger = Logger(traj)
    ctx.logger.log("setup", started_at=datetime.now(timezone.utc).isoformat(),
                   project=args.project, layout_moves=moved,
                   template=str(template), c_dir=str(Path(args.c_dir).resolve()),
                   model=mcfg.get("model"), toolchain=cfg.get("toolchain"),
                   resume=bool(getattr(args, "resume", False)),
                   clean=bool(getattr(args, "clean", False)),
                   previous_outputs_backup=str(backup) if backup else None,
                   cargo_target=cfg.get("cargo_target"),
                   max_iterations=cfg.get("max_iterations"),
                   max_llm_requests=cfg.get("max_llm_requests_per_run"),
                   token_budget=cfg.get("max_total_tokens"))
    ctx.logger.log("review_state_restored", evidence_complete=True,
                   reader_reviewed_signatures=sorted(ctx.state.reader_reviewed_signatures),
                   failure_analysis_signatures=sorted(ctx.state.failure_analysis_signatures))
    mcfg["max_total_tokens"] = cfg["max_total_tokens"]
    mcfg["max_llm_requests_per_run"] = cfg["max_llm_requests_per_run"]
    ctx.llm = llm or LLM(mcfg, ctx.logger)
    ctx.harness = Harness(crate, cfg)
    ctx.harness.interface_sigs = interface_signatures(template / "src")
    ctx.ws = Workspace(crate, args.c_dir, traj / "notes", cfg, ctx.harness)
    ctx.ws.snapshot_protected()
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
    budget = ctx.cfg.get("max_total_tokens")
    return budget is not None and ctx.llm.total_tokens >= budget


def _source_excerpt(path, virtual, start=1, end=None):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    end = min(end or len(lines), len(lines))
    body = "\n".join(f"{index + 1:5d}  {lines[index]}"
                     for index in range(max(0, start - 1), end))
    return {"path": virtual, "content": f"{virtual} ({len(lines)} lines)\n{body}"}


def initial_evidence(ctx, role, include_notes=False):
    """Supply complete initial inputs without spending limited file-read actions."""
    sources = []
    if role == "writer" or include_notes:
        sources.extend((path, "notes/" + path.name)
                       for path in sorted(ctx.ws.notes.glob("spec*.md")) if path.is_file())
    manifest = ctx.crate / "Cargo.toml"
    if manifest.is_file():
        sources.append((manifest, "Cargo.toml"))
    sources.extend((path, path.relative_to(ctx.crate).as_posix())
                   for path in sorted((ctx.crate / "src").rglob("*.rs")) if path.is_file())
    sources.extend((path, "c/" + path.relative_to(ctx.ws.c_dir).as_posix())
                   for path in sorted(ctx.ws.c_dir.rglob("*"))
                   if path.is_file() and path.suffix.lower() in {".c", ".h"}
                   and not any(part in {"doc", "target", ".git"}
                               for part in path.relative_to(ctx.ws.c_dir).parts))
    evidence, omitted = [], []
    limit = max(0, int(ctx.cfg.get("initial_evidence_max_chars", 120000)))
    remaining = limit
    for path, virtual in sources:
        # Apply the same path boundaries as tool reads to controller-provided data.
        ctx.ws.resolve(virtual)
        item = _source_excerpt(path, virtual)
        size = len(item["content"])
        if size > remaining:
            omitted.append(virtual)
            continue
        evidence.append(item)
        remaining -= size
    ctx.logger.log("initial_source_packet", agent=role,
                   paths=[item["path"] for item in evidence],
                   content_chars=limit - remaining, char_limit=limit, omitted_paths=omitted)
    return evidence, omitted


def _function_intervals(text, names, rust=False):
    intervals = []
    for name in sorted(names):
        if rust:
            pattern = r"\bfn\s+" + re.escape(name) + r"\s*(?:<[^>]*>)?\s*\("
        else:
            pattern = r"(?m)^" + re.escape(name) + r"[ \t]*\("
        for match in re.finditer(pattern, text):
            brace = text.find("{", match.end())
            semicolon = text.find(";", match.end())
            if brace < 0 or (semicolon >= 0 and semicolon < brace):
                continue
            end = _matching_delimiter(text, brace, "{", "}")
            if end < 0:
                continue
            start_line = max(1, text.count("\n", 0, match.start()) - 4)
            end_line = text.count("\n", 0, end) + 1
            intervals.append((start_line, end_line))
    return sorted(set(intervals))


def repair_evidence(ctx, report, role):
    """Supply bounded real source context instead of spending agent turns finding files."""
    if role == "writer" and report and not report.get("build_ok", True):
        packet, seen, remaining = [], set(), 48000
        for match in re.finditer(r"\b(src[\\/][^\s:]+\.rs):\d+", report.get("build_text", "")):
            virtual = match.group(1).replace("\\", "/")
            path = (ctx.crate / virtual).resolve()
            if (virtual in seen or ctx.crate.resolve() not in path.parents or not path.is_file()
                    or ctx.ws._is_protected(virtual)):
                continue
            seen.add(virtual)
            item = _source_excerpt(path, virtual)
            if len(item["content"]) <= remaining:
                packet.append(item)
                remaining -= len(item["content"])
        if packet:
            return packet
    evidence, identifiers = [], set()
    for detail in (report or {}).get("failure_details", [])[:1]:
        match = re.match(r"(.+?):(\d+)(?::\d+)?$", detail.get("location", ""))
        if not match:
            continue
        relative = match.group(1).replace("\\", "/")
        path = (ctx.crate / relative).resolve()
        if ctx.crate.resolve() not in path.parents or not path.is_file():
            continue
        virtual = path.relative_to(ctx.crate).as_posix()
        line = int(match.group(2))
        excerpt = _source_excerpt(path, virtual, max(1, line - 18), line + 10)
        evidence.append(excerpt)
        identifiers.update(re.findall(r"(?:\.|::)([A-Za-z_]\w*)\s*\(", excerpt["content"]))
        # A panic inside a callback often reports a line near the top of the
        # file, while its state was prepared much later by the calling test.
        text = path.read_text(encoding="utf-8", errors="replace")
        offset = sum(len(part) for part in text.splitlines(keepends=True)[:line - 1])
        functions = list(re.finditer(r"\bfn\s+([A-Za-z_]\w*)\s*\(", text[:offset]))
        for function in reversed(functions):
            brace = text.find("{", function.end())
            end = _matching_delimiter(text, brace, "{", "}") if brace >= 0 else -1
            if not brace < offset <= end:
                continue
            name = function.group(1)
            identifiers.add(name)
            callers = [reference for reference in re.finditer(r"\b" + re.escape(name) + r"\b", text)
                       if not function.start() <= reference.start() <= end]
            for reference in callers[:2]:
                caller_line = text.count("\n", 0, reference.start()) + 1
                caller = _source_excerpt(path, virtual, max(1, caller_line - 18), caller_line + 10)
                evidence.append(caller)
                identifiers.update(re.findall(r"(?:\.|::)([A-Za-z_]\w*)\s*\(", caller["content"]))
            break

    sources = []
    for path in sorted((ctx.crate / "src").rglob("*.rs")):
        virtual = path.relative_to(ctx.crate).as_posix()
        if ctx.ws._is_protected(virtual):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        functions = set(re.findall(r"\bfn\s+([A-Za-z_]\w*)\s*(?:<[^>]*>)?\s*\(", text))
        sources.append((len(functions & identifiers), path, functions))
    sources.sort(key=lambda item: (-item[0], str(item[1])))
    selected = [item for item in sources if item[0]][:1]
    if not selected and len(sources) == 1:
        selected = sources
    if role == "writer":
        for _, path, _ in selected:
            if path.stat().st_size <= 40000:
                evidence.append(_source_excerpt(path, path.relative_to(ctx.crate).as_posix()))
    elif role == "tester":
        for _, path, functions in selected:
            text = path.read_text(encoding="utf-8", errors="replace")
            intervals = _function_intervals(text, identifiers, rust=True)
            # Include directly called private helpers, without sending every unrelated method.
            called = set()
            lines = text.splitlines()
            for start, end in intervals:
                called.update(re.findall(r"\b([A-Za-z_]\w*)\s*\(", "\n".join(lines[start - 1:end])))
            intervals = _function_intervals(text, identifiers | (called & functions), rust=True)
            for start, end in intervals[:12]:
                evidence.append(_source_excerpt(path, path.relative_to(ctx.crate).as_posix(), start, end))

    modules = {path.stem for _, path, _ in selected}
    c_files = sorted(path for path in ctx.ws.c_dir.rglob("*")
                     if path.is_file() and path.suffix.lower() in {".c", ".h"}
                     and not any(part in {"doc", "target", ".git"} for part in path.relative_to(ctx.ws.c_dir).parts))
    preferred = [path for path in c_files if path.stem in modules or path.stem.removesuffix("_test") in modules]
    if not preferred and len(c_files) <= 3:
        preferred = c_files
    preferred.sort(key=lambda path: (path.suffix == ".h", path.stem.endswith("_test"), str(path)))
    for path in preferred:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        starts = []
        for name in sorted(identifiers):
            matches = list(re.finditer(r"\b" + re.escape(name) + r"\s*\(", text))
            for match in matches[:2]:
                starts.append(text.count("\n", 0, match.start()) + 1)
        if path.suffix == ".h" or not starts:
            starts.insert(0, 1)
        intervals = _function_intervals(text, identifiers) if path.suffix == ".c" else []
        for line in sorted(set(starts)):
            if path.suffix == ".c" and not path.stem.endswith("_test") and intervals:
                break
            start, end = max(1, line - 10), min(len(lines), line + 55)
            if intervals and start <= intervals[-1][1] + 1:
                intervals[-1] = (intervals[-1][0], max(intervals[-1][1], end))
            else:
                intervals.append((start, end))
        virtual = "c/" + path.relative_to(ctx.ws.c_dir).as_posix()
        for start, end in intervals[:4]:
            evidence.append(_source_excerpt(path, virtual, start, end))

    result, remaining = [], 24000 if role == "tester" else 48000
    for item in evidence:
        if len(item["content"]) <= remaining:
            result.append(item)
            remaining -= len(item["content"])
    return result


def review_complete(agent, role):
    evidence = agent.last_run
    if not evidence.get("completed") or evidence.get("missing_evidence") or not evidence.get("c_evidence"):
        return False
    paths = evidence.get("wrote_paths", [])
    if role == "reader":
        return any(path.startswith("notes/spec") for path in paths)
    return "notes/failure_analysis.md" in paths


def analysis_validation_error(ctx, report):
    """Return a concrete format/source error, without certifying the proposed cause."""
    path = ctx.ws.notes / "failure_analysis.md"
    details = (report or {}).get("failure_details") or []
    if not path.is_file():
        return "missing notes/failure_analysis.md"
    if not details:
        return "harness report has no first-failure details"
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > 5000:
        return f"analysis exceeds 5000 characters ({len(text)})"
    # Parse entire labelled sections. Prose and bullet lists can follow a label
    # on subsequent lines; typography does not establish causal correctness.
    labels = ("Analysis-Version", "Failure", "Observed", "Expected", "C-Evidence",
              "Rust-Evidence", "Trace", "Hypothesis", "Unresolved")
    headings = list(re.finditer(r"(?mi)^[ \t]*(?:\#{1,6}[ \t]+)?(" + "|".join(labels)
                                + r"):[ \t]*", text))
    fields = {}
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        fields.setdefault(heading.group(1).lower(), []).append(text[heading.end():end].strip())
    if fields.get("analysis-version") != ["1"]:
        return "missing Analysis-Version: 1"
    detail = details[0]
    required = {"Failure": detail.get("location", ""), "Observed": detail.get("actual", ""),
                "Expected": detail.get("expected", "")}
    for label, value in required.items():
        if not value:
            continue
        if fields.get(label.lower()) != [value]:
            return f"{label} must match the current failure: {value}"
    for label, expected_kind in (("C-Evidence", "c"), ("Rust-Evidence", "crate")):
        entries = fields.get(label.lower(), [])
        if not entries:
            return f"missing {label} source citations"
        for entry in entries:
            # Extract references independently of surrounding prose. Descriptions
            # can contain commas/semicolons, so splitting the whole section on
            # punctuation would mistake an explanation for another citation.
            citations = list(re.finditer(
                r"(?<![\w./\\-])([\w./\\-]+\.[A-Za-z]\w*):([^\s`<>()\[\]{},;]+)", entry))
            if not citations:
                return f"missing {label} source citations in path:START-END form"
            for citation in citations:
                virtual = citation.group(1).replace("\\", "/")
                location = citation.group(2).rstrip(".:")
                lines = re.fullmatch(r"(\d+)(?:-(\d+))?", location)
                if not lines:
                    return f"invalid {label} range: {citation.group(0)!r}; expected path:START-END"
                try:
                    kind, _, source, _ = ctx.ws.resolve(virtual)
                    if kind != expected_kind or not source.is_file():
                        return f"{label} source is missing or outside {expected_kind}: {virtual}"
                    count = len(source.read_text(encoding="utf-8", errors="replace").splitlines())
                    start, end = int(lines.group(1)), int(lines.group(2) or lines.group(1))
                    if not 1 <= start <= end <= count:
                        return f"{label} range is outside source lines 1-{count}: {virtual}:{location}"
                except (OSError, PermissionError) as error:
                    return f"cannot read {label} citation {virtual}:{location}: {error}"
    for label in ("Trace", "Hypothesis"):
        if not any(fields.get(label.lower(), [])):
            return f"missing nonempty {label} section"
    return None


def analysis_matches(ctx, report):
    """Validate scope and cited locations; the proposed cause remains a hypothesis to test."""
    return analysis_validation_error(ctx, report) is None


def _call_agent_with_budget(ctx, agent, task, evidence, focused):
    """Reserve real provider requests for Writer, including HTTP retries."""
    initial_reader = agent.name == "reader" and not focused
    if agent.name == "writer" or (not focused and not initial_reader):
        return agent.run(task, evidence=evidence)
    usage = getattr(ctx.llm, "usage", {})
    used = usage.get("requests", usage.get("calls", 0))
    global_limit = ctx.cfg.get("max_llm_requests_per_run")
    reserve = int(ctx.cfg.get("writer_reserved_requests", 6))
    allowance = int(ctx.cfg.get("reader_initial_max_requests", 6) if initial_reader
                    else ctx.cfg.get("tester_analysis_max_requests", 3))
    if global_limit is not None:
        allowance = min(allowance, max(0, global_limit - used - reserve))
    if allowance < 1:
        raise RequestBudgetReached("remaining requests are reserved for Writer; cannot start another analysis")
    settings = getattr(ctx.llm, "cfg", None)
    saved = {}
    if settings is not None:
        for key in ("max_llm_requests_per_run", "max_total_tokens"):
            saved[key] = (key in settings, settings.get(key))
        settings["max_llm_requests_per_run"] = used + allowance
        global_tokens = ctx.cfg.get("max_total_tokens")
        if global_tokens is not None:
            token_reserve = min(int(ctx.cfg.get("writer_reserved_tokens", 100000)),
                                int(global_tokens) // 2)
            stage_tokens = int(ctx.cfg.get("reader_initial_max_tokens", 160000) if initial_reader
                               else ctx.cfg.get("analysis_max_tokens", 60000))
            settings["max_total_tokens"] = min(int(global_tokens) - token_reserve,
                                                ctx.llm.total_tokens + stage_tokens)
    ctx.logger.log("agent_budget", agent=agent.name, request_allowance=allowance,
                   writer_reserved_requests=reserve)
    task += (f"\nYour request allowance is {allowance} replies including completion. Reserve the last "
             "reply for write_file and done; perform only essential inspection before then.")
    try:
        return agent.run(task, evidence=evidence, request_limit=allowance)
    except (RequestBudgetReached, TokenBudgetReached) as error:
        agent.last_run = {"completed": False, "wrote_paths": [], "c_evidence": [],
                          "test_evidence": [], "missing_evidence": True, "spec_gap": False}
        ctx.logger.log("analysis_budget_stop", agent=agent.name, error=str(error))
        return "EVIDENCE_REQUIRED: analysis budget reached; preserve Writer's budget"
    finally:
        if settings is not None:
            for key, (existed, value) in saved.items():
                if existed:
                    settings[key] = value
                else:
                    settings.pop(key, None)


def run_agent_task(ctx, agent, task, report=None):
    """Retry missing evidence once, then stop clearly instead of burning unchanged iterations."""
    file_map = ["c/" + path.relative_to(ctx.ws.c_dir).as_posix()
                for path in sorted(ctx.ws.c_dir.rglob("*"))
                if path.is_file() and path.suffix.lower() in {".c", ".h"}
                and "doc" not in path.relative_to(ctx.ws.c_dir).parts][:40]
    task += "\n\nConfirmed C source paths: " + ", ".join(file_map)
    initial_pass = report is None and agent.name in {"reader", "writer"}
    if report:
        task += ("\nFocus on the first actual panic/assertion. Assertion-diagnostic callbacks are downstream "
                 "symptoms, not proof that card construction or another guessed function is broken. "
                 "Use source evidence to establish the cause before changing behavior.")
    elif initial_pass:
        task += ("\nThis is initial translation, not a repair of an existing panic. The controller supplies "
                 "complete current Rust files, C sources/headers/tests, and available specifications within "
                 "a bounded source packet. Use that packet immediately; do not rediscover its paths or "
                 "reread complete supplied files. Generate the requested specifications or implementation "
                 "from the actual C behavior. Only read essential files explicitly listed as omitted.")
    focused_analysis = agent.name == "tester" and task.lstrip().startswith("ANALYZE:") and bool(report)
    if focused_analysis:
        first = (report.get("failure_details") or [{}])[0]
        task += ("\n\nAnalyze only this first failure, not every diagnostic callback. Within your request allowance "
                 "write notes/failure_analysis.md (under 5000 characters) and call done. Use these literal labels:\n"
                 "Analysis-Version: 1\nFailure: " + first.get("location", "unknown")
                 + "\nObserved: " + first.get("actual", "unknown") + "\nExpected: " + first.get("expected", "unknown")
                 + "\nC-Evidence: c/existing.c:START-END\nRust-Evidence: src/existing.rs:START-END\n"
                 "Trace: input/state -> actual operation -> observed result\nHypothesis: a focused suspected fix\n"
                 "Unresolved: missing evidence or contract differences\n"
                 "Trace and Hypothesis may use multiline prose or bullet lists. Citation fields may list "
                 "multiple path:START-END references. The state trace must explain prior state changes, "
                 "the actual failing operation, and its result; arrows are optional. "
                 "Citations must reference real lines. Trace the actual Rust branch and selection arithmetic; "
                 "array initialization order alone does not establish dealing order. Do not certify unrelated "
                 "functions or promise that one hypothesis clears all assertions. Report SPEC_GAP: with "
                 "side-by-side evidence if the protected setup omits a required C operation.")
    for attempt in range(1 if focused_analysis else 2):
        invocation_task = task
        if initial_pass:
            evidence, omitted = initial_evidence(ctx, agent.name, include_notes=attempt > 0)
            if omitted:
                invocation_task += "\nNot included in the initial packet: " + ", ".join(omitted)
            else:
                invocation_task += "\nAll listed initial source files are included completely."
        else:
            evidence = repair_evidence(ctx, report, agent.name) if report else []
        summary = _call_agent_with_budget(ctx, agent, invocation_task, evidence, bool(report))
        info = agent.last_run
        ctx.last_task_result = {"agent": agent.name, "attempt": attempt + 1,
                                "summary": summary, "evidence": info}
        if info.get("spec_gap"):
            ctx.logger.log("spec_gap", agent=agent.name, failure_sig=(report or {}).get("sig"),
                           summary=summary, evidence=info)
            return "spec_gap"
        if agent.name in {"reader", "tester"}:
            produced = review_complete(agent, agent.name)
            if focused_analysis and produced:
                error = analysis_validation_error(ctx, report)
                if error:
                    produced = False
                    ctx.logger.log("analysis_rejected", failure_sig=report["sig"], reason=error)
        else:
            produced = any(path.startswith("src/") for path in info.get("wrote_paths", []))
        if info.get("completed") and not info.get("missing_evidence") and produced:
            return "completed"
        ctx.logger.log("agent_incomplete", agent=agent.name, attempt=attempt + 1,
                       failure_sig=(report or {}).get("sig"), summary=summary, evidence=info)
        if not focused_analysis and attempt == 0 and not over_budget(ctx):
            task += ("\n\nThe previous attempt did not produce a completed, evidenced result: " + summary
                     + "\nUse the supplied source excerpts first. Write the requested analysis/specification "
                     "or repair, and call done. If essential evidence is still missing, call done with "
                     "EVIDENCE_REQUIRED: and the exact missing excerpt. Do not repeat broad inspection.")
            continue
        return "evidence_required"


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
            outcome = run_agent_task(ctx, agents["reader"], "Read the C project, the Rust interface and the tests, "
                                     "then write the spec (notes/spec.md plus one notes/spec_<module>.md per module).")
            if outcome != "completed":
                status = outcome
            if over_budget(ctx):
                status = "token_budget"
            elif status not in {"spec_gap", "evidence_required"}:
                outcome = run_agent_task(ctx, agents["writer"], "Create the initial Rust translation. Read "
                                         "notes/spec.md first, then the Rust interface in src/ and the tests. "
                                         "Get `run_cargo cmd=\"check\"` to pass, then `cmd=\"test\"`.")
                if outcome != "completed":
                    status = outcome
                if over_budget(ctx):
                    status = "token_budget"
        for it in range(1, cfg["max_iterations"] + 1) if status not in {
                "token_budget", "spec_gap", "evidence_required"} else ():
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
            reviewed = st.failure_was_analyzed(rep["sig"])
            analysis_error = analysis_validation_error(ctx, rep) if reviewed else None
            analysis_ready = reviewed and analysis_error is None
            analysed_sig = rep["sig"] if analysis_ready else None
            if reviewed and not analysis_ready:
                log.log("analysis_invalidated", failure_sig=rep["sig"], reason=analysis_error)
            st.record(it, phase, rep)
            bad = ctx.ws.enforce_protected()
            if bad:
                log.log("integrity_violation", files=bad)
            focused_report = dict(rep)
            if phase == "A":
                focused_report["assertion_diagnostics"] = None
                focused_report["failure_details"] = rep.get("failure_details", [])[:1]
            rendered = h.render(focused_report, cfg["obs_limit_chars"])
            log.log("iteration", it=iteration_number, phase=phase, build_ok=rep["build_ok"], core=rep["core"],
                    extra=rep["extra"], clippy=rep["clippy"], unsafe=rep["unsafe"], score=rep["score"],
                    failure_sig=rep["sig"], failure_details=rep.get("failure_details", []))
            print(f"[iter {iteration_number} phase {phase}] build={'ok' if rep['build_ok'] else 'FAIL'} "
                  f"core={rep['core'] and (rep['core']['passed'], rep['core']['total'])} "
                  f"score={rep['score']} tokens={ctx.llm.total_tokens}", flush=True)

            if phase == "A":
                if rep["core_ok"] and rep["extra_ok"]:
                    if getattr(args, "stop_after_tests", False):
                        status = "tests_passed"
                        log.log("tests_passed", note="stopping before test generation or quality edits")
                        break
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
                    outcome = run_agent_task(ctx, agents["writer"],
                                             f"{repair_task}\n\nHarness feedback:\n{rendered}", rep)
                    if outcome != "completed":
                        status = outcome
                        break
                    continue
                if st.stalled(cfg["stall_rounds"]):
                    if st.reader_was_reviewed(rep["sig"]):
                        status = "stalled"
                        break
                    log.log("reader_escalation", failure_sig=rep["sig"], iteration=iteration_number,
                            reason="repeated identical harness failure")
                    outcome = run_agent_task(ctx, agents["reader"], "The writer is stuck on the same failure. "
                                             "Re-read the relevant C code and extend notes/spec*.md with the "
                                             "exact missing behaviour.\n\n" + rendered, rep)
                    if outcome != "completed":
                        status = outcome
                        break
                    st.mark_reader_reviewed(rep["sig"])
                    log.log("reader_reviewed", failure_sig=rep["sig"], evidence_complete=True)
                    st.reset_stall()
                    continue
                if analysis_ready:
                    d = {"next_agent": "writer", "task":
                         "Repair the first observed failure using notes/failure_analysis.md as a hypothesis. "
                         "Check its trace against the supplied Rust and C code before implementing. "
                         "Preserve the required interfaces and tests. Make the smallest behaviorally justified "
                         "repair, then run cargo check and the failing test. Do not re-analyze all diagnostic callbacks."}
                else:
                    d = {"next_agent": "tester", "task":
                         "Analyze only the first observed panic, its setup, and the directly involved Rust/C "
                         "operations. Produce a short source-backed state trace and focused repair hypothesis."}
                log.log("repair_route", selected=d["next_agent"], failure_sig=rep["sig"],
                        reason="completed focused analysis goes directly to Writer; no planning API request")
                if over_budget(ctx):
                    status = "token_budget"
                    break
                if d["next_agent"] == "stop":
                    status = "orchestrator_stop"
                    break
                if d["next_agent"] == "tester" and analysis_ready:
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
                    log.log("reader_escalation", failure_sig=rep["sig"], iteration=iteration_number,
                            reason="orchestrator selected reader")
                brief = f"{d['task']}\n\nHarness feedback:\n{rendered}"
                if d["next_agent"] == "tester":
                    outcome = run_agent_task(ctx, agents["tester"], "ANALYZE: " + brief, rep)
                    if outcome != "completed":
                        status = outcome
                        break
                    analysed_sig = rep["sig"]
                    st.mark_failure_analyzed(rep["sig"])
                    log.log("failure_analysis_reviewed", failure_sig=rep["sig"], iteration=iteration_number,
                            evidence_complete=True)
                elif d["next_agent"] == "reader":
                    outcome = run_agent_task(ctx, agents["reader"], brief, rep)
                    if outcome != "completed":
                        status = outcome
                        break
                    st.mark_reader_reviewed(rep["sig"])
                    log.log("reader_reviewed", failure_sig=rep["sig"], evidence_complete=True)
                else:
                    outcome = run_agent_task(ctx, agents["writer"], brief, rep)
                    if outcome != "completed":
                        status = outcome
                        break
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
        final = h.last_report
        evaluation_complete = False
        try:
            if status != "interrupted":
                final = h.evaluate(full=True)
                evaluation_complete = True
        except KeyboardInterrupt:
            status = "interrupted"
            log.log("interrupted", note="final evaluation interrupted; retaining the last completed report")
        if final is None:
            final = {"build_ok": False, "core": None, "extra": None, "clippy": None, "unsafe": None,
                     "interface_missing": [], "core_ok": False, "extra_ok": False}
        ctx.ws.enforce_protected()
        result = {
            "status": status, "iterations": len(st.history), "phase": phase,
            "build_ok": final["build_ok"], "core": final["core"], "extra": final["extra"],
            "clippy": final["clippy"], "unsafe": final["unsafe"],
            "assertion_diagnostics": final.get("assertion_diagnostics"),
            "interface_missing": final["interface_missing"],
            "core_ok": final["core_ok"], "extra_ok": final["extra_ok"],
            "tokens": ctx.llm.usage,
            "evaluation_complete": evaluation_complete,
            "failure_details": final.get("failure_details", []),
            "failure_sig": final.get("sig", ""),
        }
        if status in {"evidence_required", "spec_gap"}:
            result["stop_details"] = getattr(ctx, "last_task_result", None)
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
    ap.add_argument("--stop-after-tests", action="store_true",
                    help="stop once core and extra tests pass, before generation or quality edits; use with --continue to check an existing translation")
    ap.add_argument("--cargo-target", help="optional Cargo target triple (useful for Windows GNU builds)")
    ap.add_argument("--continue", "--resume", dest="resume", action="store_true",
                    help="continue from the saved translation/specs and iteration history")
    ap.add_argument("--clean", action="store_true",
                    help="archive this project's previous outputs, then regenerate from the template")
    ap.add_argument("--out-root", help="override output root (default: MP4/); used by tests")
    run(ap.parse_args())


if __name__ == "__main__":
    main()
