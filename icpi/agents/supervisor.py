"""
Supervisor: selects one parameter family + formulates goals.
"""
from __future__ import annotations
from icpi.agents.base import BaseAgent
from icpi.state import LayoutState
from icpi.journal import DesignJournal

SCHEMA = {
    "type": "object",
    "properties": {
        "family": {
            "type": "string",
            "enum": ["net_weights", "placement_bias", "symmetry",
                     "routing_priority", "wire_widths"],
        },
        "goals": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 3,
        },
        "rationale": {"type": "string"},
    },
    "required": ["family", "goals", "rationale"],
}


class SupervisorAgent(BaseAgent):
    prompt_file = "supervisor.md"
    output_schema = SCHEMA
    agent_name = "supervisor"

    def run(self, state: LayoutState, analyzer_hints: dict, journal: DesignJournal) -> dict:
        user_prompt = (
            "CURRENT LAYOUT STATE:\n" + state.compact_summary() + "\n\n"
            "CIRCUIT ANALYSIS HINTS:\n" + _fmt_hints(analyzer_hints) + "\n\n"
            "DESIGN JOURNAL (recent entries):\n" +
            journal.to_context_str(family="", top_k=4) + "\n\n"
            "Select the next parameter family to tune and state your goals."
        )
        return self._call(user_prompt)


def _fmt_hints(hints: dict) -> str:
    lines = []
    for cp in hints.get("critical_pairs", []):
        lines.append(f"Match pair {cp['devices']}: {cp['reason']} (importance={cp['importance']})")
    for cn in hints.get("critical_nets", []):
        lines.append(f"Critical net '{cn['name']}': {cn['sensitivity']} (importance={cn['importance']})")
    for fp in hints.get("family_priorities", []):
        lines.append(f"Family '{fp['family']}' priority={fp['priority']}: {fp['reason']}")
    return "\n".join(lines) if lines else "(no hints)"
