"""
BaseAgent: shared logic for prompt rendering + LLM call + output validation.
Wraps each call in TRACKER.agent_context for per-agent usage accounting.
"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Any

from icpi.usage import TRACKER

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


class BaseAgent:
    prompt_file: str = ""
    output_schema: dict | None = None
    agent_name: str = "base"

    def __init__(self, model: str = "gemini-2.5-flash"):
        self.model = model
        self._system_prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        return (PROMPTS_DIR / self.prompt_file).read_text()

    def _call(self, user_prompt: str) -> Any:
        from llm_api.router import chat
        with TRACKER.agent_context(self.agent_name):
            return chat(
                system_prompt=self._system_prompt,
                user_prompt=user_prompt,
                output_schema=self.output_schema,
                model=self.model,
            )
