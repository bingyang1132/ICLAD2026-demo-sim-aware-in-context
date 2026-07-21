import pytest
from icpi.action_space import make_params, apply_diff, validate


def test_apply_diff_clamps():
    p = make_params()
    p2 = apply_diff(p, "net_weights", {"out2": 99.0})
    assert p2["net_weights"]["out2"] == 8.0  # clamped to upper bound


def test_apply_diff_no_mutation():
    p = make_params()
    apply_diff(p, "wire_widths", {"vout": 3.0})
    assert p["wire_widths"] == {}  # original unchanged


def test_symmetry_diff_structured():
    p = make_params()
    p2 = apply_diff(p, "symmetry", {
        "pairs": [["M1", "M2"]],
        "self_symmetric": ["M0"],
        "matched_nets": [["in_p", "in_n"]],
    })
    assert p2["symmetry"]["pairs"] == [["M1", "M2"]]
    assert p2["symmetry"]["self_symmetric"] == ["M0"]
    assert p2["symmetry"]["matched_nets"] == [["in_p", "in_n"]]


def test_symmetry_partial_update():
    """Setting only `pairs` keeps previously-set self_symmetric/matched_nets."""
    p = make_params()
    p = apply_diff(p, "symmetry", {"self_symmetric": ["M0", "Cc"]})
    p = apply_diff(p, "symmetry", {"pairs": [["M1", "M2"]]})
    assert p["symmetry"]["self_symmetric"] == ["M0", "Cc"]
    assert p["symmetry"]["pairs"] == [["M1", "M2"]]


def test_symmetry_rejects_bad_pair():
    p = make_params()
    with pytest.raises(ValueError):
        apply_diff(p, "symmetry", {"pairs": [["M1", "M2", "M3"]]})


def test_validate_passes_default():
    p = make_params()
    assert validate(p) == []


def test_validate_catches_invalid_symmetry_type():
    p = make_params()
    p["symmetry"] = "not a dict"
    violations = validate(p)
    assert any("symmetry" in v for v in violations)
