# Simulation-Aware In-Context Policy Improvement for Analog Layout

Demo of the framework described in our paper *"Simulation-Aware In-Context Policy Improvement for Analog Layout"* (ICLAD 2026 accepted as long paper). The open-source demo runs on a **PDK-free synthetic OTA environment** (no real layout generator or simulator); the framework's agent loop, journal, and reflection logic are exercised end-to-end.

## Architecture

```
Analyzer (×1)            → circuit-level hints (saved once)
Main loop (×N rounds):
  Supervisor             → choose one parameter family + 1–3 goals
  Executor               → concrete diff → SyntheticOTAOracle.evaluate()
                           (retries on high legalization_risk)
  Reflector              → journal entry (saved per round)
```

Five parameter families: `net_weights`, `placement_bias`, `symmetry`, `routing_priority`, `wire_widths`. `symmetry` is structured (`pairs`, `self_symmetric`, `matched_nets`).

`SyntheticOTAOracle` is a handcrafted nonlinear surrogate: layout controls →
synthetic PEX (R/C, congestion, legalization_risk, route_fail_risk) →
synthetic post-layout sim (gain, ugb, pm, cmrr, offset, power) → score + diagnosis. The model is documented inline in `icpi/tools/oracle.py`.

## Quick start

Requires **Python 3.10+**.

```bash
pip install -r requirements.txt

# provider API keys — key file OR env var (env var wins)
echo "YOUR_GEMINI_KEY"     > llm_api/key.txt              # or export GEMINI_API_KEY
echo "YOUR_DEEPSEEK_KEY"   > llm_api/deepseek_key.txt     # or export DEEPSEEK_API_KEY
echo "YOUR_OPENROUTER_KEY" > llm_api/openrouter_key.txt   # or export OPENROUTER_API_KEY

# offline tests (no API call)
python -m pytest tests/ -q

# end-to-end run (default: Gemini flash)
python run.py

# pick a model — Gemini, DeepSeek direct, or any OpenRouter model
python run.py --model pro --rounds 12 --sim-every 3
python run.py --model deepseek        # DeepSeek direct (deepseek-chat)
python run.py --model or-qwen         # Qwen via OpenRouter gateway
python run.py --list-models
```

## Providers

One OpenAI-compatible client backs every non-Gemini provider; the backend is
inferred from the model id (`vendor/model` → OpenRouter, `deepseek-*` → DeepSeek
direct, otherwise Gemini). Use an alias from `--list-models` or pass a full id
(e.g. `--model deepseek/deepseek-r1` routes through OpenRouter).

## CLI

| Flag | Default | Description |
|------|---------|-------------|
| `--model` | `flash` | Model alias (Gemini / DeepSeek / OpenRouter — see `--list-models`) or full model ID |
| `--rounds` | 6 | Number of ICPI iterations |
| `--sim-every` | 2 | Expose synthetic sim every N rounds |
| `--seed` | 42 | Deterministic-mode seed for the oracle |
| `--benchmark` | `icpi/benchmark/ota_toy.json` | Netlist file |
| `--list-models` | — | Print model aliases and exit |

## Outputs (`runs/<timestamp>/`)

| File | Description |
|------|-------------|
| `journal.jsonl` | One JSON line per round (family, diff, reflection, FoM) |
| `state_round*.json` | Full LayoutState snapshot per round |
| `analyzer_hints.json` | One-shot circuit analysis output |
| `summary.json` | Machine-readable run summary, including `usage` block |
| `summary.md` | Human-readable FoM table + per-agent token / time breakdown |

`summary.md` always includes wall-clock, LLM-time, and per-agent token counts.

## Connecting real tools

`icpi/tools/oracle.py` is the only stub. To plug in a real flow, replace
`SyntheticOTAOracle.evaluate(controls)` so its return shape matches:

```python
{
  "pex": {"net_rc": ..., "pair_mismatch": ..., "congestion": ...,
          "legalization_risk": ..., "route_fail_risk": ...},
  "sim": {"gain_db": ..., "ugb_mhz": ..., "pm_deg": ..., "cmrr_db": ...,
          "offset_mV": ..., "power_uW": ...},
  "score": float, "violations": {...}, "diagnosis": [...]
}
```

The rest of the pipeline may need to be changed accouding to the specific feedback structure provided.

## Citation

If you use this work, please cite:

```bibtex
@inproceedings{liu2026simulation,
  author    = {Bingyang Liu and Ziming Wei and Xiaohan Gao and David Z. Pan},
  title     = {Simulation-Aware In-Context Policy Improvement for {LLM}-Aided Analog Layout Refinement},
  booktitle = {2026 IEEE International Conference on LLM-Aided Design (ICLAD)},
  year      = {2026},
  publisher = {IEEE}
}
```

## License

Released under the [MIT License](LICENSE).
