"""
Analyzer: one-shot circuit analysis before the ICPI loop.
"""
from __future__ import annotations
import json
from icpi.agents.base import BaseAgent

SCHEMA = {
    "type": "object",
    "properties": {
        "stages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "devices": {"type": "array", "items": {"type": "string"}},
                    "function": {"type": "string"},
                },
                "required": ["name", "devices", "function"],
            },
        },
        "critical_pairs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "devices": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                    "importance": {"type": "number"},
                },
                "required": ["devices", "reason", "importance"],
            },
        },
        "critical_nets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "sensitivity": {"type": "string"},
                    "importance": {"type": "number"},
                },
                "required": ["name", "sensitivity", "importance"],
            },
        },
        "family_priorities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "family": {"type": "string"},
                    "reason": {"type": "string"},
                    "priority": {"type": "number"},
                },
                "required": ["family", "reason", "priority"],
            },
        },
    },
    "required": ["stages", "critical_pairs", "critical_nets", "family_priorities"],
}


class AnalyzerAgent(BaseAgent):
    prompt_file = "analyzer.md"
    output_schema = SCHEMA
    agent_name = "analyzer"

    def run(self, netlist: dict) -> dict:
        user_prompt = (
            "Analyze the following analog IC netlist and produce circuit-level hints.\n\n"
            "NETLIST:\n" + json.dumps(netlist, indent=2)
        )
        return self._call(user_prompt)
