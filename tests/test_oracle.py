"""
Verify the SyntheticOTAOracle behaves consistently with SYNTHETIC_ENVIROMENT.md
section 12 expectations:
  - default controls produce a moderate score with low gain/CMRR
  - good controls beat default on CMRR / score / FoM
  - bad controls (knobs maxed) produce high risks and low score
"""
from icpi.tools.oracle import SyntheticOTAOracle

DEFAULT_CONTROLS: dict = {
    "net_weights": {}, "placement_bias": {}, "symmetry": {},
    "routing_priority": {}, "wire_widths": {},
}

GOOD_CONTROLS: dict = {
    "net_weights": {"out2": 3.0, "vout": 2.5, "in_p": 2.0, "in_n": 2.0, "comp_mid": 2.0},
    "placement_bias": {
        "M1": -0.3, "M2": 0.3, "M3": -0.25, "M4": 0.25,
        "M0": 0.0, "M6": 0.4, "M7": 0.4, "Cc": 0.2, "Rc": 0.3,
    },
    "symmetry": {
        "pairs": [["M1", "M2"], ["M3", "M4"]],
        "self_symmetric": ["M0", "Cc"],
        "matched_nets": [["in_p", "in_n"], ["out1", "out2"]],
    },
    "routing_priority": {"out2": 2.5, "vout": 2.5, "comp_mid": 2.0, "in_p": 1.5, "in_n": 1.5},
    "wire_widths": {
        "VDD": 4.0, "GND": 4.0, "vout": 3.0, "out2": 2.0,
        "comp_mid": 1.5, "in_p": 1.5, "in_n": 1.5,
    },
}

BAD_CONTROLS: dict = {
    "net_weights": {"out2": 8.0, "vout": 8.0, "in_p": 8.0, "in_n": 8.0, "ptail": 8.0},
    "routing_priority": {"out2": 4.0, "vout": 4.0, "in_p": 4.0, "in_n": 4.0},
    "wire_widths": {"vout": 6.0, "out2": 6.0, "in_p": 6.0, "in_n": 6.0},
    "symmetry": {},
}


def _oracle():
    return SyntheticOTAOracle(seed=0, deterministic=True)


def test_default_controls_in_expected_range():
    r = _oracle().evaluate(DEFAULT_CONTROLS)
    sim = r["sim"]
    # SYNTHETIC_ENVIROMENT.md section 12.1 expectations
    assert 35 <= sim["gain_db"] <= 55, f"gain={sim['gain_db']}"
    assert 12 <= sim["ugb_mhz"] <= 25, f"ugb={sim['ugb_mhz']}"
    assert 40 <= sim["pm_deg"] <= 75, f"pm={sim['pm_deg']}"
    assert 45 <= sim["cmrr_db"] <= 70, f"cmrr={sim['cmrr_db']}"


def test_good_controls_beat_default():
    o = _oracle()
    base = o.evaluate(DEFAULT_CONTROLS)
    good = o.evaluate(GOOD_CONTROLS)
    assert good["sim"]["cmrr_db"] > base["sim"]["cmrr_db"], "good should raise CMRR"
    assert good["score"] > base["score"], "good should raise score"


def test_bad_controls_raise_risks():
    o = _oracle()
    bad = o.evaluate(BAD_CONTROLS)
    assert bad["pex"]["legalization_risk"] > 0.4, (
        f"bad should drive legalization risk up: {bad['pex']['legalization_risk']}"
    )
    assert bad["pex"]["route_fail_risk"] > 0.3
    base = o.evaluate(DEFAULT_CONTROLS)
    assert bad["score"] < base["score"], "blindly maxing knobs should hurt score"


def test_pex_has_required_fields():
    r = _oracle().evaluate(DEFAULT_CONTROLS)
    assert set(r["pex"].keys()) >= {
        "net_rc", "pair_mismatch", "congestion",
        "legalization_risk", "route_fail_risk",
    }
    for n in ("out2", "vout", "in_p", "comp_mid"):
        assert n in r["pex"]["net_rc"]
        assert "r_ohm" in r["pex"]["net_rc"][n]


def test_symmetry_declaration_helps_cmrr():
    """Declaring M1/M2 + in_p/in_n matched should dramatically improve CMRR."""
    o = _oracle()
    no_sym = o.evaluate(DEFAULT_CONTROLS)
    with_sym = o.evaluate({
        **DEFAULT_CONTROLS,
        "symmetry": {
            "pairs": [["M1", "M2"]],
            "self_symmetric": [],
            "matched_nets": [["in_p", "in_n"]],
        },
    })
    assert with_sym["sim"]["cmrr_db"] > no_sym["sim"]["cmrr_db"] + 10


def test_diagnosis_explains_missing_symmetry():
    """Default config has no symmetry — diagnosis should call it out."""
    r = _oracle().evaluate(DEFAULT_CONTROLS)
    assert any("symmetry" in d.lower() or "cmrr" in d.lower() for d in r["diagnosis"])
