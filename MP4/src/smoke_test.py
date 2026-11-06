#!/usr/bin/env python3
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agents.base import parse_actions
from harness import parse_tests, builtin_unsafe_metrics
import pipeline


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        check.failed = True


check.failed = False

acts = parse_actions('x<action name="read_file" path="src/a.rs"/> y <action name="write_file" path="src/b.rs">\nfn a() -> i32 { 1 }\n</action>'
                     '<action name="done">ok</action>')
check([a["name"] for a in acts] == ["read_file", "write_file", "done"], "parse_actions finds 3 actions")
check(acts[1]["body"].strip() == "fn a() -> i32 { 1 }", "write_file body preserved")
check(parse_actions('<action name="write_file" path="x">abc')[0]["truncated"], "truncated write detected")

core, extra, ex = parse_tests("""     Running unittests src/lib.rs (target/debug/deps/demo-1)
test result: ok. 2 passed; 0 failed; 0 ignored
     Running tests/extra_a.rs (target/debug/deps/extra_a-1)
test t ... FAILED
test result: FAILED. 1 passed; 1 failed; 0 ignored
""")
check(core["passed"] == 2 and extra["failed"] == 1 and extra["failed_names"], "parse_tests splits core/extra")
um = builtin_unsafe_metrics(Path(sys.argv[1]) / "none") if len(sys.argv) > 1 else {}
check(um.get("unsafe_lines", 0) == 0, "unsafe estimator handles missing dir")

work = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path("/tmp/mp4_smoke")
shutil.rmtree(work, ignore_errors=True)
(work / "tpl/src").mkdir(parents=True)
(work / "tpl/src/bin").mkdir()
(work / "c").mkdir()
(work / "c/add.c").write_text("int add(int a, int b) { return a + b; }\n")
(work / "tpl/Cargo.toml").write_text('[package]\nname = "demo"\nversion = "0.1.0"\nedition = "2021"\n')
(work / "tpl/src/lib.rs").write_text("pub fn add(a: i32, b: i32) -> i32 {\n    todo!()\n}\n")
(work / "tpl/src/bin/t.rs").write_text("use demo::add;\nfn main() {}\n#[test]\nfn adds() {\n    assert_eq!(add(2, 3), 5);\n}\n")
orig_test = (work / "tpl/src/bin/t.rs").read_text()


class FakeLLM:
    usage = {"prompt": 0, "completion": 0, "calls": 0}
    total_tokens = 0

    def chat(self, messages, **kw):
        sysm, first = messages[0]["content"], len(messages) == 2
        self.usage["calls"] += 1
        if "ORCHESTRATOR" in sysm:
            return '{"next_agent": "writer", "task": "fix it", "reason": "r"}'
        if "READER" in sysm:
            return ('<action name="write_file" path="notes/spec.md">add returns a+b</action>' if first
                    else '<action name="done">spec written</action>')
        if "WRITER" in sysm and first and "SAFETY AND IDIOM" not in messages[1]["content"]:
            return ('<action name="write_file" path="src/lib.rs">\n```rust\npub fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n```\n</action>'
                    '<action name="write_file" path="src/bin/t.rs">// cheating</action>'
                    '<action name="write_file" path="Cargo.toml">x</action>'
                    '<action name="run_cargo" cmd="test"/>')
        return '<action name="done">done</action>'


args = SimpleNamespace(project=1, c_dir=str(work / "c"), rust_template=str(work / "tpl"),
                       max_iterations=8, out_root=str(work / "out"))
result = pipeline.run(args, llm=FakeLLM())
crate = work / "out/translations/project_1"
check(result["build_ok"] and result["core"]["passed"] == 1, "pipeline: crate builds and CRUST test passes")
check((crate / "src/bin/t.rs").read_text() == orig_test, "protected test file untouched")
check("[package]" in (crate / "Cargo.toml").read_text(), "protected Cargo.toml untouched")
check(result["status"] == "success", f"pipeline reached success (status={result['status']})")
check(result["clippy"] is not None and result["unsafe"] is not None, "final report has clippy + unsafe metrics")
check((work / "out/trajectories/project_1/trajectory.jsonl").is_file(), "trajectory written")
log = (work / "out/trajectories/project_1/trajectory.jsonl").read_text()
check("DENIED" in log, "denied writes appear in the trajectory")
print("\nOVERALL:", "FAILED" if check.failed else "ALL PASSED")
sys.exit(1 if check.failed else 0)
