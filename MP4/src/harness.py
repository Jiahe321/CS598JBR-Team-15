import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

CLIPPY_CATEGORIES = ["correctness", "style", "complexity", "perf"]
NOISE = re.compile(r"^\s*(Compiling|Downloaded|Downloading|Blocking|Updating|Locking|Adding)\b")


def tool_env():
    env = dict(os.environ)
    extra = ["/opt/homebrew/opt/rustup/bin", str(Path.home() / ".cargo/bin")]
    env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
    return env


def truncate(text, limit):
    if len(text) <= limit:
        return text
    head = int(limit * 0.75)
    tail = limit - head
    return text[:head] + f"\n...[{len(text) - limit} chars truncated]...\n" + text[-tail:]


def parse_tests(text):
    def bucket():
        return {"passed": 0, "failed": 0, "failed_names": []}
    core, extra = bucket(), bucket()
    cur = "?"
    for line in text.splitlines():
        m = re.match(r"\s*Running (.+?)(?: \(|$)", line)
        if m:
            cur = m.group(1)
            continue
        if re.match(r"\s*Doc-tests", line):
            cur = "doctests"
            continue
        b = extra if "tests/extra_" in cur else core
        m = re.match(r"test result: \w+\. (\d+) passed; (\d+) failed", line)
        if m:
            b["passed"] += int(m.group(1))
            b["failed"] += int(m.group(2))
            continue
        m = re.match(r"test (\S+) \.\.\. FAILED", line)
        if m:
            b["failed_names"].append(f"{cur}::{m.group(1)}")
    if "error: test failed" in text and core["failed"] == 0 and not core["failed_names"]:
        core["failed"] = 1
        core["failed_names"].append("(a test binary crashed before reporting results)")
    for b in (core, extra):
        b["total"] = b["passed"] + b["failed"]
    excerpts = []
    for m in re.finditer(r"---- (.+?) stdout ----\n(.*?)(?=\n---- |\nfailures:|\Z)", text, re.S):
        excerpts.append(f"[{m.group(1)}]\n{m.group(2).strip()[:700]}")
    return core, extra, excerpts[:8]


ASSERTION_MACRO = re.compile(r"\b(assert_eq|assert_ne|assert)!\s*\(")


def _matching_delimiter(text, opening, left, right):
    depth, i = 0, opening
    in_string = escaped = False
    line_comment = False
    block_depth = 0
    while i < len(text):
        if line_comment:
            if text[i] == "\n":
                line_comment = False
        elif block_depth:
            if text.startswith("/*", i):
                block_depth += 1
                i += 1
            elif text.startswith("*/", i):
                block_depth -= 1
                i += 1
        elif in_string:
            if escaped:
                escaped = False
            elif text[i] == "\\":
                escaped = True
            elif text[i] == '"':
                in_string = False
        elif text.startswith("//", i):
            line_comment = True
            i += 1
        elif text.startswith("/*", i):
            block_depth = 1
            i += 1
        elif text[i] == '"':
            in_string = True
        elif text[i] == left:
            depth += 1
        elif text[i] == right:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _matching_paren(text, opening):
    return _matching_delimiter(text, opening, "(", ")")


def _matching_brace(text, opening):
    return _matching_delimiter(text, opening, "{", "}")


ASSERTION_REPORT_HELPER = r'''mod assertion_report {
    use std::collections::BTreeMap;
    use std::fs;
    use std::panic::{catch_unwind, AssertUnwindSafe};
    use std::sync::{Mutex, OnceLock};

    #[derive(Default)]
    struct Entry {
        line: usize,
        kind: String,
        executions: usize,
        passed: usize,
        failed: usize,
        first_failure: String,
    }

    static RESULTS: OnceLock<Mutex<BTreeMap<usize, Entry>>> = OnceLock::new();

    pub fn begin() {
        std::panic::set_hook(Box::new(|_| {}));
    }

    pub fn check<F: FnOnce()>(id: usize, line: usize, kind: &str, assertion: F) {
        let outcome = catch_unwind(AssertUnwindSafe(assertion));
        let mut results = RESULTS.get_or_init(|| Mutex::new(BTreeMap::new()))
            .lock().expect("assertion report lock poisoned");
        let entry = results.entry(id).or_default();
        entry.line = line;
        entry.kind = kind.to_string();
        entry.executions += 1;
        match outcome {
            Ok(()) => entry.passed += 1,
            Err(payload) => {
                entry.failed += 1;
                if entry.first_failure.is_empty() {
                    let message = payload.downcast_ref::<String>().cloned()
                        .or_else(|| payload.downcast_ref::<&str>().map(|s| s.to_string()))
                        .unwrap_or_else(|| "non-string panic payload".to_string());
                    entry.first_failure = message.replace('\t', " ").replace('\n', " ");
                }
            }
        }
    }

    pub fn finish() {
        let results = RESULTS.get_or_init(|| Mutex::new(BTreeMap::new()))
            .lock().expect("assertion report lock poisoned");
        let mut report = String::from("id\tline\tmacro\texecutions\tpassed\tfailed\tfirst_failure\n");
        let mut executions = 0;
        let mut passed = 0;
        let mut failed = 0;
        for (id, entry) in results.iter() {
            executions += entry.executions;
            passed += entry.passed;
            failed += entry.failed;
            report.push_str(&format!("{}\t{}\t{}\t{}\t{}\t{}\t{}\n",
                id, entry.line, entry.kind, entry.executions, entry.passed,
                entry.failed, entry.first_failure));
        }
        let path = "assertion_diagnostics.tsv";
        fs::write(path, report).expect("could not write assertion diagnostics");
        println!("ASSERTION_DIAGNOSTIC sites={} executions={} passed={} failed={} report={}",
            results.len(), executions, passed, failed, path);
        if failed > 0 {
            panic!("{} assertion evaluations failed; see {}", failed, path);
        }
    }
}
'''


def instrument_assertions(source):
    """Instrument a temporary test copy; leave the benchmark source untouched."""
    matches = []
    for match in ASSERTION_MACRO.finditer(source):
        opening = source.find("(", match.start(), match.end())
        closing = _matching_paren(source, opening)
        if closing < 0:
            raise ValueError(f"could not parse assertion macro at line {source.count(chr(10), 0, match.start()) + 1}")
        line = source.count("\n", 0, match.start()) + 1
        end = closing + 1
        if end < len(source) and source[end] == ";":
            end += 1
        matches.append((match.start(), end, closing + 1, line, match.group(1)))
    if not matches:
        raise ValueError("no assertion macros found")

    instrumented = source
    for assertion_id, (start, end, call_end, line, kind) in reversed(list(enumerate(matches, 1))):
        call = source[start:call_end]
        replacement = (f'assertion_report::check({assertion_id}, {line}, "{kind}", '
                       f'|| {{ {call} }});')
        instrumented = instrumented[:start] + replacement + instrumented[end:]

    test_headers = list(re.finditer(
        r"#\[\s*test\s*\]\s*fn\s+\w+\s*\([^)]*\)\s*\{", instrumented
    ))
    if len(test_headers) != 1:
        raise ValueError("assertion diagnostics currently require exactly one #[test] function")
    test_header = test_headers[0]
    test_body_open = test_header.end() - 1
    close_pos = _matching_brace(instrumented, test_body_open)
    if close_pos < 0:
        raise ValueError("could not find the end of the #[test] function")
    instrumented = (instrumented[:test_header.end()] + "\n    assertion_report::begin();"
                    + instrumented[test_header.end():])
    # Inserting `begin` shifts the closing-brace offset by its byte length.
    close_pos += len("\n    assertion_report::begin();")
    instrumented = instrumented[:close_pos] + "    assertion_report::finish();\n" + instrumented[close_pos:]
    return ASSERTION_REPORT_HELPER + "\n" + instrumented, len(matches)


def interface_signatures(src_dir):
    sigs = set()
    pat = re.compile(r"pub\s+(?:const\s+)?fn\s+\w+\s*(?:<[^>]*>)?\s*\([^)]*\)\s*(?:->\s*[^{;]+)?")

    def canonicalize(signature):
        signature = re.sub(r"\s+", " ", signature).strip()
        match = re.match(r"(pub\s+(?:const\s+)?fn\s+\w+(?:\s*<[^>]*>)?)\s*\((.*)\)(.*)", signature)
        if not match:
            return signature

        prefix, params, suffix = match.groups()
        parts, start, depth = [], 0, 0
        for index, char in enumerate(params):
            if char in "(<[":
                depth += 1
            elif char in ")>]":
                depth -= 1
            elif char == "," and depth == 0:
                parts.append(params[start:index].strip())
                start = index + 1
        tail = params[start:].strip()
        if tail:
            parts.append(tail)

        normalized = []
        for part in parts:
            if ":" in part:
                name, typ = part.split(":", 1)
                # Parameter names (including `mut name`) are not part of a Rust API type.
                if re.fullmatch(r"(?:mut\s+)?[A-Za-z_][A-Za-z0-9_]*", name.strip()):
                    part = typ.strip()
            normalized.append(re.sub(r"\s+", "", part))
        suffix = re.sub(r"\s+", "", suffix.rstrip(","))
        prefix = re.sub(r"\s+", "", prefix)
        return f"{prefix}({','.join(normalized)}){suffix}"

    for f in Path(src_dir).rglob("*.rs"):
        for m in pat.finditer(f.read_text(errors="replace")):
            sigs.add(canonicalize(m.group(0)))
    return sigs


def builtin_unsafe_metrics(src_dir):
    m = {"unsafe_lines": 0, "unsafe_calls": 0, "unsafe_casts": 0, "pointer_arithmetic": 0,
         "unsafe_blocks": 0, "unsafe_fns": 0, "source": "builtin-estimate"}
    cast = re.compile(r"as\s+\*(const|mut)\b|\btransmute\b")
    arith = re.compile(r"\.(add|sub|offset|byte_add|byte_offset|wrapping_add|wrapping_sub)\s*\(")
    call = re.compile(r"\b[A-Za-z_][\w:]*\s*\(")
    for f in Path(src_dir).rglob("*.rs"):
        depth = 0
        in_unsafe = False
        for raw in f.read_text(errors="replace").splitlines():
            line = re.sub(r"//.*", "", raw).strip()
            if not line:
                continue
            starts = bool(re.search(r"\bunsafe\b", line))
            if starts:
                m["unsafe_fns" if re.search(r"unsafe\s+(extern\s+\"C\"\s+)?fn\b", line) else "unsafe_blocks"] += 1
            if starts and not in_unsafe:
                in_unsafe, depth, opened = True, 0, False
            if in_unsafe:
                m["unsafe_lines"] += 1
                m["unsafe_casts"] += len(cast.findall(line))
                m["pointer_arithmetic"] += len(arith.findall(line))
                m["unsafe_calls"] += len(call.findall(re.sub(r"\bunsafe\b", "", line)))
                depth += line.count("{") - line.count("}")
                opened = opened or "{" in line
                if opened and depth <= 0:
                    in_unsafe = False
    return m


class Harness:
    def __init__(self, crate, cfg):
        self.crate = Path(crate)
        self.cfg = cfg
        self.interface_sigs = set()
        self.last_report = None

    def cargo(self, args, timeout=None):
        env = tool_env()
        # On Windows, CreateProcess resolves a bare executable against the
        # parent PATH rather than the custom PATH passed in `env`.
        cargo = shutil.which("cargo", path=env.get("PATH")) or "cargo"
        target = self.cfg.get("cargo_target")
        if target and "--target" not in args:
            if "--" in args:
                i = args.index("--")
                args = [*args[:i], "--target", target, *args[i:]]
            else:
                args = [*args, "--target", target]
        cmd = [cargo, f"+{self.cfg['toolchain']}", *args]
        try:
            p = subprocess.run(
                cmd, cwd=self.crate, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                timeout=timeout or self.cfg["cargo_timeout_seconds"], env=env)
        except subprocess.TimeoutExpired as e:
            partial = e.stdout or ""
            if isinstance(partial, bytes):
                partial = partial.decode(errors="replace")
            detail = "TIMEOUT: command exceeded the time limit"
            if partial.strip():
                detail += "\nPartial output:\n" + partial
            return 124, detail
        except FileNotFoundError:
            return 127, "cargo not found; check PATH / rustup install"
        out = "\n".join(l for l in p.stdout.splitlines() if not NOISE.match(l))
        return p.returncode, out

    def build(self):
        rc, out = self.cargo(["build", "--all-targets"])
        heads = sorted(set(re.findall(r"^error(?:\[E\d+\])?: .*$", out, re.M)))
        return rc == 0, out, heads

    def test(self, target=None, test_filter=None):
        args = ["test", "--no-fail-fast"]
        if target:
            args.extend(["--test", target])
        if test_filter:
            args.extend(["--", test_filter])
        rc, out = self.cargo(args, timeout=self.cfg.get("cargo_test_timeout_seconds"))
        core, extra, excerpts = parse_tests(out)
        return rc, out, core, extra, excerpts

    def diagnose_assertions(self):
        """Run a failure-continuing diagnostic in a temporary crate copy only."""
        test_path = self.crate / "src" / "bin" / "test.rs"
        if not test_path.is_file():
            return {"status": "skipped", "reason": "src/bin/test.rs not found"}
        try:
            instrumented, site_count = instrument_assertions(test_path.read_text(encoding="utf-8"))
        except Exception as e:
            return {"status": "skipped", "reason": str(e)}

        try:
            with tempfile.TemporaryDirectory(prefix="mp4-assertion-diagnostic-") as temp_dir:
                diagnostic_crate = Path(temp_dir) / "crate"
                shutil.copytree(
                    self.crate, diagnostic_crate,
                    ignore=shutil.ignore_patterns("target", ".git"),
                )
                diagnostic_test = diagnostic_crate / "src" / "bin" / "test.rs"
                diagnostic_test.write_text(instrumented, encoding="utf-8")
                rc, output = Harness(diagnostic_crate, self.cfg).cargo(
                    ["test", "--bin", "test", "--", "--nocapture", "--test-threads=1"],
                    timeout=self.cfg.get("cargo_test_timeout_seconds"),
                )
                report = diagnostic_crate / "assertion_diagnostics.tsv"
                if not report.is_file():
                    return {
                        "status": "error", "reason": "diagnostic test did not produce its report",
                        "output": truncate(output, 1200),
                    }
                destination = Path(self.cfg.get(
                    "assertion_diagnostics_path", self.crate.parent / "assertion_diagnostics.tsv"
                ))
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(report, destination)

                executions = passed = failed = 0
                failed_sites = []
                for line in report.read_text(encoding="utf-8").splitlines()[1:]:
                    fields = line.split("\t", 6)
                    if len(fields) < 6:
                        continue
                    site_executions, site_passed, site_failed = map(int, fields[3:6])
                    executions += site_executions
                    passed += site_passed
                    failed += site_failed
                    if site_failed:
                        failed_sites.append({
                            "id": int(fields[0]), "line": int(fields[1]), "macro": fields[2],
                            "executions": site_executions, "passed": site_passed,
                            "failed": site_failed, "first_failure": fields[6] if len(fields) > 6 else "",
                        })
                return {
                    "status": "complete", "report": str(destination),
                    "assertion_sites": site_count, "executions": executions,
                    "passed": passed, "failed": failed, "failed_sites": failed_sites,
                    "diagnostic_exit_code": rc,
                }
        except Exception as e:
            return {"status": "error", "reason": f"{type(e).__name__}: {e}"}

    def clippy(self):
        counts, samples = {}, []
        for cat in CLIPPY_CATEGORIES:
            rc, out = self.cargo(["clippy", "--all-targets", "--all-features", "--message-format=json",
                                  "--", "-A", "clippy::all", "-W", f"clippy::{cat}"])
            seen = set()
            for line in out.splitlines():
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if obj.get("reason") != "compiler-message":
                    continue
                msg = obj["message"]
                code = (msg.get("code") or {}).get("code") or ""
                if not code.startswith("clippy::") or msg.get("level") not in ("warning", "error"):
                    continue
                span = next((s for s in msg.get("spans", []) if s.get("is_primary")), {})
                key = (code, span.get("file_name"), span.get("line_start"), span.get("column_start"))
                if key in seen:
                    continue
                seen.add(key)
                samples.append(f"{code} {span.get('file_name')}:{span.get('line_start')}: {msg['message']}")
            counts[cat] = len(seen)
        return counts, samples

    def unsafe_metrics(self):
        cmd = self.cfg.get("unsafe_metrics_cmd")
        if not cmd:
            return builtin_unsafe_metrics(self.crate / "src")
        full = [c.replace("{crate}", str(self.crate)) for c in cmd]
        try:
            p = subprocess.run(full, capture_output=True, text=True, timeout=120)
            out = p.stdout + p.stderr
        except (OSError, subprocess.TimeoutExpired) as e:
            return {"source": "official-tool-failed", "error": str(e)}
        try:
            data = json.loads(out)
            data["source"] = "official-tool"
            return data
        except ValueError:
            return {"source": "official-tool", "raw": truncate(out, 2000)}

    def interface_missing(self):
        have = interface_signatures(self.crate / "src")
        return sorted(s for s in self.interface_sigs if s not in have)

    def evaluate(self, full=False, safety=False):
        r = {"build_ok": False, "build_text": "", "build_errors": [], "core": None, "extra": None,
             "excerpts": [], "test_text": "", "clippy": None, "clippy_samples": [], "unsafe": None,
             "test_rc": None, "test_timed_out": False, "assertion_diagnostics": None,
             "interface_missing": self.interface_missing()}
        r["build_ok"], r["build_text"], r["build_errors"] = self.build()
        if r["build_ok"]:
            rc, out, core, extra, excerpts = self.test()
            r.update(test_rc=rc, test_timed_out=(rc == 124), test_text=out,
                     core=core, extra=extra, excerpts=excerpts)
            if core["failed"] > 0 and rc != 124:
                r["assertion_diagnostics"] = self.diagnose_assertions()
        # Interface conformance is part of the required benchmark contract. Do
        # not advance to Phase B (or report success) while a required public
        # signature has disappeared or changed, even if visible tests pass.
        r["core_ok"] = bool(
            r["build_ok"] and r["test_rc"] == 0 and r["core"] and r["core"]["failed"] == 0
            and r["core"]["total"] > 0 and not r["interface_missing"]
        )
        r["extra_ok"] = bool(r["extra"] is None or r["extra"]["failed"] == 0)
        if full and r["build_ok"]:
            r["clippy"], r["clippy_samples"] = self.clippy()
        if full or safety:
            r["unsafe"] = self.unsafe_metrics()
        if not r["build_ok"]:
            sig_src = r["build_errors"]
        elif r["test_timed_out"]:
            sig_src = ["TEST_TIMEOUT"]
        else:
            sig_src = r["core"]["failed_names"] if r["core"] else []
        r["sig"] = hashlib.md5("\n".join(sig_src).encode()).hexdigest()[:10] if sig_src else ""
        r["score"] = self.score(r)
        self.last_report = r
        return r

    @staticmethod
    def score(r):
        if not r.get("clippy") or not r.get("unsafe"):
            return None
        u = r["unsafe"]
        unsafe_total = sum(int(u.get(k, 0) or 0) for k in
                           ("unsafe_lines", "unsafe_calls", "unsafe_casts", "pointer_arithmetic"))
        return sum(r["clippy"].values()) + unsafe_total

    def render(self, r, limit=6000):
        parts = []
        if not r["build_ok"]:
            parts.append(f"BUILD FAILED ({len(r['build_errors'])} distinct errors). Compiler output:\n"
                         + truncate(r["build_text"], limit))
        elif r.get("test_timed_out"):
            parts.append(f"BUILD OK. TESTS TIMED OUT after {self.cfg.get('cargo_test_timeout_seconds', self.cfg['cargo_timeout_seconds'])} seconds; the 0/0 count is not a pass.\n"
                         + truncate(r["test_text"], limit))
        elif r.get("test_rc") not in (None, 0) and r["core"] and r["core"]["total"] == 0:
            parts.append(f"BUILD OK. TEST COMMAND FAILED (exit={r['test_rc']}); no test result was reported.\n"
                         + truncate(r["test_text"], limit))
        else:
            c, e = r["core"], r["extra"]
            parts.append(f"BUILD OK. CRUST tests: {c['passed']}/{c['total']} passed.")
            if e and e["total"]:
                parts.append(f"Agent-written extra tests: {e['passed']}/{e['total']} passed.")
            names = c["failed_names"] + e["failed_names"] if e else c["failed_names"]
            if names:
                parts.append("Failing tests: " + ", ".join(names[:20]))
            if r["excerpts"]:
                parts.append("Failure output:\n" + truncate("\n\n".join(r["excerpts"]), limit))
            diag = r.get("assertion_diagnostics")
            if diag and diag.get("status") == "complete":
                parts.append(
                    "ASSERTION DIAGNOSTIC (temporary copy only; does not change benchmark score): "
                    f"{diag['passed']}/{diag['executions']} passed, {diag['failed']} failed across "
                    f"{diag['assertion_sites']} source assertion sites. Full report: {diag['report']}"
                )
                if diag.get("failed_sites"):
                    parts.append("Failing assertion sites (original test line numbers):\n  " + "\n  ".join(
                        f"line {site['line']} {site['macro']} ({site['failed']}/{site['executions']} failed): "
                        f"{site['first_failure']}"
                        for site in diag["failed_sites"][:20]
                    ))
        if r["interface_missing"]:
            parts.append("INTERFACE WARNING: these original pub signatures are missing/changed:\n  "
                         + "\n  ".join(r["interface_missing"][:15]))
        if r["clippy"] is not None:
            parts.append(f"CLIPPY: {r['clippy']}")
            if r["clippy_samples"]:
                parts.append("Clippy findings:\n  " + "\n  ".join(r["clippy_samples"][:25]))
        if r["unsafe"] is not None:
            parts.append(f"UNSAFE METRICS: {json.dumps(r['unsafe'])}")
        return "\n".join(parts)
