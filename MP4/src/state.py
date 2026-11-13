import json
import re
import shutil
from pathlib import Path


class State:
    @staticmethod
    def _compatible_signature(signature):
        return isinstance(signature, str) and re.fullmatch(r"v2:[0-9a-f]{20}", signature) is not None

    def __init__(self, crate, traj_dir, resume=False):
        self.crate = Path(crate)
        self.dir = Path(traj_dir)
        self.snap_dir = self.dir / "snapshots"
        self.history = []
        history_file = self.dir / "iterations.json"
        if resume and history_file.is_file():
            # Cleared logs can leave an empty file rather than deleting it.
            history_text = history_file.read_text(encoding="utf-8-sig").strip()
            self.history = json.loads(history_text) if history_text else []
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
        try:
            for line in trajectory.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = event.get("kind")
                if kind == "review_state_restored" and event.get("evidence_complete") is True:
                    # Support review state carried in older per-run logs as well
                    # as reviews recorded in the appended trajectory.
                    for key, signatures in (
                            ("reader_reviewed_signatures", self.reader_reviewed_signatures),
                            ("failure_analysis_signatures", self.failure_analysis_signatures)):
                        restored = event.get(key, [])
                        if isinstance(restored, list):
                            signatures.update(value for value in restored if self._compatible_signature(value))
                    continue
                signature = event.get("failure_sig")
                # Old name-only identities and a started/escalated review do not prove
                # that the current assertion received a completed, evidence-based review.
                if not self._compatible_signature(signature) or event.get("evidence_complete") is not True:
                    continue
                if kind == "reader_reviewed":
                    self.reader_reviewed_signatures.add(signature)
                elif kind == "failure_analysis_reviewed":
                    self.failure_analysis_signatures.add(signature)
        except OSError:
            return

    def reader_was_reviewed(self, signature):
        return self._compatible_signature(signature) and signature in self.reader_reviewed_signatures

    def mark_reader_reviewed(self, signature):
        if self._compatible_signature(signature):
            self.reader_reviewed_signatures.add(signature)

    def failure_was_analyzed(self, signature):
        return self._compatible_signature(signature) and signature in self.failure_analysis_signatures

    def mark_failure_analyzed(self, signature):
        if self._compatible_signature(signature):
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
            "sig": report.get("sig", ""),
            "failure_fingerprint_version": report.get("failure_fingerprint_version"),
            "failure_details": report.get("failure_details", []),
            "interface_missing": report.get("interface_missing", []),
        }
        self.history.append(entry)
        self.sigs.append(report["sig"])
        (self.dir / "iterations.json").write_text(json.dumps(self.history, indent=2, default=str))

    def stalled(self, n):
        tail = self.sigs[-n:]
        return len(tail) == n and tail[0] != "" and len(set(tail)) == 1

    def reset_stall(self):
        self.sigs.clear()
