#!/usr/bin/env python3
"""
CLI entry point for the ICPI framework.

Examples:
  python run.py
  python run.py --rounds 12 --sim-every 3 --model pro
  python run.py --model gemini-2.5-flash-lite --seed 7
  python run.py --list-models
"""
import argparse
import json
import logging
import sys
from pathlib import Path

from icpi.config import MODELS, DEFAULT_MODEL_ALIAS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main():
    parser = argparse.ArgumentParser(description="ICPI analog layout optimizer")
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL_ALIAS,
        help=f"Model alias or full ID (Gemini / DeepSeek / OpenRouter). "
             f"Aliases: {', '.join(MODELS)}",
    )
    parser.add_argument("--rounds", type=int, default=6)
    parser.add_argument("--sim-every", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--benchmark",
        type=str,
        default="icpi/benchmark/ota_toy.json",
        help="Path to benchmark JSON",
    )
    parser.add_argument(
        "--list-models", action="store_true", help="Print available model aliases and exit"
    )
    args = parser.parse_args()

    if args.list_models:
        print("Available model aliases:")
        for alias, full in MODELS.items():
            print(f"  {alias:<14} → {full}")
        return

    benchmark_path = Path(args.benchmark)
    if not benchmark_path.exists():
        print(f"ERROR: benchmark file not found: {benchmark_path}", file=sys.stderr)
        sys.exit(1)
    netlist = json.loads(benchmark_path.read_text())

    from icpi.loop import run_icpi
    summary = run_icpi(
        netlist=netlist,
        rounds=args.rounds,
        sim_every=args.sim_every,
        model=args.model,
        seed=args.seed,
    )

    bs = summary["best_sim"]
    usage = summary["usage"]
    print("\n" + "=" * 70)
    print(f"  Run dir       : {summary['run_dir']}")
    print(f"  Model         : {summary['model']}  (alias: {summary['model_alias']})")
    print(f"  Rounds / seed : {summary['rounds']} / seed={summary['seed']}")
    print(f"  Baseline FoM  : {summary['baseline_fom']:.4f}   "
          f"(score {summary['baseline_score']:.2f})")
    print(f"  Best     FoM  : {summary['best_fom']:.4f}   "
          f"(score {summary['best_score']:.2f}) @ round {summary['best_round']}")
    print(f"  Best metrics  : Gain={bs['gain_db']} dB  UGB={bs['ugb_mhz']} MHz  "
          f"PM={bs['pm_deg']}°  CMRR={bs['cmrr_db']} dB")
    print(f"  Wall clock    : {usage['total_wall_clock_seconds']:.2f}s   "
          f"(LLM {usage['total_llm_seconds']:.2f}s in {usage['total_calls']} calls)")
    print(f"  Tokens        : prompt={usage['total_prompt_tokens']}  "
          f"completion={usage['total_completion_tokens']}  "
          f"total={usage['total_tokens']}")
    print("=" * 70)


if __name__ == "__main__":
    main()
