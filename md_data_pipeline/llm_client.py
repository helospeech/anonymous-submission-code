from __future__ import annotations

import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class LLMConfig:
    name: str
    api_url: str
    api_key: str
    qps: int = 25
    temperature: float = 1.0
    max_tokens: int = 32768
    stream: bool = False
    top_p: float = 0.001
    timeout: int = 3000
    max_retries: int = 3
    retry_backoff_base: float = 0.8


class LLMClient:
    def __init__(self, config: LLMConfig):
        self.config = config

    @classmethod
    def from_env(cls) -> "LLMClient":
        api_key = os.getenv("SIM_MODEL_API_KEY", "") or os.getenv("OPENROUTER_API_KEY", "")
        return cls(
            LLMConfig(
                name=os.getenv("SIM_MODEL_NAME", "Gemini 3-Pro-Preview"),
                api_url=os.getenv("SIM_MODEL_API_URL", "https://openrouter.ai/api/v1/chat/completions"),
                api_key=api_key,
                qps=int(os.getenv("SIM_MODEL_QPS", "5")),
                temperature=float(os.getenv("SIM_MODEL_TEMPERATURE", "1.0")),
                max_tokens=int(os.getenv("SIM_MODEL_MAX_TOKENS", "16384")),
                stream=os.getenv("SIM_MODEL_STREAM", "false").lower() == "true",
                top_p=float(os.getenv("SIM_MODEL_TOP_P", "0.001")),
                timeout=int(os.getenv("SIM_MODEL_TIMEOUT", "3000")),
                max_retries=int(os.getenv("SIM_MODEL_MAX_RETRIES", "3")),
                retry_backoff_base=float(os.getenv("SIM_MODEL_RETRY_BACKOFF", "0.8")),
            )
        )

    @property
    def enabled(self) -> bool:
        return bool(self.config.api_key.strip())

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        if not self.enabled:
            raise RuntimeError("SIM_MODEL_API_KEY 未设置，无法调用模型")

        def _build_payload(target_model: str) -> dict[str, Any]:
            target_model_l = target_model.lower()
            if target_model_l in {"gemini 3-pro-preview", "gemini-3-flash-preview"}:
                payload_local: dict[str, Any] = {
                    "model": target_model,
                    "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                    "generation_config": {
                        "response_modalities": ["TEXT"],
                        "thinkingConfig": {"thinkingLevel": "HIGH"},
                    },
                    "safety_settings": {
                        "method": "PROBABILITY",
                        "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                        "threshold": "BLOCK_NONE",
                    },
                    "stream": False,
                }
                if system_prompt:
                    payload_local["system_instruction"] = {"parts": [{"text": system_prompt}]}
                return payload_local
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_prompt})
            payload_local = {
                "messages": messages,
                "model": target_model,
                "stream": self.config.stream,
                "temperature": self.config.temperature,
            }
            if target_model_l.startswith("gpt-5"):
                payload_local["max_completion_tokens"] = self.config.max_tokens
            else:
                payload_local["top_p"] = self.config.top_p
                payload_local["max_tokens"] = self.config.max_tokens
            return payload_local

        model_name = self.config.name
        model_name_l = model_name.lower()
        used_model = model_name
        payload = _build_payload(used_model)

        raw = ""
        last_error: Exception | None = None
        switched_to_fallback = False
        for attempt in range(self.config.max_retries):
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.config.api_url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.config.api_key}",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                    raw = resp.read().decode("utf-8")
                break
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
                if e.code == 400:
                    unsupported_param = ""
                    m = re.search(r'"param"\s*:\s*"([^"]+)"', body)
                    if m:
                        unsupported_param = m.group(1)
                    if unsupported_param == "max_tokens" and "max_tokens" in payload:
                        payload["max_completion_tokens"] = payload.pop("max_tokens")
                        continue
                    if unsupported_param and unsupported_param in payload:
                        payload.pop(unsupported_param, None)
                        continue
                    if not switched_to_fallback and used_model.lower() != "gpt-5":
                        switched_to_fallback = True
                        used_model = "gpt-5"
                        payload = _build_payload(used_model)
                        continue
                retriable = e.code in {408, 409, 425, 429, 500, 502, 503, 504}
                last_error = RuntimeError(f"HTTP {e.code}: {body[:500]}")
                if not retriable or attempt == self.config.max_retries - 1:
                    raise last_error
                backoff = (self.config.retry_backoff_base ** attempt) + random.uniform(0, 0.5)
                time.sleep(backoff)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_error = e
                if attempt == self.config.max_retries - 1:
                    raise RuntimeError(f"请求失败: {e}") from e
                backoff = (self.config.retry_backoff_base ** attempt) + random.uniform(0, 0.5)
                time.sleep(backoff)

        if not raw:
            raise RuntimeError(f"模型调用失败: {last_error}")

        parsed = json.loads(raw)
        used_model_l = used_model.lower()
        if used_model_l in {"gemini 3-pro-preview", "gemini-3-flash-preview"}:
            candidates = parsed.get("candidates", [])
            if isinstance(candidates, dict):
                candidates = [candidates]
            if not candidates:
                raise ValueError(f"响应结构异常: {parsed}")
            parts = candidates[0].get("content", {}).get("parts", [])
            content = parts[0].get("text", "") if parts else ""
        else:
            choices = parsed.get("choices", [])
            if not choices:
                raise ValueError(f"响应结构异常: {parsed}")
            content = choices[0]["message"]["content"]

        content = content.strip()
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.MULTILINE).strip()
        return content
