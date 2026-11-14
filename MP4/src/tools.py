import fnmatch
import hashlib
import re
import subprocess
from pathlib import Path

from harness import tool_env, truncate

TEXT_EXT = {".c", ".h", ".rs", ".md", ".toml", ".txt", ".json", ".mk", ""}


class Workspace:
    def __init__(self, crate, c_dir, notes, cfg, harness):
        self.crate, self.c_dir, self.notes = Path(crate).resolve(), Path(c_dir).resolve(), Path(notes).resolve()
        self.notes.mkdir(parents=True, exist_ok=True)
        self.cfg, self.harness = cfg, harness
        self.protected_hashes = {}

    def resolve(self, vpath):
        v = (vpath or ".").strip().lstrip("/")
        if v == "c" or v.startswith("c/"):
            kind, root, rel = "c", self.c_dir, v[2:]
        elif v == "notes" or v.startswith("notes/"):
            kind, root, rel = "notes", self.notes, v[6:]
        elif v == "safety" or v.startswith("safety/"):
            kind, root, rel = "safety", Path(self.cfg["safety_output_dir"]).resolve(), v[7:]
        else:
            kind, root, rel = "crate", self.crate, v
        p = (root / rel).resolve()
        if p != root and root not in p.parents:
            raise PermissionError(f"path escapes workspace: {vpath}")
        return kind, root, p, v

    def _is_protected(self, v):
        c = self.cfg
        if any(fnmatch.fnmatch(v, g) for g in c["protected_exceptions"]):
            return False
        return any(fnmatch.fnmatch(v, g) for g in c["protected_globs"])

    def read_file(self, path, start=None, end=None):
        kind, root, p, v = self.resolve(path)
        if not p.is_file():
            return f"ERROR: no such file: {path}"
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        s = max(int(start or 1), 1)
        e = int(end) if end else len(lines)
        body = "\n".join(f"{i + 1:5d}  {l}" for i, l in enumerate(lines[s - 1:e], start=s - 1))
        return f"{path} ({len(lines)} lines)\n{body}"

    def list_dir(self, path="."):
        kind, root, p, v = self.resolve(path)
        if not p.is_dir():
            return f"ERROR: not a directory: {path}"
        out = []
        for f in sorted(p.rglob("*")):
            rel = f.relative_to(p)
            if any(part in ("target", ".git", "node_modules") or part.startswith(".") for part in rel.parts):
                continue
            if f.is_file():
                out.append(f"{rel}  ({f.stat().st_size} bytes)")
            if len(out) >= 200:
                out.append("...[more files not shown]")
                break
        return "\n".join(out) or "(empty)"

    def grep(self, pattern, path="."):
        kind, root, p, v = self.resolve(path)
        if not p.exists():
            return f"ERROR: no such path: {path}"
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return f"ERROR: bad regex: {e}"
        files = [p] if p.is_file() else sorted(x for x in p.rglob("*")
                                               if x.is_file() and x.suffix in TEXT_EXT and "target" not in x.parts)
        hits = []
        for f in files:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{f.relative_to(root)}:{i}: {line.strip()[:160]}")
                    if len(hits) >= 80:
                        return "\n".join(hits) + "\n...[truncated]"
        return "\n".join(hits) or "(no matches)"

    def write_file(self, path, content, write_globs):
        kind, root, p, v = self.resolve(path)
        if kind in {"c", "safety"}:
            return "DENIED: C source and safety evidence are read-only"
        if kind == "crate" and self._is_protected(v):
            return f"DENIED: {v} is a protected benchmark file (tests / Cargo.toml / interface config)"
        if not any(fnmatch.fnmatch(v, g) for g in write_globs):
            return f"DENIED: your role may only write: {', '.join(write_globs)}"
        if kind == "crate" and p.suffix == ".rs" and not content.strip():
            return "DENIED: refusing empty Rust source; provide the complete implementation"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"wrote {v} ({len(content.encode())} bytes, {content.count(chr(10))} lines)"

    def run_cargo(self, cmd, role, target=None, test_filter=None, target_kind=None):
        h = self.harness
        if (target or test_filter or target_kind) and cmd != "test":
            return 'ERROR: target, target_kind and filter are only valid with cmd="test"'
        if target_kind is not None and (target_kind not in {"bin", "test"} or not target):
            return "ERROR: target_kind requires a target and must be bin or test"
        if target and not re.fullmatch(r"[A-Za-z0-9_-]+", target):
            return "ERROR: test target must contain only letters, digits, '_' or '-'"
        if test_filter and any(ch in test_filter for ch in "\0\r\n"):
            return "ERROR: test filter must be a single line"
        if cmd == "check":
            rc, out = h.cargo(["check", "--all-targets"])
            return truncate(out, self.cfg["obs_limit_chars"]) if rc else "cargo check: OK"
        if cmd == "build":
            ok, out, _ = h.build()
            return "cargo build: OK" if ok else truncate(out, self.cfg["obs_limit_chars"])
        if cmd == "test":
            if target or test_filter:
                rc, out, _, _, _ = h.test(target=target, test_filter=test_filter, target_kind=target_kind)
                result_counts = re.findall(r"test result: .*?\b(\d+) passed; (\d+) failed;", out)
                ran_tests = any(int(passed) + int(failed) > 0 for passed, failed in result_counts)
                if rc == 124:
                    status = "TIMED OUT"
                elif rc == 0 and not ran_tests:
                    status = "NO TESTS EXECUTED"
                else:
                    status = "OK" if rc == 0 else f"FAILED (exit={rc})"
                return f"cargo test {status}:\n" + truncate(out, self.cfg["obs_limit_chars"])
            r = h.evaluate(full=False)
            return h.render(r, self.cfg["obs_limit_chars"])
        if cmd == "clippy":
            if role == "reader":
                return "DENIED"
            counts, samples = h.clippy()
            return f"CLIPPY: {counts}\n" + "\n".join(samples[:30])
        if cmd == "unsafe":
            import json
            return json.dumps(h.unsafe_metrics("agent_request"), indent=2)
        return "ERROR: cmd must be one of check|build|test|clippy|unsafe"

    def run_c_oracle(self, driver="notes/oracle.c", stdin=None):
        kind, root, drv, v = self.resolve(driver)
        if not drv.is_file():
            return f"ERROR: driver not found: {driver} (write it with write_file first)"
        main_rx = re.compile(r"\bint\s+main\s*\(")
        srcs = [f for f in sorted(self.c_dir.rglob("*.c"))
                if f.resolve() != drv and "tests" not in f.parts and not main_rx.search(f.read_text(errors="replace"))]
        incs = sorted({str(f.parent) for f in self.c_dir.rglob("*.h")} | {str(self.c_dir)})
        exe = self.notes / "oracle_bin"
        cmd = [self.cfg["c_compiler"], "-O0", "-g", "-std=gnu11", "-w", "-o", str(exe), str(drv), *map(str, srcs),
               *[f"-I{i}" for i in incs], "-lm"]
        comp = subprocess.run(cmd, capture_output=True, text=True)
        if comp.returncode:
            return "C COMPILE ERROR:\n" + truncate(comp.stderr, self.cfg["obs_limit_chars"])
        try:
            run = subprocess.run([str(exe)], input=stdin or "", capture_output=True, text=True,
                                 timeout=self.cfg["oracle_timeout_seconds"])
        except subprocess.TimeoutExpired:
            return "ORACLE TIMEOUT"
        return f"exit={run.returncode}\nSTDOUT:\n{truncate(run.stdout, 4000)}\nSTDERR:\n{truncate(run.stderr, 1500)}"

    def _protected_files(self):
        for f in self.crate.rglob("*"):
            if not f.is_file() or "target" in f.parts:
                continue
            rel = f.relative_to(self.crate).as_posix()
            if self._is_protected(rel):
                yield rel, f

    def snapshot_protected(self):
        self.protected_hashes = {rel: (hashlib.sha256(f.read_bytes()).hexdigest(), f.read_bytes())
                                 for rel, f in self._protected_files()}

    def enforce_protected(self):
        bad = []
        for rel, (h, data) in self.protected_hashes.items():
            f = self.crate / rel
            if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest() != h:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(data)
                bad.append(rel)
        return bad
