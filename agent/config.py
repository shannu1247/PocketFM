"""
Configuration and environment management.
"""

import os
from dataclasses import dataclass, field
from typing import Optional, List, Tuple


# Default models per backend
DEFAULT_MODELS = {
    "gemini": "gemini-2.5-pro",
    "groq":   "llama-3.3-70b-versatile",
    "ollama": "qwen2.5-coder:32b",
}

# Required env vars per backend
REQUIRED_ENV = {
    "gemini": [
        ("GEMINI_API_KEY", "Get free key at https://aistudio.google.com/app/apikey"),
    ],
    "groq": [
        ("GROQ_API_KEY", "Get free key at https://console.groq.com"),
    ],
    "ollama": [],  # Local, no key needed
}


@dataclass
class Config:
    llm_backend: str = "gemini"
    model_override: Optional[str] = None
    workspace_dir: str = "./workspace"
    output_dir: str = "./output"
    dry_run: bool = False
    verbose: bool = False

    # Derived
    model: str = field(init=False)
    gemini_api_key: str = field(init=False, default="")
    groq_api_key: str = field(init=False, default="")
    ollama_base_url: str = field(init=False, default="")
    github_token: str = field(init=False, default="")

    def __post_init__(self):
        self.model = self.model_override or DEFAULT_MODELS.get(self.llm_backend, "")
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
        self.groq_api_key = os.environ.get("GROQ_API_KEY", "")
        self.ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        self.github_token = os.environ.get("GITHUB_TOKEN", "")

    def validate(self) -> List[Tuple[str, str]]:
        """Returns list of (var_name, hint) for any missing required env vars."""
        missing = []
        for var, hint in REQUIRED_ENV.get(self.llm_backend, []):
            if not os.environ.get(var):
                missing.append((var, hint))
        return missing

    def get_llm_client(self):
        """Returns initialized LLM client based on backend."""
        if self.llm_backend == "gemini":
            from agent.llm_backends import GeminiClient
            return GeminiClient(api_key=self.gemini_api_key, model=self.model)
        elif self.llm_backend == "groq":
            from agent.llm_backends import GroqClient
            return GroqClient(api_key=self.groq_api_key, model=self.model)
        elif self.llm_backend == "ollama":
            from agent.llm_backends import OllamaClient
            return OllamaClient(base_url=self.ollama_base_url, model=self.model)
        else:
            raise ValueError(f"Unknown LLM backend: {self.llm_backend}")
