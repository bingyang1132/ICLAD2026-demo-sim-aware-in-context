import tempfile
from pathlib import Path
from icpi.journal import DesignJournal, JournalEntry


def _make_entry(round_idx, family, fom_after=None):
    return JournalEntry(
        round_idx=round_idx,
        family=family,
        goals="test goal",
        diff={"key": 1.0},
        outcome_summary="ok",
        reflection="test reflection",
        fom_before=0.9,
        fom_after=fom_after,
    )


def test_append_and_reload():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "journal.jsonl"
        j = DesignJournal(path)
        j.append(_make_entry(1, "symmetry", fom_after=1.0))
        j.append(_make_entry(2, "net_weights", fom_after=1.05))

        j2 = DesignJournal(path)
        assert len(j2.entries) == 2
        assert j2.entries[0].family == "symmetry"
        assert j2.entries[1].fom_after == 1.05


def test_retrieve_same_family_first():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "journal.jsonl"
        j = DesignJournal(path)
        for i in range(3):
            j.append(_make_entry(i, "net_weights"))
        j.append(_make_entry(3, "symmetry"))
        j.append(_make_entry(4, "wire_widths"))

        result = j.retrieve("symmetry", top_k=3)
        families = [e.family for e in result]
        assert "symmetry" in families


def test_context_str_not_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "journal.jsonl"
        j = DesignJournal(path)
        j.append(_make_entry(1, "symmetry", fom_after=1.1))
        ctx = j.to_context_str("symmetry")
        assert "symmetry" in ctx
        assert "Round 1" in ctx
