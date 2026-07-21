"""
SyntheticOTAOracle — PDK-free synthetic environment.
Maps layout controls → synthetic PEX → synthetic post-layout sim metrics → score.

Implements the math model described in SYNTHETIC_ENVIROMENT.md.
"""
from __future__ import annotations
import json
import math
import random
import statistics
from pathlib import Path
from typing import Any

# ── Per-net nominal parameters (section 3) ────────────────────────────────────
NET_BASE: dict[str, dict[str, float]] = {
    "in_p":     {"length_um": 20.0, "r_ohm_per_um": 0.08, "c_fF_per_um": 0.015, "criticality": 0.7},
    "in_n":     {"length_um": 20.0, "r_ohm_per_um": 0.08, "c_fF_per_um": 0.015, "criticality": 0.7},
    "ptail":    {"length_um": 12.0, "r_ohm_per_um": 0.06, "c_fF_per_um": 0.012, "criticality": 0.5},
    "out1":     {"length_um": 18.0, "r_ohm_per_um": 0.09, "c_fF_per_um": 0.020, "criticality": 0.8},
    "out2":     {"length_um": 28.0, "r_ohm_per_um": 0.10, "c_fF_per_um": 0.025, "criticality": 1.0},
    "comp_mid": {"length_um": 10.0, "r_ohm_per_um": 0.08, "c_fF_per_um": 0.018, "criticality": 0.8},
    "vout":     {"length_um": 35.0, "r_ohm_per_um": 0.12, "c_fF_per_um": 0.035, "criticality": 1.0},
    "vbias_p":  {"length_um": 30.0, "r_ohm_per_um": 0.06, "c_fF_per_um": 0.010, "criticality": 0.3},
    "vbias_n":  {"length_um": 30.0, "r_ohm_per_um": 0.06, "c_fF_per_um": 0.010, "criticality": 0.3},
}

DEVICE_NETS: dict[str, list[str]] = {
    "M0": ["ptail", "vbias_p", "VDD"],
    "M1": ["out1", "in_p", "ptail"],
    "M2": ["out2", "in_n", "ptail"],
    "M3": ["out1", "GND"],
    "M4": ["out2", "out1", "GND"],
    "M6": ["vout", "out2", "VDD"],
    "M7": ["vout", "vbias_n", "GND"],
    "Cc": ["out2", "comp_mid"],
    "Rc": ["comp_mid", "vout"],
}

# ── Bounds (section 4) ─────────────────────────────────────────────────────────
W_LO, W_HI = 0.5, 8.0
P_LO, P_HI = 0.5, 4.0
A_LO, A_HI = 1.0, 6.0
B_LO, B_HI = -1.0, 1.0

# ── Nominal circuit constants (section 9) ──────────────────────────────────────
C_CC_FF = 100.0
C_LOAD_FF = 100.0
GM1_US = 12.0
GM6_US = 35.0
RO1_KOHM = 1200.0
RO2_KOHM = 900.0
POWER_UW_NOM = 120.0
R_C_NOM = 2000.0

TARGETS = {"gain_db": 50.0, "ugb_mhz": 18.0, "pm_deg": 60.0, "cmrr_db": 70.0}


# ── Helpers ────────────────────────────────────────────────────────────────────
def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def softplus(x: float) -> float:
    if x > 30:
        return x
    return math.log1p(math.exp(x))


def sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def relu(x: float) -> float:
    return max(0.0, x)


def normalize_controls(controls: dict) -> dict:
    """Clamp all per-key values to legal ranges; fill missing keys with defaults."""
    out = {
        "net_weights": {},
        "placement_bias": {},
        "symmetry": {},
        "routing_priority": {},
        "wire_widths": {},
    }
    for n, v in (controls.get("net_weights") or {}).items():
        out["net_weights"][n] = clamp(float(v), W_LO, W_HI)
    for n, v in (controls.get("routing_priority") or {}).items():
        out["routing_priority"][n] = clamp(float(v), P_LO, P_HI)
    for n, v in (controls.get("wire_widths") or {}).items():
        out["wire_widths"][n] = clamp(float(v), A_LO, A_HI)
    for d, v in (controls.get("placement_bias") or {}).items():
        out["placement_bias"][d] = clamp(float(v), B_LO, B_HI)

    sym = controls.get("symmetry") or {}
    pairs = []
    for p in sym.get("pairs", []) or []:
        if isinstance(p, (list, tuple)) and len(p) == 2:
            pairs.append([str(p[0]), str(p[1])])
    self_sym = [str(x) for x in (sym.get("self_symmetric") or [])]
    matched_nets = []
    for p in sym.get("matched_nets", []) or []:
        if isinstance(p, (list, tuple)) and len(p) == 2:
            matched_nets.append([str(p[0]), str(p[1])])
    out["symmetry"] = {"pairs": pairs, "self_symmetric": self_sym, "matched_nets": matched_nets}
    return out


# ──────────────────────────────────────────────────────────────────────────────
class SyntheticOTAOracle:
    """
    Open-source synthetic OTA environment.
    evaluate(controls) → {pex, sim, score, violations, diagnosis}.
    """

    def __init__(
        self,
        sym_spec_path: Path | str | None = None,
        seed: int = 0,
        deterministic: bool = True,
    ):
        if sym_spec_path is None:
            sym_spec_path = Path(__file__).parent.parent / "benchmark" / "sym.json"
        with open(sym_spec_path) as f:
            self.sym_spec = json.load(f)
        self.seed = seed
        self.deterministic = deterministic
        self._call_count = 0

    # ── Top-level entry ───────────────────────────────────────────────────────
    def evaluate(self, controls: dict) -> dict:
        self._call_count += 1
        rng = random.Random(self.seed + self._call_count) if not self.deterministic \
            else random.Random(self.seed)
        c = normalize_controls(controls)

        # Section 5 — congestion / legalization / route_fail risks
        P_place, P_route, P_width = self._compute_pressures(c)
        congestion = sigmoid(0.8 * P_place + 1.0 * P_route + 0.5 * P_width - 1.5)
        legalization_risk = sigmoid(1.2 * P_place + 0.8 * P_width + 0.4 * P_route - 1.2)
        route_fail_risk = sigmoid(1.0 * P_route + 0.6 * P_width + 0.3 * P_place - 1.8)

        # Section 6 — synthetic net length model
        net_lengths = self._compute_net_lengths(c, congestion)

        # Section 7 — synthetic PEX
        net_rc = self._compute_pex(c, net_lengths, congestion, rng)

        # Section 8 — symmetry-related scores
        sym_scores = self._compute_symmetry_scores(c, net_rc)

        pex = {
            "net_rc": net_rc,
            "pair_mismatch": {
                "input_pair": sym_scores["S_input"],
                "mirror_load": sym_scores["S_load"],
                "in_p_in_n": sym_scores["S_in_net"],
                "out1_out2": sym_scores["S_out_net"],
            },
            "congestion": round(congestion, 4),
            "legalization_risk": round(legalization_risk, 4),
            "route_fail_risk": round(route_fail_risk, 4),
        }

        # Section 9 — synthetic post-layout simulation
        sim = self._compute_sim(net_rc, sym_scores, congestion, route_fail_risk, rng)

        # Section 10 — score and violations
        score, violations = self._compute_score(sim, legalization_risk, route_fail_risk,
                                                congestion)
        diagnosis = self._generate_diagnosis(sim, pex, sym_scores)
        return {
            "pex": pex,
            "sim": sim,
            "score": round(score, 3),
            "violations": violations,
            "diagnosis": diagnosis,
        }

    # ── Section 5: pressures ──────────────────────────────────────────────────
    def _compute_pressures(self, c: dict) -> tuple[float, float, float]:
        weights = c["net_weights"]
        priority = c["routing_priority"]
        widths = c["wire_widths"]

        def _avg_for(net_factor):
            vals = []
            for n in NET_BASE:
                crit = NET_BASE[n]["criticality"]
                vals.append(crit * net_factor(n))
            return statistics.mean(vals) if vals else 0.0

        def f_place(n):
            w_n = weights.get(n, 1.0)
            return softplus((w_n - 4.0) / 1.0) ** 2

        def f_route(n):
            p_n = priority.get(n, 1.0)
            a_n = widths.get(n, 1.0)
            return softplus((p_n * a_n - 8.0) / 2.0) ** 2

        P_place = _avg_for(f_place)
        P_route = _avg_for(f_route)
        # P_width — average over nets, no criticality weighting
        vals = [softplus((widths.get(n, 1.0) - 5.0) / 0.25) ** 2 for n in NET_BASE]
        P_width = statistics.mean(vals) if vals else 0.0
        return P_place, P_route, P_width

    # ── Section 6: net length model ───────────────────────────────────────────
    def _compute_net_lengths(self, c: dict, congestion: float) -> dict[str, float]:
        weights = c["net_weights"]
        priority = c["routing_priority"]
        bias = c["placement_bias"]

        # var bias per net = variance of biases of devices connected to that net
        def var_bias(net: str) -> float:
            devs = [d for d, nets in DEVICE_NETS.items() if net in nets]
            biases = [bias.get(d, 0.0) for d in devs]
            if len(biases) < 2:
                return 0.0
            return statistics.pvariance(biases)

        lengths = {}
        for n, base in NET_BASE.items():
            w = weights.get(n, 1.0)
            p = priority.get(n, 1.0)
            F_weight = w ** (-0.25)
            F_priority = p ** (-0.15)
            F_bias = math.exp(0.4 * var_bias(n))
            F_cong = 1 + 0.25 * congestion
            L = base["length_um"] * F_weight * F_priority * F_bias * F_cong
            L = clamp(L, 0.35 * base["length_um"], 2.5 * base["length_um"])
            lengths[n] = L
        return lengths

    # ── Section 7: synthetic PEX ──────────────────────────────────────────────
    def _compute_pex(
        self, c: dict, net_lengths: dict[str, float], congestion: float, rng: random.Random
    ) -> dict[str, dict[str, float]]:
        widths = c["wire_widths"]
        net_rc = {}
        for n, base in NET_BASE.items():
            L = net_lengths[n]
            a = widths.get(n, 1.0)
            eps_r = rng.gauss(0.0, 0.02)
            eps_c = rng.gauss(0.0, 0.02)
            R = base["r_ohm_per_um"] * L / a * (1 + 0.3 * congestion + eps_r)
            C = base["c_fF_per_um"] * L * (0.7 + 0.3 * a ** 0.7) * (1 + 0.2 * congestion + eps_c)
            net_rc[n] = {
                "r_ohm": round(max(R, 0.01), 3),
                "c_fF": round(max(C, 0.01), 3),
                "length_um": round(L, 2),
            }
        return net_rc

    # ── Section 8: symmetry scores ────────────────────────────────────────────
    def _compute_symmetry_scores(self, c: dict, net_rc: dict) -> dict[str, float]:
        sym = c["symmetry"]
        declared_pairs = {frozenset(p) for p in sym["pairs"]}
        declared_matched_nets = {frozenset(p) for p in sym["matched_nets"]}
        bias = c["placement_bias"]

        pair_scores = {}
        for pair_spec in self.sym_spec.get("required_pairs", []):
            devs = pair_spec["devices"]
            importance = pair_spec.get("importance", 1.0)
            declared = frozenset(devs) in declared_pairs
            A_missing = 0.0 if declared else 1.0
            A_bias = abs(bias.get(devs[0], 0.0) + bias.get(devs[1], 0.0))
            S = importance * (0.6 * A_missing + 0.4 * A_bias)
            pair_scores[pair_spec["name"]] = clamp(S, 0.0, 1.5)

        # matched net scores
        net_scores = {}
        for spec in self.sym_spec.get("matched_net_pairs", []):
            nets = spec["nets"]
            importance = spec.get("importance", 1.0)
            L1 = net_rc.get(nets[0], {}).get("length_um", 1.0)
            L2 = net_rc.get(nets[1], {}).get("length_um", 1.0)
            mean = (L1 + L2) / 2 if (L1 + L2) > 0 else 1.0
            base_mismatch = abs(L1 - L2) / mean
            declared = frozenset(nets) in declared_matched_nets
            score = importance * base_mismatch + (0.0 if declared else 0.3 * importance)
            net_scores[f"{nets[0]}_{nets[1]}"] = clamp(score, 0.0, 1.5)

        S_input = pair_scores.get("input_pair", 0.0)
        S_load = pair_scores.get("mirror_load", 0.0)
        S_in_net = net_scores.get("in_p_in_n", 0.0)
        S_out_net = net_scores.get("out1_out2", 0.0)

        return {
            "S_input": S_input,
            "S_load": S_load,
            "S_in_net": S_in_net,
            "S_out_net": S_out_net,
            "pair_scores": pair_scores,
            "net_scores": net_scores,
        }

    # ── Section 9: post-layout sim model ──────────────────────────────────────
    def _compute_sim(
        self,
        net_rc: dict,
        sym: dict,
        congestion: float,
        route_fail_risk: float,
        rng: random.Random,
    ) -> dict[str, float]:
        S_input = sym["S_input"]
        S_load = sym["S_load"]
        S_in_net = sym["S_in_net"]

        # 9.1 output node parasitics
        C_out2 = net_rc["out2"]["c_fF"] + 0.3 * net_rc["comp_mid"]["c_fF"]
        C_vout = net_rc["vout"]["c_fF"] + 0.3 * net_rc["comp_mid"]["c_fF"]
        R_vout = net_rc["vout"]["r_ohm"]
        R_comp_mid = net_rc["comp_mid"]["r_ohm"]
        R_ptail = net_rc["ptail"]["r_ohm"]

        # 9.2 transconductance
        gm1_eff = max(0.5 * GM1_US * 1e-6,
                      GM1_US * 1e-6 * (1 - 0.08 * congestion - 0.05 * S_input))
        gm6_eff = max(0.5 * GM6_US * 1e-6,
                      GM6_US * 1e-6 * (1 - 0.06 * congestion))

        # 9.3 output resistance
        ro1_eff = RO1_KOHM * 1e3 / (1 + 0.5 * S_load + 0.2 * congestion)
        ro2_eff = RO2_KOHM * 1e3 / (1 + 0.3 * congestion)

        # 9.4 DC gain
        A1 = gm1_eff * ro1_eff
        A2 = gm6_eff * ro2_eff
        gain_db = 20 * math.log10(max(A1 * A2, 1e-9))
        gain_db -= 4.0 * S_load + 2.0 * congestion
        gain_db = clamp(gain_db, 20.0, 80.0)

        # 9.5 UGB
        Cc_eff_fF = C_CC_FF + 0.5 * C_out2 + 0.2 * C_vout
        Cc_eff_F = Cc_eff_fF * 1e-15
        UGB_Hz = gm1_eff / (2 * math.pi * Cc_eff_F)
        UGB_MHz = UGB_Hz / 1e6 * (1 - 0.15 * route_fail_risk)

        # 9.6 PM (two-pole + zero approximation)
        C2_eff_fF = C_LOAD_FF + C_vout + 0.2 * C_out2
        C2_eff_F = C2_eff_fF * 1e-15
        p2_Hz = gm6_eff / (2 * math.pi * C2_eff_F)
        R_c_eff = R_C_NOM + R_comp_mid + 0.5 * R_vout
        z_Hz = 1.0 / (2 * math.pi * R_c_eff * C_CC_FF * 1e-15)
        pm_deg = (
            90.0
            - math.degrees(math.atan(UGB_Hz / p2_Hz))
            + 0.35 * math.degrees(math.atan(UGB_Hz / z_Hz))
            - 10.0 * congestion
            - 8.0 * route_fail_risk
        )
        pm_deg = clamp(pm_deg, 10.0, 90.0)

        # 9.7 CMRR
        S_tail = min(1.0, R_ptail / 10.0)
        cmrr_db = 82.0 - 22.0 * S_input - 12.0 * S_in_net - 5.0 * S_tail - 4.0 * congestion
        cmrr_db = clamp(cmrr_db, 30.0, 90.0)

        return {
            "gain_db":  round(gain_db, 2),
            "ugb_mhz":  round(UGB_MHz, 3),
            "pm_deg":   round(pm_deg, 2),
            "cmrr_db":  round(cmrr_db, 2),
        }

    # ── Section 10: score / violations ────────────────────────────────────────
    def _compute_score(
        self, sim: dict, legalization_risk: float, route_fail_risk: float, congestion: float
    ) -> tuple[float, dict[str, float]]:
        v_gain = relu((TARGETS["gain_db"] - sim["gain_db"]) / 10)
        v_ugb = relu((TARGETS["ugb_mhz"] - sim["ugb_mhz"]) / 5)
        v_pm = relu((TARGETS["pm_deg"] - sim["pm_deg"]) / 15)
        v_cmrr = relu((TARGETS["cmrr_db"] - sim["cmrr_db"]) / 15)
        violations = {
            "v_gain": round(v_gain, 4), "v_ugb": round(v_ugb, 4),
            "v_pm": round(v_pm, 4), "v_cmrr": round(v_cmrr, 4),
            "v_legal": round(legalization_risk, 4), "v_route": round(route_fail_risk, 4),
        }
        score = (
            100
            - 20 * v_gain ** 2
            - 20 * v_ugb ** 2
            - 20 * v_pm ** 2
            - 15 * v_cmrr ** 2
            - 10 * legalization_risk
            - 10 * route_fail_risk
            - 5 * congestion
        )
        return clamp(score, 0.0, 100.0), violations

    # ── Section 11: diagnosis ─────────────────────────────────────────────────
    def _generate_diagnosis(self, sim: dict, pex: dict, sym: dict) -> list[str]:
        out = []
        net_rc = pex["net_rc"]
        if sim["cmrr_db"] < TARGETS["cmrr_db"]:
            if sym["S_input"] > 0.3:
                out.append("CMRR is degraded mainly by missing or weak input-pair symmetry.")
            if sym["S_in_net"] > 0.2:
                out.append("Input net parasitic imbalance between in_p and in_n contributes to CMRR loss.")
        if sim["pm_deg"] < TARGETS["pm_deg"]:
            C_vout = net_rc["vout"]["c_fF"]
            if C_vout > NET_BASE["vout"]["length_um"] * NET_BASE["vout"]["c_fF_per_um"] * 1.3:
                out.append("Phase margin is reduced by excessive vout parasitic capacitance.")
            if pex["route_fail_risk"] > 0.4:
                out.append("Routing pressure introduces additional parasitic uncertainty and PM degradation.")
        if sim["ugb_mhz"] < TARGETS["ugb_mhz"]:
            out.append("UGB is limited by effective Miller/load capacitance around out2 and vout.")
        if pex["legalization_risk"] > 0.5:
            out.append("Large wire-width multipliers or excessive high-priority nets increase legalization risk.")
        if sim["gain_db"] < TARGETS["gain_db"]:
            out.append("Gain is reduced by mirror-load mismatch, routing congestion, or excessive parasitic loading.")
        return out
