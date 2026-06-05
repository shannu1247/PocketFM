"""
LLM backend clients. All expose a unified .chat(messages) -> str interface.
"""

import json
import time
import urllib.request
import urllib.error
from typing import List, Dict, Any


class BaseLLMClient:
    def chat(self, messages: List[Dict[str, str]], system: str = "") -> str:
        raise NotImplementedError

    def _retry(self, fn, retries=3, delay=5):
        for i in range(retries):
            try:
                return fn()
            except Exception as e:
                if i == retries - 1:
                    raise
                print(f"   ⚠️  LLM error ({e}), retrying in {delay}s...")
                time.sleep(delay)


# ---------------------------------------------------------------------------
# Gemini (Google AI Studio — free tier)
# ---------------------------------------------------------------------------
class GeminiClient(BaseLLMClient):
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str, model: str = "gemini-2.5-pro"):
        self.api_key = api_key
        self.model = model

    def chat(self, messages: List[Dict[str, str]], system: str = "") -> str:
        # Convert OpenAI-style messages to Gemini format
        contents = []
        if system:
            contents.append({
                "role": "user",
                "parts": [{"text": f"[SYSTEM]\n{system}\n[/SYSTEM]\n\nAcknowledge and proceed."}]
            })
            contents.append({
                "role": "model",
                "parts": [{"text": "Understood. I will follow these instructions."}]
            })

        for msg in messages:
            role = "model" if msg["role"] == "assistant" else "user"
            contents.append({
                "role": role,
                "parts": [{"text": msg["content"]}]
            })

        payload = json.dumps({
            "contents": contents,
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 8192,
            }
        }).encode()

        url = f"{self.BASE_URL}/{self.model}:generateContent?key={self.api_key}"

        def _call():
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode())
            candidates = data.get("candidates", [])
            if not candidates:
                raise ValueError(f"Empty response from Gemini: {data}")
            return candidates[0]["content"]["parts"][0]["text"]

        return self._retry(_call)


# ---------------------------------------------------------------------------
# Groq (free tier — very fast inference)
# ---------------------------------------------------------------------------
class GroqClient(BaseLLMClient):
    BASE_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile"):
        self.api_key = api_key
        self.model = model

    def chat(self, messages: List[Dict[str, str]], system: str = "") -> str:
        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        payload = json.dumps({
            "model": self.model,
            "messages": all_messages,
            "temperature": 0.2,
            "max_tokens": 8192,
        }).encode()

        def _call():
            req = urllib.request.Request(
                self.BASE_URL,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode())
            return data["choices"][0]["message"]["content"]

        return self._retry(_call)


# ---------------------------------------------------------------------------
# Ollama (fully local — no API key needed)
# ---------------------------------------------------------------------------
class OllamaClient(BaseLLMClient):
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qwen2.5-coder:32b"):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def chat(self, messages: List[Dict[str, str]], system: str = "") -> str:
        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        payload = json.dumps({
            "model": self.model,
            "messages": all_messages,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 8192},
        }).encode()

        def _call():
            req = urllib.request.Request(
                f"{self.base_url}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read().decode())
            return data["message"]["content"]

        return self._retry(_call)
