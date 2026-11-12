import hashlib
import json
import shutil
from pathlib import Path


class State:
    def __init__(self, crate, traj_dir, resume=False):
        self.crate = Path(crate)
        self.dir = Path(traj_dir)
        self.snap_dir = self.dir / "snapshots"
        self.history = []
        history_file = self.dir / "iterations.json"
        if resume and history_file.is_file():
            self.history = json.loads(history_file.read_text(encoding="utf-8"))
            if not isinstance(self.history, list):
                raise ValueError(f"Expected an iteration list in {history_file}")
        self.iteration_offset = len(self.history)
        self.sigs = []
        self.decisions = []
        self.reader_reviewed_signatures = set()
        self.failure_analysis_signatures = set()
        self._load_reader_reviews()

    def _load_reader_reviews(self):
        trajectory = self.dir / "trajectory.jsonl"
        if not trajectory.is_file():
            return
        last_failure_signature = ""
        pending_analysis_signature = ""
        try:
            for line in trajectory.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = event.get("kind")
                if kind == "iteration":
                    failed = (event.get("core") or {}).get("failed_names") or []
                    last_failure_signature = (
                        hashlib.md5("\n".join(failed).encode()).hexdigest()[:10] if failed else ""
                    )
                if kind == "reader_escalation" and event.get("failure_sig"):
                    self.reader_reviewed_signatures.add(event["failure_sig"])
                if kind == "failure_analysis_reviewed" and event.get("failure_sig"):
                    self.failure_analysis_signatures.add(event["failure_sig"])
                task = str(event.get("task", "")).lower()
                if kind == "agent_start" and event.get("agent") == "reader" and last_failure_signature and (
                    "writer is stuck" in task or "re-read the c" in task or "re-read the relevant c" in task
                ):
                    self.reader_reviewed_signatures.add(last_failure_signature)
                if kind == "agent_start" and event.get("agent") == "tester" and task.startswith("analyze:"):
                    pending_analysis_signature = last_failure_signature
                if kind == "agent_end" and event.get("agent") == "tester":
                    if pending_analysis_signature:
                        self.failure_analysis_signatures.add(pending_analysis_signature)
                    pending_analysis_signature = ""
        except OSError:
            return

    def reader_was_reviewed(self, signature):
        return bool(signature) and signature in self.reader_reviewed_signatures

    def mark_reader_reviewed(self, signature):
        if signature:
            self.reader_reviewed_signatures.add(signature)

    def failure_was_analyzed(self, signature):
        return bool(signature) and signature in self.failure_analysis_signatures

    def mark_failure_analyzed(self, signature):
        if signature:
            self.failure_analysis_signatures.add(signature)

    def snapshot(self, label):
        dst = self.snap_dir / label
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(self.crate / "src", dst)

    def restore(self, label):
        src = self.snap_dir / label
        if not src.exists():
            return False
        shutil.rmtree(self.crate / "src")
        shutil.copytree(src, self.crate / "src")
        return True

    def record(self, it, phase, report):
        entry = {
            "iteration": self.iteration_offset + it, "phase": phase, "build_ok": report["build_ok"],
            "core": report["core"], "extra": report["extra"],
            "clippy": report["clippy"], "unsafe": report["unsafe"], "score": report["score"],
        }
        self.history.append(entry)
        self.sigs.append(report["sig"])
        (self.dir / "iterations.json").write_text(json.dumps(self.history, indent=2, default=str))

    def stalled(self, n):
        tail = self.sigs[-n:]
        return len(tail) == n and tail[0] != "" and len(set(tail)) == 1

    def reset_stall(self):
        self.sigs.clear()
