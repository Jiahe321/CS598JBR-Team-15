import json
import os
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime


class LLMError(Exception):
    pass


class TokenBudgetReached(LLMError):
    pass


class RequestBudgetReached(LLMError):
    pass


class LLM:
    def __init__(self, cfg, logger=None):
        self.cfg = cfg
        self.logger = logger
        self.key = os.environ.get(cfg["api_key_env"], "")
        self.usage = {"prompt": 0, "completion": 0, "calls": 0, "requests": 0}

    @property
    def total_tokens(self):
        return self.usage["prompt"] + self.usage["completion"]

    def chat(self, messages, max_tokens=None, temperature=None):
        budget = self.cfg.get("max_total_tokens")
        if budget is not None and self.total_tokens >= budget:
            raise TokenBudgetReached(f"token budget reached ({self.total_tokens}/{budget})")
        if not self.key:
            raise LLMError(f"{self.cfg['api_key_env']} is not set in the environment")
        models = [self.cfg["model"]]
        if self.cfg.get("fallback_model"):
            models.append(self.cfg["fallback_model"])
        last = None
        for model in models:
            try:
                return self._call(model, messages, max_tokens, temperature)
            except RequestBudgetReached:
                raise
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
        thinking = cfg.get("thinking")
        if thinking:
            body["thinking"] = dict(thinking)
        elif cfg.get("reasoning"):
            # Compatibility for providers that use an OpenRouter-style reasoning field.
            body["reasoning"] = dict(cfg["reasoning"])
            if max_tokens and "max_tokens" in body["reasoning"]:
                body["reasoning"]["max_tokens"] = min(
                    body["reasoning"]["max_tokens"], max(1, max_tokens // 2))
        data = json.dumps(body).encode()
        headers = {
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "X-Title": "CS598 MP4 C-to-Rust agent",
        }
        err = "unknown"
        retries = max(1, int(cfg.get("max_retries", 1)))
        request_budget = cfg.get("max_llm_requests_per_run")
        for attempt in range(retries):
            if request_budget is not None and self.usage["requests"] >= int(request_budget):
                raise RequestBudgetReached(
                    f"model request budget reached ({self.usage['requests']}/{request_budget})")
            self.usage["requests"] += 1
            if self.logger:
                self.logger.log("llm_request", model=model, request=self.usage["requests"], attempt=attempt + 1)
            req = urllib.request.Request(cfg["base_url"].rstrip("/") + "/chat/completions",
                                         data=data, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=cfg["timeout_seconds"]) as r:
                    out = json.load(r)
            except urllib.error.HTTPError as e:
                body = e.read()
                err = f"HTTP {e.code}: {body[:300]!r}"
                if e.code == 429 and self._is_daily_quota_error(body):
                    raise LLMError(f"provider daily request quota exhausted; stopped without retry ({err})")
                if e.code in (408, 429, 500, 502, 503, 504) and attempt + 1 < retries:
                    delay = self._retry_delay(attempt, e.headers)
                    max_wait = float(cfg.get("max_retry_wait_seconds", 20))
                    if delay > max_wait:
                        raise LLMError(f"HTTP {e.code} retry delay {delay:g}s exceeds configured limit {max_wait:g}s")
                    time.sleep(delay)
                    continue
                if e.code not in (408, 429, 500, 502, 503, 504):
                    raise LLMError(err)
                break
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                err = f"network: {e}"
                if attempt + 1 < retries:
                    delay = self._retry_delay(attempt)
                    max_wait = float(cfg.get("max_retry_wait_seconds", 20))
                    if delay > max_wait:
                        raise LLMError(f"network retry delay {delay:g}s exceeds configured limit {max_wait:g}s")
                    time.sleep(delay)
                    continue
                break
            if "error" in out:
                err = f"provider error: {str(out['error'])[:300]}"
                if self._is_daily_quota_error(json.dumps(out)):
                    raise LLMError(f"provider daily request quota exhausted; stopped without retry ({err})")
                if attempt + 1 < retries:
                    delay = self._retry_delay(attempt)
                    max_wait = float(cfg.get("max_retry_wait_seconds", 20))
                    if delay > max_wait:
                        raise LLMError(f"provider retry delay {delay:g}s exceeds configured limit {max_wait:g}s")
                    time.sleep(delay)
                    continue
                break
            try:
                choice = out["choices"][0]
                message = choice["message"]
                text = message.get("content") or ""
            except (KeyError, IndexError):
                err = f"malformed response: {str(out)[:300]}"
                if attempt + 1 < retries:
                    time.sleep(self._retry_delay(attempt))
                    continue
                break
            u = out.get("usage") or {}
            self.usage["prompt"] += u.get("prompt_tokens", 0)
            self.usage["completion"] += u.get("completion_tokens", 0)
            self.usage["calls"] += 1
            if self.logger:
                self.logger.log(
                    "llm_response", model=model,
                    finish_reason=choice.get("finish_reason"),
                    content_chars=len(text), usage=u,
                )
            if not text.strip():
                err = (f"empty visible content (finish_reason={choice.get('finish_reason')}, "
                       f"completion_tokens={u.get('completion_tokens', 0)})")
                if attempt + 1 < retries:
                    time.sleep(self._retry_delay(attempt))
                    continue
                break
            return text
        raise LLMError(f"{model}: giving up after {retries} attempts ({err})")

    @staticmethod
    def _is_daily_quota_error(body):
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        text = str(body).lower()
        return any(marker in text for marker in (
            "free-models-per-day", "free model requests per day", "daily request quota", "daily limit"
        ))

    def _retry_delay(self, attempt, headers=None):
        if headers:
            retry_after = headers.get("Retry-After")
            if retry_after:
                try:
                    return max(0.0, float(retry_after))
                except ValueError:
                    try:
                        return max(0.0, parsedate_to_datetime(retry_after).timestamp() - time.time())
                    except (TypeError, ValueError, OverflowError):
                        pass
        return float(self.cfg.get("backoff_base_seconds", 1)) * (2 ** attempt)
