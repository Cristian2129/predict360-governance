"""US-07: risk & impediment register (probability x impact) mirrored on the Trello board."""
import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTER = ROOT / "data" / "risk_register.csv"
DEFAULT_REVIEWS = ROOT / "data" / "risk_reviews.csv"
EVIDENCE_FILE = ROOT / "docs" / "evidence" / "us07_risk_register.md"
TRELLO_CARDS_FILE = ROOT / "docs" / "evidence" / "us07_trello_cards.md"

REQUIRED_COLUMNS = {
    "risk_id", "type", "category", "description",
    "probability", "impact", "owner", "control", "status",
}
REVIEW_COLUMNS = {"sprint", "risk_id", "reviewed_on", "reviewer", "note"}
LEVELS = {"Low": 1, "Medium": 2, "High": 3}
ACTIVE_STATUSES = {"Open", "Mitigating", "Occurred"}
VALID_STATUSES = ACTIVE_STATUSES | {"Closed"}
VALID_TYPES = {"Risk", "Impediment"}
# AC2: the register must cover these four families.
REQUIRED_CATEGORIES = {"Data quality", "Compliance", "Schedule", "Business adoption"}


def _blank(series: pd.Series) -> pd.Series:
    return series.isna() | series.astype(str).str.strip().eq("")


def validate_register(df: pd.DataFrame) -> None:
    """AC1 + AC2: every row has probability, impact, owner and control; key categories present."""
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Risk register is missing columns: {sorted(missing)}")
    if df.empty:
        raise ValueError("Risk register is empty")
    if df["risk_id"].duplicated().any():
        raise ValueError("Duplicate risk_id values in the register")
    for col in ("owner", "control"):
        if _blank(df[col]).any():
            raise ValueError(f"Every risk needs a non-empty '{col}'")
    for col in ("probability", "impact"):
        if not df[col].isin(LEVELS).all():
            raise ValueError(f"'{col}' must be one of {sorted(LEVELS)}")
    if not df["status"].isin(VALID_STATUSES).all():
        raise ValueError(f"'status' must be one of {sorted(VALID_STATUSES)}")
    if not df["type"].isin(VALID_TYPES).all():
        raise ValueError(f"'type' must be one of {sorted(VALID_TYPES)}")
    absent = REQUIRED_CATEGORIES - set(df["category"])
    if absent:
        raise ValueError(f"Missing required risk categories: {sorted(absent)}")


def score_register(df: pd.DataFrame) -> pd.DataFrame:
    """Adds score (probability x impact, 1-9) and level, sorted from most to least severe."""
    validate_register(df)
    out = df.copy()
    out["score"] = out["probability"].map(LEVELS) * out["impact"].map(LEVELS)
    out["level"] = out["score"].apply(lambda s: "High" if s >= 6 else "Medium" if s >= 3 else "Low")
    return out.sort_values(["score", "risk_id"], ascending=[False, True]).reset_index(drop=True)


def active_risks(df: pd.DataFrame) -> pd.DataFrame:
    """Risks and impediments that must appear on the board (status != Closed)."""
    scored = score_register(df)
    return scored[scored["status"].isin(ACTIVE_STATUSES)].reset_index(drop=True)


def pending_reviews(register: pd.DataFrame, reviews: pd.DataFrame, sprint: int) -> list[str]:
    """AC4: active risk IDs with no review row for this sprint checkpoint."""
    missing = REVIEW_COLUMNS - set(reviews.columns)
    if missing:
        raise ValueError(f"Risk review log is missing columns: {sorted(missing)}")
    reviewed = set(reviews.loc[reviews["sprint"].astype(str) == str(sprint), "risk_id"])
    return [r for r in active_risks(register)["risk_id"] if r not in reviewed]


def export_trello_cards(register: pd.DataFrame, output: str | Path = TRELLO_CARDS_FILE) -> int:
    """AC3: one ready-to-paste card per active risk for the 'Blocked / Risks' list."""
    cards = active_risks(register)
    lines = ["# US-07 — Cards for the Trello `Blocked / Risks` list", "",
             f"{len(cards)} active items, most severe first. One Trello card per block.", ""]
    for _, r in cards.iterrows():
        lines += [
            f"## [{r['risk_id']}] {r['category']} — {r['probability']}/{r['impact']} (score {r['score']})",
            f"- **Label:** {r['type']}, {r['category']}, {r['level']}",
            f"- **Member:** {r['owner']}",
            f"- **Description:** {r['description']}",
            f"- **Control:** {r['control']}",
            f"- **Status:** {r['status']}", "",
        ]
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    return len(cards)


def export_register_report(register: pd.DataFrame, reviews: pd.DataFrame, sprint: int,
                           output: str | Path = EVIDENCE_FILE) -> dict:
    """Evidence file: scored register plus review status for the sprint checkpoint."""
    scored = score_register(register)
    pending = pending_reviews(register, reviews, sprint)
    lines = [
        "# US-07 — Risk & Impediment Register", "",
        f"Checkpoint: Sprint {sprint} | Active items: {len(active_risks(register))}", "",
        "| ID | Type | Category | Prob. | Impact | Score | Owner | Control | Status |",
        "| :---: | :---: | :--- | :---: | :---: | :---: | :--- | :--- | :---: |",
    ]
    for _, r in scored.iterrows():
        lines.append(f"| {r['risk_id']} | {r['type']} | {r['category']} | {r['probability']} | "
                     f"{r['impact']} | {r['score']} | {r['owner']} | {r['control']} | {r['status']} |")
    lines += ["", f"Review status: **{'COMPLETE' if not pending else 'PENDING'}**"]
    if pending:
        lines.append(f"Not yet reviewed in Sprint {sprint}: {', '.join(pending)}")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"sprint": sprint, "active": len(active_risks(register)), "pending": pending}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="US-07 risk register checkpoint")
    parser.add_argument("--sprint", type=int, required=True)
    args = parser.parse_args()
    reg = pd.read_csv(DEFAULT_REGISTER)
    rev = pd.read_csv(DEFAULT_REVIEWS)
    result = export_register_report(reg, rev, args.sprint)
    n = export_trello_cards(reg)
    print(f"Active items: {result['active']} | Trello cards: {n}")
    print(f"Pending review in Sprint {args.sprint}: {result['pending'] or 'none'}")
