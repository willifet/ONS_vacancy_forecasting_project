from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze revision patterns over time")
    parser.add_argument("--input", type=Path, default=Path("data") / "processed" / "ap2y_consolidated.csv", help="Consolidated CSV path")
    parser.add_argument("--outdir", type=Path, default=Path("reports"), help="Output directory for figures and summaries")
    return parser


def load_panel(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["observation_date"] = pd.to_datetime(df["observation_date"], errors="coerce")
    df["vintage_date"] = pd.to_datetime(df["vintage_date"], errors="coerce")
    df = df.dropna(subset=["observation_date", "vintage_date", "value"]).copy()
    df["value"] = df["value"].astype(float)
    return df


def add_revision_metrics(df: pd.DataFrame) -> pd.DataFrame:
    # First available value per observation month
    idx_first = df.groupby("observation_date")["vintage_date"].idxmin()
    first_values = df.loc[idx_first, ["observation_date", "value"]].rename(columns={"value": "first_value"})
    df = df.merge(first_values, on="observation_date", how="left")
    df["rev_from_first"] = df["value"] - df["first_value"]

    # Vintage age in months: use Period arithmetic (robust across pandas versions)
    obs_period = df["observation_date"].dt.to_period("M")
    vint_period = df["vintage_date"].dt.to_period("M")
    df["vintage_age_months"] = (vint_period - obs_period).apply(lambda x: x.n)
    # Keep non-negative ages
    df = df[df["vintage_age_months"] >= 0].copy()
    return df


def summarize_by_age(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("vintage_age_months")
    summary = g["rev_from_first"].agg(
        count="count",
        mean_revision="mean",
        mean_abs_revision=lambda s: s.abs().mean(),
        median_abs_revision=lambda s: s.abs().median(),
        p90_abs_revision=lambda s: s.abs().quantile(0.9),
    ).reset_index()
    return summary.sort_values("vintage_age_months")


def plot_summary(summary: pd.DataFrame, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 5))
    sns.lineplot(ax=ax, data=summary, x="vintage_age_months", y="mean_abs_revision", marker="o", label="Mean |revision|")
    sns.lineplot(ax=ax, data=summary, x="vintage_age_months", y="median_abs_revision", marker="o", label="Median |revision|")
    ax.set_title("Revision patterns vs vintage age (months since observation)")
    ax.set_xlabel("Vintage age (months since observation month)")
    ax.set_ylabel("Absolute revision from first estimate (thousands)")
    ax.grid(True, linestyle=":", alpha=0.5)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main(argv: Optional[list[str]] = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    df = load_panel(args.input)
    df = add_revision_metrics(df)
    summary = summarize_by_age(df)

    # Save summary CSV
    args.outdir.mkdir(parents=True, exist_ok=True)
    summary_csv = args.outdir / "revision_patterns_summary.csv"
    summary.to_csv(summary_csv, index=False)

    # Plot summary
    fig_path = args.outdir / "revision_patterns_mean_abs_by_vintage_age.png"
    plot_summary(summary, fig_path)
    print(f"Saved: {summary_csv}")
    print(f"Saved: {fig_path}")


if __name__ == "__main__":
    main()


