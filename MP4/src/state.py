import json
import shutil
from pathlib import Path


class State:
    def __init__(self, crate, traj_dir):
        self.crate = Path(crate)
        self.dir = Path(traj_dir)
        self.snap_dir = self.dir / "snapshots"
        self.history = []
        self.sigs = []
        self.decisions = []

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
            "iteration": it, "phase": phase, "build_ok": report["build_ok"],
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
