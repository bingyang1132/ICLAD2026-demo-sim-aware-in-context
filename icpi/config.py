import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).parent.parent
LLM_API_DIR = ROOT / "llm_api"
KEY_FILE = LLM_API_DIR / "key.txt"
BENCHMARK_DIR = ROOT / "icpi" / "benchmark"
RUNS_DIR = ROOT / "runs"


# ── Providers ─────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Provider:
    """An LLM backend. base_url is empty for Gemini (uses the google.genai SDK)."""
    name: str
    base_url: str
    key_file: Path
    env_var: str

    def read_key(self) -> str:
        """API key from the env var (preferred) or the provider's key file."""
        env = os.environ.get(self.env_var)
        if env:
            return env.strip()
        if self.key_file.exists():
            return self.key_file.read_text().strip()
        raise RuntimeError(
            f"No API key for provider '{self.name}': set ${self.env_var} "
            f"or create {self.key_file}"
        )


PROVIDERS: dict[str, Provider] = {
    "gemini": Provider("gemini", "", KEY_FILE, "GEMINI_API_KEY"),
    "deepseek": Provider(
        "deepseek", "https://api.deepseek.com/v1",
        LLM_API_DIR / "deepseek_key.txt", "DEEPSEEK_API_KEY",
    ),
    "openrouter": Provider(
        "openrouter", "https://openrouter.ai/api/v1",
        LLM_API_DIR / "openrouter_key.txt", "OPENROUTER_API_KEY",
    ),
}


def provider_for(model_id: str) -> Provider:
    """Infer the provider from a resolved model id string.

    - contains "/"          → OpenRouter (uses "vendor/model" ids, e.g. deepseek/deepseek-chat)
    - starts with "deepseek" → DeepSeek direct (deepseek-chat, deepseek-reasoner)
    - otherwise              → Gemini (default, backward compatible)
    """
    if "/" in model_id:
        return PROVIDERS["openrouter"]
    if model_id.startswith("deepseek"):
        return PROVIDERS["deepseek"]
    return PROVIDERS["gemini"]


# ── Model presets ─────────────────────────────────────────────────────────────
# Alias (left) → full model id (right). The provider is inferred from the id.
MODELS: dict[str, str] = {
    # Gemini (Google)
    "flash":          "gemini-2.5-flash",
    "flash-lite":     "gemini-2.5-flash-lite",
    "pro":            "gemini-2.5-pro",
    "2.0-flash":      "gemini-2.0-flash",
    "2.0-flash-lite": "gemini-2.0-flash-lite",
    # DeepSeek (direct API)
    "deepseek":       "deepseek-chat",
    "deepseek-r1":    "deepseek-reasoner",
    # OpenRouter gateway (open-source models via one endpoint).
    # OpenRouter's catalog drifts — verify current ids at openrouter.ai/models;
    # any full id works via `--model vendor/model` without needing an alias here.
    "or-deepseek":    "deepseek/deepseek-v4-flash",
    "or-qwen":        "qwen/qwen3.7-max",
    "or-llama":       "meta-llama/llama-3.3-70b-instruct",
}
DEFAULT_MODEL_ALIAS = "flash"


def resolve_model(name: str) -> str:
    """Return the full model ID for an alias, or pass through a full ID."""
    return MODELS.get(name, name)


# ── Loop defaults ─────────────────────────────────────────────────────────────
DEFAULT_ROUNDS = 6
DEFAULT_SIM_EVERY = 2

# ── LLM client behavior ───────────────────────────────────────────────────────
MAX_LLM_RETRIES = 3
LLM_RETRY_DELAY = 2.0   # seconds, doubled each retry

# ── Oracle thresholds ─────────────────────────────────────────────────────────
LEGALIZATION_RETRY_THRESHOLD = 0.7   # if legalization_risk > this, executor retries
