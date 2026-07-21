"""
Reflector: compresses round outcome into a design journal entry.
"""
from __future__ import annotations
from icpi.agents.base import BaseAgent
from icpi.state import LayoutState
from icpi.journal import JournalEntry

SCHEMA = {
    "type": "object",
    "properties": {
        "reflection": {"type": "string"},
        "outcome_summary": {"type": "string"},
        "takeaway": {"type": "string"},
    },
    "required": ["reflection", "outcome_summary", "takeaway"],
}


class ReflectorAgent(BaseAgent):
    prompt_file = "reflector.md"
    output_schema = SCHEMA
    agent_name = "reflector"

    def run(
        self,
        round_idx: int,
        family: str,
        goals: list[str],
        diff: dict,
        state_before: LayoutState,
        state_after: LayoutState,
        legalization_failed: bool,
    ) -> JournalEntry:
        fom_before = state_before.sim_results.fom
        fom_after = state_after.sim_results.fom

        user_prompt = (
            f"ROUND: {round_idx}\n"
            f"FAMILY: {family}\n"
            f"GOALS:\n" + "\n".join(f"- {g}" for g in goals) + "\n\n"
            f"PARAMETER DIFF APPLIED: {diff}\n\n"
            f"STATE BEFORE:\n{state_before.compact_summary()}\n\n"
            f"STATE AFTER:\n{state_after.compact_summary()}\n\n"
            f"LEGALIZATION FAILED: {legalization_failed}\n\n"
            "Write a concise journal entry reflecting on this round."
        )
        result = self._call(user_prompt)
        reflection_text = result.get("reflection", "") + " " + result.get("takeaway", "")
        outcome_summary = result.get("outcome_summary", "")

        return JournalEntry(
            round_idx=round_idx,
            family=family,
            goals="; ".join(goals),
            diff=diff,
            outcome_summary=outcome_summary,
            reflection=reflection_text.strip(),
            fom_before=fom_before,
            fom_after=fom_after,
            legalization_failed=legalization_failed,
        )
