from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # backend sin ventana; debe ir antes de importar pyplot
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # backend sin ventana; debe ir antes de importar pyplot
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

ROOT = Path(__file__).resolve().parents[2]

def calculate_velocity(log_df: pd.DataFrame) -> pd.DataFrame:
    """Computes planned vs. completed Story Points per sprint."""
    records = []
    for sprint_num, group in log_df.groupby("sprint"):
        start = group.loc[group["block"] == 0, "actual_remaining"]
        if start.empty:
            raise ValueError(f"Sprint {sprint_num}: missing block 0 row (planned SP).")
        planned = float(start.iloc[0])

        stories = (
            group[group["story_id"] != "NONE"]
            .sort_values("block")
            .drop_duplicates("story_id", keep="last")
        )
        done_sp = float(stories.loc[stories["status"] == "Done", "story_points"].sum())

        rate = round((done_sp / planned) * 100.0, 2) if planned > 0 else 0.0
        records.append({
            "sprint": int(sprint_num),
            "planned_sp": planned,
            "completed_sp": done_sp,
            "completion_rate_pct": rate,
        })
    return pd.DataFrame(records)


def get_burndown_series(log_df: pd.DataFrame, sprint_num: int) -> pd.DataFrame:
    """Returns ordered burndown checkpoints for a specific sprint."""
    sub = log_df[log_df["sprint"] == sprint_num].sort_values("block").copy()
    return sub[["block", "timestamp_label", "ideal_remaining", "actual_remaining"]].reset_index(drop=True)


def generate_all_charts(log_csv: str = str(ROOT / "docs" / "sprint_log.csv"),out_dir: str = str(ROOT / "reports" / "figures"),) -> None:
    """Generates Sprint 1 & 2 Burndown charts and the Velocity comparison chart."""
    df = pd.read_csv(log_csv)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    for s in sorted(df["sprint"].unique()):
        bd = get_burndown_series(df, s)
        plt.figure(figsize=(7, 4))
        plt.plot(bd["timestamp_label"], bd["ideal_remaining"], "--", label="Ideal Remaining (SP)", color="#606671")
        plt.plot(bd["timestamp_label"], bd["actual_remaining"], "-o", linewidth=2, label="Actual Remaining (SP)", color="#1a62ff")
        plt.title(f"FinBank Predict360 — Sprint {s} Burndown Chart")
        plt.xlabel("Sprint Checkpoints")
        plt.ylabel("Remaining Story Points (SP)")
        plt.xticks(rotation=20, ha="right")
        plt.grid(True, linestyle=":", alpha=0.6)
        plt.legend()
        plt.tight_layout()
        plt.savefig(out / f"burndown_sprint{s}.png", dpi=150)
        plt.close()

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
    plt.savefig(out / "velocity_comparison.png", dpi=150)
    plt.close()


if __name__ == "__main__":
    generate_all_charts()