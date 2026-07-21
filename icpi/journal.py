"""
DesignJournal: per-run JSONL file, one entry per round.
Retrieval: most-recent K entries + entries matching the requested family.
"""
from __future__ import annotations
import json
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class JournalEntry:
    round_idx: int
    family: str
    goals: str
    diff: dict
    outcome_summary: str   # short human-readable result
    reflection: str        # Reflector output
    fom_before: Optional[float]
    fom_after: Optional[float]
    legalization_failed: bool = False


class DesignJournal:
    def __init__(self, path: Path):
        self.path = path
        self.entries: list[JournalEntry] = []
        if path.exists():
            self._load()

    def _load(self):
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if line:
                    d = json.loads(line)
                    self.entries.append(JournalEntry(**d))

    def append(self, entry: JournalEntry):
        self.entries.append(entry)
        with open(self.path, "a") as f:
            f.write(json.dumps(asdict(entry)) + "\n")

    def retrieve(self, family: str, top_k: int = 4) -> list[JournalEntry]:
        """Return up to top_k entries: same-family first, then most recent."""
        same = [e for e in self.entries if e.family == family]
        other = [e for e in self.entries if e.family != family]
        combined = same[-top_k:] + other[-(top_k - len(same[-top_k:])):]
        # deduplicate preserving order
        seen: set[int] = set()
        result = []
        for e in combined:
            if id(e) not in seen:
                seen.add(id(e))
                result.append(e)
        return result[-top_k:]

    def to_context_str(self, family: str, top_k: int = 4) -> str:
        entries = self.retrieve(family, top_k)
        if not entries:
            return "(No journal entries yet)"
        lines = []
        for e in entries:
            fom_str = f"FoM {e.fom_before}→{e.fom_after}" if e.fom_after is not None else "sim not run"
            status = "LEGALIZATION_FAIL" if e.legalization_failed else "OK"
            lines.append(
                f"[Round {e.round_idx}] family={e.family} status={status} {fom_str}\n"
                f"  goals: {e.goals}\n"
                f"  diff: {json.dumps(e.diff)}\n"
                f"  reflection: {e.reflection}"
            )
        return "\n\n".join(lines)
