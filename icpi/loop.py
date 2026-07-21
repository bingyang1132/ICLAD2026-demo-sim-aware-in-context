"""
ICPI orchestrator: Analyzer → main loop (Supervisor → Executor → Oracle → Reflector).

Uses the SyntheticOTAOracle as the unified PEX + sim backend.
Tracks wall-clock time and per-agent token usage in the global TRACKER.
"""
from __future__ import annotations
import copy
import json
import logging
import time
from pathlib import Path
from datetime import datetime

from icpi.config import DEFAULT_ROUNDS, DEFAULT_SIM_EVERY, RUNS_DIR, resolve_model
from icpi.action_space import make_params
from icpi.state import LayoutState, DeviceInfo, NetInfo, ParasiticSummary, SimResults
from icpi.journal import DesignJournal
from icpi.fom import compute_fom
from icpi.tools.oracle import SyntheticOTAOracle
from icpi.usage import TRACKER
from icpi.agents.analyzer import AnalyzerAgent
from icpi.agents.supervisor import SupervisorAgent
from icpi.agents.executor import ExecutorAgent
from icpi.agents.reflector import ReflectorAgent

logger = logging.getLogger(__name__)


def _build_initial_state(netlist: dict, params: dict) -> LayoutState:
    devices = [
        DeviceInfo(
            name=d["name"], type=d["type"], stage=d["stage"],
            nets=d.get("nets", []),
        )
        for d in netlist.get("devices", [])
    ]
    nets = [
        NetInfo(name=n["name"], type=n["type"], devices=n.get("devices", []))
        for n in netlist.get("nets", [])
    ]
    return LayoutState(
        round_idx=0,
        devices=devices,
        nets=nets,
        params=copy.deepcopy(params),
        parasitics=ParasiticSummary(),
        sim_results=SimResults(),
    )


def _oracle_to_state(state: LayoutState, oracle_result: dict, expose_sim: bool, targets: dict):
    """Mutate `state` with the oracle result. Sim metrics only exposed on schedule."""
    pex = oracle_result["pex"]
    state.parasitics = ParasiticSummary(
        net_rc=pex["net_rc"],
        pair_mismatch=pex["pair_mismatch"],
        congestion=pex["congestion"],
        legalization_risk=pex["legalization_risk"],
        route_fail_risk=pex["route_fail_risk"],
    )
    if expose_sim:
        sim = oracle_result["sim"]
        sr = SimResults(
            gain_db=sim["gain_db"],
            ugb_mhz=sim["ugb_mhz"],
            pm_deg=sim["pm_deg"],
            cmrr_db=sim["cmrr_db"],
            score=oracle_result["score"],
            violations=oracle_result["violations"],
            diagnosis=oracle_result["diagnosis"],
        )
        sr.fom = compute_fom(sr, targets)
        state.sim_results = sr


def run_icpi(
    netlist: dict,
    rounds: int = DEFAULT_ROUNDS,
    sim_every: int = DEFAULT_SIM_EVERY,
    model: str = "flash",
    seed: int = 42,
    run_dir: Path | None = None,
    sym_spec_path: Path | None = None,
) -> dict:
    """Run the full ICPI loop. Returns a summary dict."""
    if run_dir is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = RUNS_DIR / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    model_id = resolve_model(model)
    logger.info("Model: %s (alias=%s)", model_id, model)

    # ── Setup ─────────────────────────────────────────────────────────────────
    TRACKER.reset()
    TRACKER.start_run()

    journal = DesignJournal(run_dir / "journal.jsonl")
    targets = netlist["targets"]
    params = make_params()
    # Explicitly seed wire_widths so the LLM sees concrete 1.0× values to increase
    net_names = [n["name"] for n in netlist.get("nets", [])]
    params["wire_widths"] = {n: 1.0 for n in net_names}
    oracle = SyntheticOTAOracle(sym_spec_path=sym_spec_path, seed=seed)

    analyzer = AnalyzerAgent(model=model_id)
    supervisor = SupervisorAgent(model=model_id)
    executor = ExecutorAgent(model=model_id)
    reflector = ReflectorAgent(model=model_id)

    # ── Baseline (round 0) ────────────────────────────────────────────────────
    logger.info("Evaluating baseline (default controls)...")
    baseline_result = oracle.evaluate(params)
    state = _build_initial_state(netlist, params)
    _oracle_to_state(state, baseline_result, expose_sim=True, targets=targets)
    _save_state(state, run_dir, 0)
    logger.info(
        "Baseline FoM=%.4f  score=%.2f  Gain=%.1f UGB=%.2f PM=%.1f CMRR=%.1f",
        state.sim_results.fom, state.sim_results.score,
        state.sim_results.gain_db, state.sim_results.ugb_mhz,
        state.sim_results.pm_deg, state.sim_results.cmrr_db,
    )

    fom_history = [{
        "round": 0, "fom": state.sim_results.fom, "score": state.sim_results.score,
        "family": "baseline", "legalization_failed": False,
    }]

    # ── Analyzer (one-shot) ───────────────────────────────────────────────────
    logger.info("Running Analyzer...")
    analyzer_hints = analyzer.run(netlist)
    (run_dir / "analyzer_hints.json").write_text(json.dumps(analyzer_hints, indent=2))

    best_sim = copy.deepcopy(state.sim_results)
    best_params = copy.deepcopy(params)
    best_round = 0

    # ── Main loop ─────────────────────────────────────────────────────────────
    for k in range(1, rounds + 1):
        with TRACKER.round_timer(k):
            logger.info("=== Round %d/%d ===", k, rounds)
            state_before = copy.deepcopy(state)
            state_before.round_idx = k

            # Supervisor
            sup_out = supervisor.run(state, analyzer_hints, journal)
            family = sup_out["family"]
            goals = sup_out["goals"]
            logger.info("Supervisor chose family=%s", family)

            # Executor → Oracle
            new_params, oracle_result, diff_applied, leg_failed = executor.run(
                state, journal, netlist, family, goals, oracle
            )

            # Build the next state
            new_state = copy.deepcopy(state)
            new_state.round_idx = k
            new_state.params = new_params
            if not oracle_result:
                logger.warning("Round %d: rolled back; no oracle eval", k)
            else:
                expose_sim = (k % sim_every == 0)
                _oracle_to_state(new_state, oracle_result, expose_sim, targets)
                if expose_sim:
                    logger.info(
                        "Round %d  FoM=%.4f  score=%.2f  Gain=%.1f UGB=%.2f PM=%.1f CMRR=%.1f  leg_risk=%.2f",
                        k, new_state.sim_results.fom, new_state.sim_results.score,
                        new_state.sim_results.gain_db, new_state.sim_results.ugb_mhz,
                        new_state.sim_results.pm_deg, new_state.sim_results.cmrr_db,
                        new_state.parasitics.legalization_risk,
                    )
                    if (new_state.sim_results.fom and
                            (best_sim.fom is None or new_state.sim_results.fom > best_sim.fom)):
                        best_sim = copy.deepcopy(new_state.sim_results)
                        best_params = copy.deepcopy(new_params)
                        best_round = k

            _save_state(new_state, run_dir, k)

            # Reflector
            journal_entry = reflector.run(
                round_idx=k,
                family=family,
                goals=goals,
                diff=diff_applied,
                state_before=state_before,
                state_after=new_state,
                legalization_failed=leg_failed,
            )
            journal.append(journal_entry)

            fom_history.append({
                "round": k,
                "fom": new_state.sim_results.fom,
                "score": new_state.sim_results.score,
                "family": family,
                "legalization_failed": leg_failed,
            })

            state = new_state

    TRACKER.end_run()

    summary = {
        "run_dir": str(run_dir),
        "model": model_id,
        "model_alias": model,
        "rounds": rounds,
        "sim_every": sim_every,
        "seed": seed,
        "baseline_fom": fom_history[0]["fom"],
        "baseline_score": fom_history[0]["score"],
        "best_fom": best_sim.fom,
        "best_score": best_sim.score,
        "best_round": best_round,
        "best_sim": {
            "gain_db": best_sim.gain_db, "ugb_mhz": best_sim.ugb_mhz,
            "pm_deg": best_sim.pm_deg, "cmrr_db": best_sim.cmrr_db,
        },
        "best_params": best_params,
        "fom_history": fom_history,
        "usage": TRACKER.to_dict(),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    _write_markdown_summary(summary, run_dir)
    return summary


def _save_state(state: LayoutState, run_dir: Path, k: int):
    (run_dir / f"state_round{k:03d}.json").write_text(state.to_json())


def _write_markdown_summary(summary: dict, run_dir: Path):
    usage = summary["usage"]
    lines = [
        "# ICPI Run Summary",
        f"Model: `{summary['model']}` (alias `{summary['model_alias']}`)  |  "
        f"Rounds: {summary['rounds']}  |  sim_every: {summary['sim_every']}  |  seed: {summary['seed']}",
        "",
        f"**Baseline FoM**: {summary['baseline_fom']:.4f}  "
        f"(score {summary['baseline_score']:.2f})",
        f"**Best FoM**:     {summary['best_fom']:.4f}  "
        f"(score {summary['best_score']:.2f})  at round {summary['best_round']}",
        "",
        "## FoM history",
        "",
        "| Round | Family | FoM | Score | Legal |",
        "|-------|--------|-----|-------|-------|",
    ]
    for entry in summary["fom_history"]:
        fom_str = f"{entry['fom']:.4f}" if entry["fom"] is not None else "—"
        score_str = f"{entry['score']:.2f}" if entry["score"] is not None else "—"
        flag = "FAIL" if entry.get("legalization_failed") else "ok"
        lines.append(f"| {entry['round']} | {entry['family']} | {fom_str} | {score_str} | {flag} |")

    bs = summary.get("best_sim", {})
    lines += [
        "",
        "## Best layout metrics",
        f"Gain={bs.get('gain_db')} dB  UGB={bs.get('ugb_mhz')} MHz  "
        f"PM={bs.get('pm_deg')}°  CMRR={bs.get('cmrr_db')} dB",
        "",
        "## Usage",
        f"Wall clock: {usage['total_wall_clock_seconds']:.2f}s  |  "
        f"LLM time: {usage['total_llm_seconds']:.2f}s",
        f"LLM calls: {usage['total_calls']}  |  "
        f"Tokens: prompt={usage['total_prompt_tokens']}  "
        f"completion={usage['total_completion_tokens']}  "
        f"total={usage['total_tokens']}",
        "",
        "### Per-agent breakdown",
        "",
        "| Agent | Calls | Prompt tokens | Completion tokens | LLM seconds |",
        "|-------|-------|---------------|-------------------|-------------|",
    ]
    for agent, stats in usage["by_agent"].items():
        lines.append(
            f"| {agent} | {stats['calls']} | {stats['prompt_tokens']} | "
            f"{stats['completion_tokens']} | {stats['seconds']:.2f} |"
        )
    lines += [
        "",
        "### Per-round wall clock (s)",
        "",
        "| Round | Seconds |",
        "|-------|---------|",
    ]
    for r, s in usage["per_round_seconds"].items():
        lines.append(f"| {r} | {s:.2f} |")

    (run_dir / "summary.md").write_text("\n".join(lines))
