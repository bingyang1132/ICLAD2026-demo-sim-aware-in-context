"""
Smoke test: run 2 rounds with a FakeLLM (no real API call).
Verifies the orchestrator + oracle + usage tracker end-to-end.
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

NETLIST_PATH = Path(__file__).parent.parent / "icpi/benchmark/ota_toy.json"


def _fake_chat(system_prompt, user_prompt, output_schema=None, json_mode=False,
               model="gemini-2.5-flash"):
    """Deterministic stub that returns valid JSON for each agent's schema.

    Executor now uses json_mode=True (output_schema=None), so we dispatch on
    prompt content rather than schema properties for that agent.
    """
    from icpi.usage import TRACKER
    TRACKER.record_call(prompt_tokens=42, completion_tokens=17,
                        duration_s=0.001, model=model, success=True)

    # Executor uses json_mode without a schema — dispatch on prompt content
    if json_mode and output_schema is None:
        return {
            "diff": {"pairs": [["M1", "M2"]], "matched_nets": [["in_p", "in_n"]]},
            "rationale": "enable symmetry",
        }

    if output_schema is None:
        return "ok"
    props = output_schema.get("properties", {})
    if "stages" in props:  # Analyzer
        return {
            "stages": [{"name": "diff_pair", "devices": ["M1", "M2"], "function": "input amp"}],
            "critical_pairs": [{"devices": ["M1", "M2"], "reason": "input pair", "importance": 1.0}],
            "critical_nets": [{"name": "out2", "sensitivity": "high", "importance": 1.0}],
            "family_priorities": [{"family": "symmetry", "reason": "match-critical", "priority": 1.0}],
        }
    if "family" in props:  # Supervisor
        return {"family": "symmetry", "goals": ["Declare input-pair symmetry"], "rationale": "test"}
    if "reflection" in props:  # Reflector
        return {
            "reflection": "Symmetry improved CMRR.",
            "outcome_summary": "CMRR up ~12dB",
            "takeaway": "Keep M1/M2 declared.",
        }
    return {}


def test_loop_smoke():
    # mock the genai client so we never even attempt to read key.txt
    netlist = json.loads(NETLIST_PATH.read_text())

    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "smoke_run"
        with patch("llm_api.router.chat", side_effect=_fake_chat):
            from icpi.loop import run_icpi
            summary = run_icpi(
                netlist=netlist,
                rounds=2,
                sim_every=1,
                model="flash",
                seed=0,
                run_dir=run_dir,
            )

        assert summary["rounds"] == 2
        assert summary["baseline_fom"] is not None
        assert summary["best_fom"] is not None
        assert summary["best_score"] is not None
        assert len(summary["fom_history"]) == 3
        # symmetry diff should have raised CMRR; FoM should improve
        assert summary["best_fom"] >= summary["baseline_fom"]

        journal_path = run_dir / "journal.jsonl"
        assert journal_path.exists()
        lines = [l for l in journal_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 2

        summary_md = run_dir / "summary.md"
        assert summary_md.exists()
        md = summary_md.read_text()
        assert "Best FoM" in md
        assert "Per-agent breakdown" in md
        assert "Wall clock" in md

        # usage tracker recorded calls (fake LLM doesn't have token usage,
        # so just check call count)
        usage = summary["usage"]
        assert usage["total_calls"] > 0
        assert "analyzer" in usage["by_agent"]
        assert "supervisor" in usage["by_agent"]


if __name__ == "__main__":
    test_loop_smoke()
    print("ok")
