"""
LayoutState — synchronized intermediate representation passed to every agent.
Matches the synthetic oracle output (no real geometry).
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class DeviceInfo:
    name: str
    type: str
    stage: str
    nets: list[str]


@dataclass
class NetInfo:
    name: str
    type: str
    devices: list[str]


@dataclass
class ParasiticSummary:
    net_rc: dict[str, dict] = field(default_factory=dict)
    pair_mismatch: dict[str, float] = field(default_factory=dict)
    congestion: float = 0.0
    legalization_risk: float = 0.0
    route_fail_risk: float = 0.0


@dataclass
class SimResults:
    gain_db: Optional[float] = None
    ugb_mhz: Optional[float] = None
    pm_deg: Optional[float] = None
    cmrr_db: Optional[float] = None
    fom: Optional[float] = None
    score: Optional[float] = None     # synthetic 0–100 score
    violations: dict = field(default_factory=dict)
    diagnosis: list[str] = field(default_factory=list)


@dataclass
class LayoutState:
    round_idx: int
    devices: list[DeviceInfo] = field(default_factory=list)
    nets: list[NetInfo] = field(default_factory=list)
    params: dict = field(default_factory=dict)
    parasitics: ParasiticSummary = field(default_factory=ParasiticSummary)
    sim_results: SimResults = field(default_factory=SimResults)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)

    @classmethod
    def from_dict(cls, d: dict) -> "LayoutState":
        devices = [DeviceInfo(**dev) for dev in d.get("devices", [])]
        nets = [NetInfo(**n) for n in d.get("nets", [])]
        parasitics = ParasiticSummary(**d.get("parasitics", {}))
        sim_results = SimResults(**d.get("sim_results", {}))
        return cls(
            round_idx=d["round_idx"],
            devices=devices,
            nets=nets,
            params=d.get("params", {}),
            parasitics=parasitics,
            sim_results=sim_results,
        )

    def compact_summary(self) -> str:
        lines = [f"=== Layout State (round {self.round_idx}) ==="]
        lines.append(
            f"Devices ({len(self.devices)}): "
            + ", ".join(f"{d.name}[{d.type}/{d.stage}]" for d in self.devices)
        )
        lines.append(
            f"Nets ({len(self.nets)}): "
            + ", ".join(f"{n.name}[{n.type}]" for n in self.nets)
        )

        # Current parameters
        lines.append("Active controls:")
        for fam, vals in self.params.items():
            if fam == "symmetry":
                if vals and (vals.get("pairs") or vals.get("self_symmetric") or vals.get("matched_nets")):
                    lines.append(f"  symmetry.pairs:          {vals.get('pairs', [])}")
                    lines.append(f"  symmetry.self_symmetric: {vals.get('self_symmetric', [])}")
                    lines.append(f"  symmetry.matched_nets:   {vals.get('matched_nets', [])}")
            elif vals:
                lines.append(f"  {fam}: " + ", ".join(f"{k}={v}" for k, v in vals.items()))

        # Parasitics summary
        p = self.parasitics
        lines.append("Parasitics:")
        lines.append(
            f"  congestion={p.congestion:.3f}  "
            f"legal_risk={p.legalization_risk:.3f}  "
            f"route_fail_risk={p.route_fail_risk:.3f}"
        )
        lines.append("  Critical net R/C/L:")
        # Show the most important nets first
        priority_nets = ["out2", "vout", "comp_mid", "in_p", "in_n", "out1", "ptail"]
        for n in priority_nets:
            if n in p.net_rc:
                rc = p.net_rc[n]
                lines.append(
                    f"    {n}: R={rc.get('r_ohm', 0):.1f}Ω  "
                    f"C={rc.get('c_fF', 0):.2f}fF  "
                    f"L={rc.get('length_um', 0):.1f}μm"
                )
        if p.pair_mismatch:
            lines.append("  Pair mismatch scores:")
            for k, v in p.pair_mismatch.items():
                lines.append(f"    {k}: {v:.3f}")

        # Sim results
        sr = self.sim_results
        if sr.fom is not None or sr.score is not None:
            lines.append(
                f"Sim: Gain={sr.gain_db}dB  UGB={sr.ugb_mhz}MHz  "
                f"PM={sr.pm_deg}°  CMRR={sr.cmrr_db}dB"
            )
            lines.append(f"  FoM={sr.fom}  score={sr.score}")
            if sr.diagnosis:
                lines.append("  Diagnosis:")
                for d in sr.diagnosis:
                    lines.append(f"    - {d}")
        else:
            lines.append("Sim: not run this round")
        return "\n".join(lines)
