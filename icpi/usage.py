"""
Per-run usage tracker — counts LLM calls, tokens, and wall-clock time.

Singleton design: a single UsageTracker is created at run start and updated
by gemini_client on each call. Reset between runs via .reset() if reused
within a single process.
"""
from __future__ import annotations
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict


@dataclass
class CallRecord:
    agent: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    duration_s: float
    success: bool = True


@dataclass
class UsageTracker:
    calls: list[CallRecord] = field(default_factory=list)
    wall_clock_start: float | None = None
    wall_clock_end: float | None = None
    per_round_seconds: dict[int, float] = field(default_factory=dict)
    current_agent: str = "unknown"

    # ── total accounting ──────────────────────────────────────────────────────
    @property
    def total_calls(self) -> int:
        return len(self.calls)

    @property
    def total_prompt_tokens(self) -> int:
        return sum(c.prompt_tokens for c in self.calls)

    @property
    def total_completion_tokens(self) -> int:
        return sum(c.completion_tokens for c in self.calls)

    @property
    def total_tokens(self) -> int:
        return self.total_prompt_tokens + self.total_completion_tokens

    @property
    def total_llm_seconds(self) -> float:
        return sum(c.duration_s for c in self.calls)

    @property
    def total_wall_clock_seconds(self) -> float:
        if self.wall_clock_start is None or self.wall_clock_end is None:
            return 0.0
        return self.wall_clock_end - self.wall_clock_start

    # ── per-agent breakdown ───────────────────────────────────────────────────
    def by_agent(self) -> dict[str, dict]:
        out: dict[str, dict] = defaultdict(
            lambda: {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "seconds": 0.0}
        )
        for c in self.calls:
            a = out[c.agent]
            a["calls"] += 1
            a["prompt_tokens"] += c.prompt_tokens
            a["completion_tokens"] += c.completion_tokens
            a["seconds"] += c.duration_s
        return dict(out)

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def start_run(self):
        self.wall_clock_start = time.time()

    def end_run(self):
        self.wall_clock_end = time.time()

    def reset(self):
        self.calls.clear()
        self.wall_clock_start = None
        self.wall_clock_end = None
        self.per_round_seconds.clear()
        self.current_agent = "unknown"

    def record_call(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        duration_s: float,
        model: str,
        success: bool = True,
    ):
        self.calls.append(CallRecord(
            agent=self.current_agent,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            duration_s=duration_s,
            success=success,
        ))

    @contextmanager
    def agent_context(self, name: str):
        prev = self.current_agent
        self.current_agent = name
        try:
            yield
        finally:
            self.current_agent = prev

    @contextmanager
    def round_timer(self, round_idx: int):
        t0 = time.time()
        try:
            yield
        finally:
            self.per_round_seconds[round_idx] = time.time() - t0

    # ── serialization ─────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "total_calls": self.total_calls,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
            "total_llm_seconds": round(self.total_llm_seconds, 3),
            "total_wall_clock_seconds": round(self.total_wall_clock_seconds, 3),
            "per_round_seconds": {k: round(v, 3) for k, v in self.per_round_seconds.items()},
            "by_agent": {a: {**v, "seconds": round(v["seconds"], 3)} for a, v in self.by_agent().items()},
            "calls": [asdict(c) for c in self.calls],
        }


# ── Module-level singleton ────────────────────────────────────────────────────
TRACKER = UsageTracker()
