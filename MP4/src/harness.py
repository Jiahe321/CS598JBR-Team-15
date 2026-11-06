import hashlib
import json
import os
import re
import shutil
import subprocess
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
        except subprocess.TimeoutExpired:
            return 124, "TIMEOUT: command exceeded the time limit (infinite loop in a test?)"
        except FileNotFoundError:
            return 127, "cargo not found; check PATH / rustup install"
        out = "\n".join(l for l in p.stdout.splitlines() if not NOISE.match(l))
        return p.returncode, out

    def build(self):
        rc, out = self.cargo(["build", "--all-targets"])
        heads = sorted(set(re.findall(r"^error(?:\[E\d+\])?: .*$", out, re.M)))
        return rc == 0, out, heads

    def test(self):
        rc, out = self.cargo(["test", "--no-fail-fast"])
        core, extra, excerpts = parse_tests(out)
        return rc, out, core, extra, excerpts

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

    def evaluate(self, full=False):
        r = {"build_ok": False, "build_text": "", "build_errors": [], "core": None, "extra": None,
             "excerpts": [], "test_text": "", "clippy": None, "clippy_samples": [], "unsafe": None,
             "interface_missing": self.interface_missing()}
        r["build_ok"], r["build_text"], r["build_errors"] = self.build()
        if r["build_ok"]:
            rc, out, core, extra, excerpts = self.test()
            r.update(test_text=out, core=core, extra=extra, excerpts=excerpts)
        # Interface conformance is part of the required benchmark contract. Do
        # not advance to Phase B (or report success) while a required public
        # signature has disappeared or changed, even if visible tests pass.
        r["core_ok"] = bool(
            r["build_ok"] and r["core"] and r["core"]["failed"] == 0
            and r["core"]["total"] > 0 and not r["interface_missing"]
        )
        r["extra_ok"] = bool(r["extra"] is None or r["extra"]["failed"] == 0)
        if full and r["build_ok"]:
            r["clippy"], r["clippy_samples"] = self.clippy()
            r["unsafe"] = self.unsafe_metrics()
        sig_src = r["build_errors"] if not r["build_ok"] else (r["core"]["failed_names"] if r["core"] else [])
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
