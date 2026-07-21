"""
Five parameter families exposed to the ICPI loop.
Bounds and semantics align with SyntheticOTAOracle (see SYNTHETIC_ENVIROMENT.md).
"""
from __future__ import annotations
import copy
from typing import Any

FAMILIES = ["net_weights", "placement_bias", "symmetry", "routing_priority", "wire_widths"]

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULTS: dict[str, Any] = {
    "net_weights":      {},   # net → float, default 1.0
    "placement_bias":   {},   # device → float in [-1, 1], default 0.0
    "symmetry":         {"pairs": [], "self_symmetric": [], "matched_nets": []},
    "routing_priority": {},   # net → float, default 1.0
    "wire_widths":      {},   # net → float multiplier, default 1.0
}

# ── Bounds ─────────────────────────────────────────────────────────────────────
BOUNDS: dict[str, tuple[float, float]] = {
    "net_weights":      (0.5, 8.0),
    "placement_bias":   (-1.0, 1.0),
    "routing_priority": (0.5, 4.0),
    "wire_widths":      (1.0, 6.0),
}


def make_params() -> dict[str, dict]:
    return copy.deepcopy(DEFAULTS)


def apply_diff(params: dict, family: str, diff: Any) -> dict:
    """
    Return a new params dict with diff applied to one family.

    For non-symmetry families: diff is {key: value}; values clamped to bounds.
    For symmetry: diff is the full structured replacement with keys
        pairs / self_symmetric / matched_nets. Missing keys are preserved
        from the previous symmetry dict (partial update).
    """
    if family not in FAMILIES:
        raise ValueError(f"Unknown family: {family}")
    new_params = copy.deepcopy(params)

    if family == "symmetry":
        sym = new_params.setdefault(
            "symmetry", {"pairs": [], "self_symmetric": [], "matched_nets": []}
        )
        if not isinstance(diff, dict):
            raise ValueError("symmetry diff must be a dict")
        for k in ("pairs", "self_symmetric", "matched_nets"):
            if k in diff:
                sym[k] = _normalize_sym_field(k, diff[k])
        return new_params

    lo, hi = BOUNDS[family]
    if not isinstance(diff, dict):
        raise ValueError(f"{family} diff must be a flat dict")
    target = new_params.setdefault(family, {})
    for key, val in diff.items():
        target[key] = float(max(lo, min(hi, float(val))))
    return new_params


def _normalize_sym_field(field: str, value: Any) -> list:
    """Coerce symmetry field into the canonical list representation."""
    if not isinstance(value, list):
        raise ValueError(f"symmetry.{field} must be a list")
    if field == "self_symmetric":
        return [str(x) for x in value]
    # pairs / matched_nets: list of 2-element lists
    out = []
    for item in value:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            out.append([str(item[0]), str(item[1])])
        else:
            raise ValueError(f"symmetry.{field} entries must be 2-element lists")
    return out


def validate(params: dict) -> list[str]:
    """Return list of hard violations (parameter out of range)."""
    violations = []
    for family, bounds in BOUNDS.items():
        lo, hi = bounds
        for key, val in params.get(family, {}).items():
            try:
                num = float(val)
            except (TypeError, ValueError):
                violations.append(f"{family}[{key}]={val!r} not a number")
                continue
            if not (lo <= num <= hi):
                violations.append(f"{family}[{key}]={val} out of [{lo},{hi}]")
    sym = params.get("symmetry", {})
    if not isinstance(sym, dict):
        violations.append("symmetry must be a dict with pairs/self_symmetric/matched_nets")
    return violations
