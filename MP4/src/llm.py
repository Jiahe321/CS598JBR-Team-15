import json
import os
import time
import urllib.error
import urllib.request


class LLMError(Exception):
    pass


class LLM:
    def __init__(self, cfg, logger=None):
        self.cfg = cfg
        self.logger = logger
        self.key = os.environ.get(cfg["api_key_env"], "")
        self.usage = {"prompt": 0, "completion": 0, "calls": 0}

    @property
    def total_tokens(self):
        return self.usage["prompt"] + self.usage["completion"]

    def chat(self, messages, max_tokens=None, temperature=None):
        if not self.key:
            raise LLMError(f"{self.cfg['api_key_env']} is not set in the environment")
        models = [self.cfg["model"]]
        if self.cfg.get("fallback_model"):
            models.append(self.cfg["fallback_model"])
        last = None
        for model in models:
            try:
                return self._call(model, messages, max_tokens, temperature)
            except LLMError as e:
                last = e
                if self.logger:
                    self.logger.log("llm_error", model=model, error=str(e))
        raise last

    def _call(self, model, messages, max_tokens, temperature):
        cfg = self.cfg
        body = {
            "model": model,
            "messages": messages,
            "temperature": cfg["temperature"] if temperature is None else temperature,
            "top_p": cfg.get("top_p", 1.0),
            "max_tokens": max_tokens or cfg["max_tokens"],
        }
        data = json.dumps(body).encode()
        headers = {
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "X-Title": "CS598 MP4 C-to-Rust agent",
        }
        err = "unknown"
        for attempt in range(cfg["max_retries"]):
            req = urllib.request.Request(cfg["base_url"].rstrip("/") + "/chat/completions",
                                         data=data, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=cfg["timeout_seconds"]) as r:
                    out = json.load(r)
            except urllib.error.HTTPError as e:
                err = f"HTTP {e.code}: {e.read()[:300]!r}"
                if e.code in (408, 429, 500, 502, 503, 504):
                    self._sleep(attempt)
                    continue
                raise LLMError(err)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                err = f"network: {e}"
                self._sleep(attempt)
                continue
            if "error" in out:
                err = f"provider error: {str(out['error'])[:300]}"
                self._sleep(attempt)
                continue
            try:
                text = out["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError):
                err = f"malformed response: {str(out)[:300]}"
                self._sleep(attempt)
                continue
            u = out.get("usage") or {}
            self.usage["prompt"] += u.get("prompt_tokens", 0)
            self.usage["completion"] += u.get("completion_tokens", 0)
            self.usage["calls"] += 1
            return text
        raise LLMError(f"{model}: giving up after {cfg['max_retries']} attempts ({err})")

    def _sleep(self, attempt):
        time.sleep(self.cfg["backoff_base_seconds"] * (2 ** attempt))
