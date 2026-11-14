"""Run the supplied newmetrics analyzer on the implementation library only."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PRIMARY = ("unsafe_lines", "unsafe_calls", "unsafe_casts", "pointer_arithmetic")
LABELS = {
    "pointer_arithmetic": "Pointer arithmetic", "unsafe_lines": "Unsafe lines",
    "unsafe_calls": "Unsafe calls", "unsafe_casts": "Unsafe casts",
    "total_spans": "Total spans", "raw_pointer_dereferences": "Raw pointer dereferences",
    "raw_pointer_declarations": "Raw pointer declarations",
}


def analyze(crate, cfg, label="evaluation", skip_reason=None):
    import re
    crate = Path(crate).resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    safe_label = re.sub(r"[^A-Za-z0-9_-]", "_", label)
    destination = Path(cfg.get("safety_output_dir", crate / "safety")).resolve() / f"{safe_label}_{stamp}"
    destination.mkdir(parents=True, exist_ok=False)
    sources = {}
    for path in sorted((crate / "src").rglob("*.rs")):
        # Preserve hashes of every source; --lib determines the actual compilation scope.
        sources[path.relative_to(crate).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ("Cargo.toml", "Cargo.lock"):
        if (crate / name).is_file():
            sources[name] = hashlib.sha256((crate / name).read_bytes()).hexdigest()
    result = {"source": "newmetrics", "status": "pending", "scope": "implementation-library",
              "artifacts": str(destination), "source_hashes": sources}
    metadata = {"started_at": stamp, "crate": str(crate), "label": label,
                "toolchain": cfg["toolchain"], "scope": result["scope"], "source_hashes": sources}
    raw = ""
    try:
        if skip_reason:
            result.update(status="skipped", reason=skip_reason)
            return result
        env = dict(os.environ)
        env["PATH"] = os.pathsep.join([str(Path.home() / ".cargo" / "bin"), env.get("PATH", "")])
        rustup = shutil.which("rustup", path=env["PATH"])
        if not rustup:
            raise RuntimeError("rustup not found")
        def probe(args):
            p = subprocess.run([rustup, "run", cfg["toolchain"], *args], env=env,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            if p.returncode:
                raise RuntimeError(p.stderr.strip() or p.stdout.strip())
            return p.stdout.strip()
        sysroot = Path(probe(["rustc", "--print", "sysroot"]))
        # Native PATH separators also work from PowerShell; no Git Bash cygpath dependency.
        env["PATH"] = str(sysroot / "bin") + os.pathsep + env["PATH"]
        wrapper = shutil.which("cargo-newmetrics", path=env["PATH"])
        driver = shutil.which("newmetrics", path=env["PATH"])
        if not wrapper or not driver:
            raise RuntimeError("Install newmetrics with the pinned toolchain; both binaries are required")
        p = subprocess.run([driver, "--print", "sysroot"], env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=30)
        if p.returncode or Path(p.stdout.strip()).resolve() != sysroot.resolve():
            raise RuntimeError("newmetrics sysroot mismatch or missing DLL: " + p.stderr.strip())
        target = cfg.get("cargo_target")
        if not target:
            target = next(line.split(":", 1)[1].strip() for line in probe(["rustc", "-vV"]).splitlines()
                          if line.startswith("host:"))
        metadata.update(target=target, wrapper=wrapper, driver=driver)
        timeout = int(cfg.get("unsafe_metrics_timeout_seconds", 600))
        # A new target directory forces actual analysis instead of Cargo's cached success.
        # Running the wrapper directly avoids cargo-newmetrics' enumeration of test binaries.
        with tempfile.TemporaryDirectory(prefix="mp4-newmetrics-") as temp:
            analysis_crate = Path(temp) / "crate"
            analysis_crate.mkdir()
            shutil.copytree(crate / "src", analysis_crate / "src")
            for name in ("Cargo.toml", "Cargo.lock"):
                if (crate / name).is_file():
                    shutil.copy2(crate / name, analysis_crate / name)
            env["CARGO_TARGET_DIR"] = str(Path(temp) / "target")
            env["RUSTC_WRAPPER"] = wrapper
            env.pop("RUSTC_WORKSPACE_WRAPPER", None)
            env["METRICS_ARGS"] = "[]"
            command = [rustup, "run", cfg["toolchain"], "cargo", "check", "--lib", "--target", target]
            if (analysis_crate / "Cargo.lock").exists():
                command.append("--locked")
            metadata.update(command=command, environment_overrides={
                key: env[key] for key in ("CARGO_TARGET_DIR", "RUSTC_WRAPPER", "METRICS_ARGS")})
            p = subprocess.run(command, cwd=analysis_crate, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                               timeout=timeout)
            raw = p.stdout
            metadata["exit_code"] = p.returncode
            for name in ("unsafe_spans.txt", "decls.txt", "derefs.txt"):
                if (analysis_crate / name).is_file():
                    shutil.copy2(analysis_crate / name, destination / name)
            if p.returncode:
                raise RuntimeError(f"newmetrics analysis exited {p.returncode}; see newmetrics.log")
            metrics = {}
            for key, text in LABELS.items():
                values = re.findall(rf"^\s*{re.escape(text)}:\s*(\d+)\s*$", raw, re.MULTILINE)
                if len(values) != 1:
                    raise RuntimeError(f"Expected one library result for {key}; found {len(values)}")
                metrics[key] = int(values[0])
            if metrics["total_spans"] <= 0:
                raise RuntimeError("newmetrics returned no analyzed source")
            metrics["unsafe_ratio"] = metrics["unsafe_lines"] / metrics["total_spans"]
            result.update(metrics, status="ok")
            result["diagnostics"] = {name: f"safety/{destination.name}/{name}" for name in
                                     ("newmetrics.log", "unsafe_spans.txt", "decls.txt", "derefs.txt")}
        return result
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or b""
        raw = partial.decode("utf-8", errors="replace") if isinstance(partial, bytes) else partial
        result.update(status="failed", error="newmetrics timed out")
        return result
    except (OSError, RuntimeError, ValueError, StopIteration) as exc:
        result.update(status="failed", error=str(exc))
        return result
    finally:
        metadata.update(status=result["status"], finished_at=datetime.now(timezone.utc).isoformat())
        if "error" in result:
            metadata["error"] = result["error"]
        if "reason" in result:
            metadata["reason"] = result["reason"]
        (destination / "newmetrics.log").write_text(raw, encoding="utf-8")
        (destination / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        (destination / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--crate", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--toolchain", default="nightly-2025-05-13")
    parser.add_argument("--target")
    args = parser.parse_args()
    report = analyze(args.crate, {"toolchain": args.toolchain, "cargo_target": args.target,
                                 "safety_output_dir": args.output}, "manual")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["status"] == "ok" else 1)
