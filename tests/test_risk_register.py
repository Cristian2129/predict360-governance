"""Tests for US-07 (first RED, then GREEN)."""
import pandas as pd
import pytest

from src.predict360.risk_register import (
    active_risks, export_register_report, export_trello_cards,
    pending_reviews, score_register, validate_register,
)


def _row(rid="R-01", cat="Data quality", p="High", i="High", owner="Paula Gacha",
         control="Early validation", status="Open", typ="Risk"):
    return {"risk_id": rid, "type": typ, "category": cat, "description": "d",
            "probability": p, "impact": i, "owner": owner, "control": control, "status": status}


def _register():
    return pd.DataFrame([
        _row("R-01", "Data quality", "High", "High"),
        _row("R-02", "Schedule", "High", "High"),
        _row("R-04", "Compliance", "Low", "High"),
        _row("R-05", "Business adoption", "Low", "Low", status="Closed"),
    ])


def _reviews(rows=()):
    return pd.DataFrame(rows, columns=["sprint", "risk_id", "reviewed_on", "reviewer", "note"])


def test_score_is_probability_times_impact():
    s = score_register(_register()).set_index("risk_id")
    assert s.loc["R-01", "score"] == 9
    assert s.loc["R-04", "score"] == 3
    assert s.loc["R-05", "score"] == 1


def test_register_requires_owner_and_control():
    df = _register()
    df.loc[0, "owner"] = ""
    with pytest.raises(ValueError):
        validate_register(df)


def test_register_requires_the_four_risk_families():
    with pytest.raises(ValueError):
        validate_register(_register().iloc[:2])  # no Compliance / Business adoption


def test_invalid_probability_raises():
    df = _register()
    df.loc[0, "probability"] = "Huge"
    with pytest.raises(ValueError):
        validate_register(df)


def test_closed_risks_are_not_active():
    ids = list(active_risks(_register())["risk_id"])
    assert "R-05" not in ids and ids[0] in {"R-01", "R-02"}


def test_pending_reviews_lists_unreviewed_active_risks():
    rev = _reviews([(1, "R-01", "2026-10-20", "Marco Jimenez", "ok")])
    assert pending_reviews(_register(), rev, sprint=1) == ["R-02", "R-04"]


def test_review_is_per_sprint():
    rev = _reviews([(1, "R-01", "2026-10-20", "Marco Jimenez", "ok")])
    assert "R-01" in pending_reviews(_register(), rev, sprint=2)


def test_evidence_and_cards_are_exported(tmp_path):
    md, cards = tmp_path / "r.md", tmp_path / "c.md"
    assert export_trello_cards(_register(), cards) == 3
    result = export_register_report(_register(), _reviews(), 1, md)
    assert result["pending"] == ["R-01", "R-02", "R-04"]
    assert "[R-01]" in cards.read_text(encoding="utf-8")
    assert "PENDING" in md.read_text(encoding="utf-8")
