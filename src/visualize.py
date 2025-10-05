from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plot revisions across vintages for a selected month")
    parser.add_argument("--input", type=Path, default=Path("data") / "processed" / "ap2y_consolidated.csv", help="Path to consolidated CSV")
    parser.add_argument("--month", type=str, required=True, help="Observation month in YYYY-MM, e.g. 2022-06")
    parser.add_argument("--out", type=Path, default=Path("reports"), help="Output directory for plots")
    return parser


def load_data(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["observation_date"] = pd.to_datetime(df["observation_date"], errors="coerce")
    df["vintage_date"] = pd.to_datetime(df["vintage_date"], errors="coerce")
    df = df.dropna(subset=["observation_date", "vintage_date", "value"])  # keep valid rows
    return df


def plot_revisions_for_month(df: pd.DataFrame, month_str: str, out_dir: Path) -> Path:
    try:
        target_month = pd.Period(month_str, freq="M")
    except Exception as exc:
        raise ValueError("--month must be in YYYY-MM format") from exc

    mask = df["observation_date"].dt.to_period("M") == target_month
    series = df.loc[mask, ["vintage_date", "value"]].sort_values("vintage_date")
    if series.empty:
        raise RuntimeError(f"No data found for observation month {month_str}")

    out_dir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 5))
    sns.lineplot(ax=ax, data=series, x="vintage_date", y="value", marker="o")

    # Key metrics
    first_dt = pd.to_datetime(series.iloc[0]["vintage_date"])  # type: ignore[index]
    first_val = float(series.iloc[0]["value"])  # type: ignore[index]
    last_dt = pd.to_datetime(series.iloc[-1]["vintage_date"])  # type: ignore[index]
    last_val = float(series.iloc[-1]["value"])  # type: ignore[index]
    vmin = float(series["value"].min())
    vmax = float(series["value"].max())
    vrange = vmax - vmin

    # Largest step change
    ser_with_diff = series.copy()
    ser_with_diff["diff"] = ser_with_diff["value"].diff()
    if ser_with_diff["diff"].abs().max() > 0:
        idx_max = ser_with_diff["diff"].abs().idxmax()
        step_dt = pd.to_datetime(ser_with_diff.loc[idx_max, "vintage_date"])  # type: ignore[index]
        step_val = float(ser_with_diff.loc[idx_max, "value"])  # type: ignore[index]
        step_diff = float(ser_with_diff.loc[idx_max, "diff"])  # type: ignore[index]
        # Draw an arrow from previous point to current
        if idx_max > 0:
            prev_dt = pd.to_datetime(ser_with_diff.loc[idx_max - 1, "vintage_date"])  # type: ignore[index]
            prev_val = float(ser_with_diff.loc[idx_max - 1, "value"])  # type: ignore[index]
            ax.annotate(
                f"Largest step: {step_diff:+.1f}",
                xy=(step_dt, step_val),
                xytext=(step_dt, step_val + (vmax - vmin) * 0.08 if vmax > vmin else step_val + 5),
                arrowprops=dict(arrowstyle="->", color="#d62728", lw=1.2),
                fontsize=9,
                color="#d62728",
            )

    # Highlight first and last points
    ax.scatter([first_dt], [first_val], color="#2ca02c", zorder=5, label="Initial")
    ax.scatter([last_dt], [last_val], color="#ff7f0e", zorder=5, label="Latest")
    ax.annotate(f"Initial: {first_val:.0f}", xy=(first_dt, first_val), xytext=(0, 10), textcoords="offset points", fontsize=9, color="#2ca02c")
    ax.annotate(f"Latest: {last_val:.0f}", xy=(last_dt, last_val), xytext=(0, -15), textcoords="offset points", fontsize=9, color="#ff7f0e")

    # Summary textbox
    summary = f"Range: {vrange:.1f} (min {vmin:.0f}, max {vmax:.0f})"
    ax.text(
        0.01,
        0.99,
        summary,
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=9,
        bbox=dict(boxstyle="round,pad=0.3", facecolor="#f9f9f9", edgecolor="#cccccc"),
    )

    ax.set_title(f"UK Vacancies (AP2Y): Revisions for {month_str}")
    ax.set_xlabel("Vintage (publication date)")
    ax.set_ylabel("Vacancies (thousands)")
    ax.grid(True, linestyle=":", alpha=0.5)
    ax.legend()
    fig.autofmt_xdate()
    out_path = out_dir / f"revisions_{month_str}.png"
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def main(argv: Optional[list[str]] = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    df = load_data(args.input)
    out_path = plot_revisions_for_month(df, args.month, args.out)
    print(f"Saved plot: {out_path}")


if __name__ == "__main__":
    main()


