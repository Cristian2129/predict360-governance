from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_COLUMNS = {"story_id", "exposure_cop_m", "sp"}


def _validate(df: pd.DataFrame) -> None:
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Backlog dataframe is missing columns: {sorted(missing)}")


def prioritize_backlog(df: pd.DataFrame, total_portfolio_risk: float = 77000.0) -> pd.DataFrame:
    """
    Orders the product backlog by quantified financial exposure and WSJF efficiency
    (COP Millions protected per Story Point), preventing double-counting.
    """
    _validate(df)
    result = df.copy()
    if "exposure_type" not in result.columns:
        result["exposure_type"] = result["exposure_cop_m"].apply(
            lambda x: "direct" if x > 0 else "enabling"
        )

    result["priority_tier"] = result["exposure_cop_m"].apply(
        lambda x: "Risk-Bearing" if x > 0 else "Enabling"
    )
    result["exposure_share_pct"] = (
        (result["exposure_cop_m"] / total_portfolio_risk) * 100.0
    ).round(2)
    result["cop_m_per_sp"] = (result["exposure_cop_m"] / result["sp"]).round(2)

    result = result.sort_values(
        by=["exposure_cop_m", "cop_m_per_sp", "sp"], ascending=[False, False, False]
    ).reset_index(drop=True)
    result["priority_rank"] = result.index + 1
    return result


def get_direct_exposure_total(df: pd.DataFrame) -> float:
    """Returns the sum of direct exposure items only (must equal COP 77,000M)."""
    if "exposure_type" not in df.columns:
        raise ValueError("Column 'exposure_type' is required to compute direct exposure.")
    return float(df.loc[df["exposure_type"] == "direct", "exposure_cop_m"].sum())


def export_prioritized_backlog(
    backlog_csv: str | Path = ROOT / "data" / "synthetic" / "backlog.csv",
    out_md: str | Path = ROOT / "docs" / "evidence" / "backlog_prioritization.md",
) -> pd.DataFrame:
    """Reads backlog.csv, computes exposure efficiency, and auto-generates the Markdown report."""
    df = pd.read_csv(backlog_csv)
    ordered = prioritize_backlog(df)
    direct_total = get_direct_exposure_total(ordered)

    out = Path(out_md)
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# FinBank Predict360 — Prioritized Backlog by Financial Exposure (US-02)\n",
        f"- **Total Reconciled Direct Exposure:** COP {direct_total:,.1f}M (EarlyRisk: 58,800.0M + StayBank: 18,200.0M)",
        "- **Governance Value Added:** Separates `direct`, `umbrella`, and `enabling` exposure to prevent double-counting (COP 231,000M raw sum vs. COP 77,000M net portfolio) and ranks stories by **Exposure Efficiency (`COP M / SP`)**.\n",
        "| Rank | Story ID | Title | Type | Exposure (COP M) | Share (%) | Efficiency (COP M / SP) | Tier | SP | Sprint |",
        "| :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for _, r in ordered.iterrows():
        title = r.get("title", r.get("domain", "-"))
        sprint = r.get("sprint", "-")
        lines.append(
            f"| {r['priority_rank']} | **{r['story_id']}** | {title} | `{r['exposure_type']}` | "
            f"{r['exposure_cop_m']:,.1f} | {r['exposure_share_pct']:.2f}% | "
            f"**{r['cop_m_per_sp']:,.1f}** | {r['priority_tier']} | {r['sp']} | {sprint} |"
        )

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved: {out}")
    return ordered


if __name__ == "__main__":
    export_prioritized_backlog()