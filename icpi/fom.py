"""
FoM formula from paper Section 4.1.
  s_m = v/L        if v < L
      = 1 + (v-L)/v  if v >= L
  alpha_PM = min(v_PM / 60, 1)
  FoM = geometric_mean(s_Gain, s_UGB, s_CMRR) * alpha_PM
"""
import math
from icpi.state import SimResults


def compute_fom(sim: SimResults, targets: dict) -> float:
    """
    targets = {"gain_db": 50, "ugb_mhz": 18, "cmrr_db": 80, "pm_deg": 60}
    Returns FoM, or 0.0 if any required metric is None.
    """
    metrics = {
        "gain_db": sim.gain_db,
        "ugb_mhz": sim.ugb_mhz,
        "cmrr_db": sim.cmrr_db,
        "pm_deg": sim.pm_deg,
    }
    if any(v is None for v in metrics.values()):
        return 0.0

    def score(v: float, L: float) -> float:
        if v < L:
            return v / L
        return 1.0 + (v - L) / v

    scores = [
        score(metrics["gain_db"], targets["gain_db"]),
        score(metrics["ugb_mhz"], targets["ugb_mhz"]),
        score(metrics["cmrr_db"], targets["cmrr_db"]),
    ]
    alpha_pm = min(metrics["pm_deg"] / targets["pm_deg"], 1.0)
    fom = math.exp(sum(math.log(max(s, 1e-9)) for s in scores) / len(scores)) * alpha_pm
    return round(fom, 6)
