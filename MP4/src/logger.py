import json
import os
import re
import time
from pathlib import Path

SECRET_PATTERNS = [
    re.compile(r"sk-or-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{20,}"),
]


def redact(text, extra_secrets=()):
    for s in extra_secrets:
        if s:
            text = text.replace(s, "[REDACTED]")
    for p in SECRET_PATTERNS:
        text = p.sub("[REDACTED]", text)
    return text


class Logger:
    def __init__(self, traj_dir, secret_env_vars=("OPENROUTER_API_KEY",)):
        self.dir = Path(traj_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "trajectory.jsonl"
        self.secrets = [os.environ.get(v, "") for v in secret_env_vars]
        self.t0 = time.time()

    def log(self, kind, **data):
        rec = {"t": round(time.time() - self.t0, 1), "kind": kind, **data}
        line = redact(json.dumps(rec, ensure_ascii=False, default=str), self.secrets)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def write_json(self, name, obj):
        text = redact(json.dumps(obj, indent=2, ensure_ascii=False, default=str), self.secrets)
        (self.dir / name).write_text(text, encoding="utf-8")
