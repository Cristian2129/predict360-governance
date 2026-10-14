from pathlib import Path

import matplotlib
matplotlib.use("Agg")  
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_COLUMNS = {"sprint", "story_id", "story_points", "status", "closed_block"}


def _validate(log_df: pd.DataFrame) -> None:
    missing = REQUIRED_COLUMNS - set(log_df.columns)
    if missing:
        raise ValueError(f"sprint_log is missing columns: {sorted(missing)}")


def calculate_velocity(log_df: pd.DataFrame) -> pd.DataFrame:
    """Computes planned vs. completed Story Points per sprint."""
    _validate(log_df)
    records = []
    for sprint_num, group in log_df.groupby("sprint"):
        planned = float(group["story_points"].sum())
        done_sp = float(group.loc[group["status"] == "Done", "story_points"].sum())
        rate = round((done_sp / planned) * 100.0, 2) if planned > 0 else 0.0
        records.append({
            "sprint": int(sprint_num),
            "planned_sp": planned,
            "completed_sp": done_sp,
            "completion_rate_pct": rate,
        })
    return pd.DataFrame(records)


def get_burndown_series(
    log_df: pd.DataFrame, sprint_num: int, total_blocks: int | None = None
) -> pd.DataFrame:
    """Returns ideal vs. actual remaining SP per block for a sprint."""
    _validate(log_df)
    sub = log_df[log_df["sprint"] == sprint_num]
    planned = float(sub["story_points"].sum())

    if total_blocks is None:
        max_closed = sub["closed_block"].max()
        total_blocks = int(max_closed) if pd.notna(max_closed) and max_closed >= 1 else 1

    rows = []
    for b in range(total_blocks + 1):
        closed_sp = float(sub.loc[sub["closed_block"] <= b, "story_points"].sum())
        rows.append({
            "block": b,
            "timestamp_label": f"Block {b}",
            "ideal_remaining": round(planned * (1 - b / total_blocks), 2),
            "actual_remaining": planned - closed_sp,
        })
    return pd.DataFrame(rows)


def generate_all_charts(
    log_csv: str = str(ROOT / "docs" / "sprint_log.csv"),
    out_dir: str = str(ROOT / "reports" / "figures"),
    total_blocks: int | None = 4,
) -> None:
    """Generates one Burndown chart per sprint and the Velocity comparison chart."""
    df = pd.read_csv(log_csv)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    for s in sorted(df["sprint"].unique()):
        bd = get_burndown_series(df, s, total_blocks)
        plt.figure(figsize=(7, 4))
        plt.plot(bd["timestamp_label"], bd["ideal_remaining"], "--", label="Ideal Remaining (SP)", color="#606671")
        plt.plot(bd["timestamp_label"], bd["actual_remaining"], "-o", linewidth=2, label="Actual Remaining (SP)", color="#1a62ff")
        plt.title(f"FinBank Predict360 — Sprint {s} Burndown Chart")
        plt.xlabel("Sprint Blocks")
        plt.ylabel("Remaining Story Points (SP)")
        plt.grid(True, linestyle=":", alpha=0.6)
        plt.legend()
        plt.tight_layout()
        path = out / f"burndown_sprint{s}.png"
        plt.savefig(path, dpi=150)
        plt.close()
        print(f"Guardado: {path}")

    vel = calculate_velocity(df)
    plt.figure(figsize=(6, 4))
    x = range(len(vel))
    width = 0.35
    plt.bar([i - width / 2 for i in x], vel["planned_sp"], width=width, label="Estimated (Planned) SP", color="#94a3b8")
    plt.bar([i + width / 2 for i in x], vel["completed_sp"], width=width, label="Actual (Completed) SP", color="#008009")
    plt.xticks(list(x), [f"Sprint {s}" for s in vel["sprint"]])
    plt.ylabel("Story Points (SP)")
    plt.title("FinBank Predict360 — Team Velocity (Estimated vs. Actual)")
    plt.legend()
    plt.grid(axis="y", linestyle=":", alpha=0.6)
    plt.tight_layout()
    path = out / "velocity_comparison.png"
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"Guardado: {path}")


if __name__ == "__main__":
    generate_all_charts()

    