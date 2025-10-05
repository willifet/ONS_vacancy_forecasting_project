from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import pandas as pd
import matplotlib.pyplot as plt
from statsmodels.tsa.holtwinters import ExponentialSmoothing


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Forecast UK vacancies using ETS on latest vintage series")
    parser.add_argument("--input", type=Path, default=Path("data") / "processed" / "ap2y_consolidated.csv", help="Consolidated input CSV")
    parser.add_argument("--h", type=int, default=12, help="Forecast horizon in months")
    parser.add_argument("--outdir", type=Path, default=Path("reports"), help="Output directory for forecast plot/CSV")
    return parser


def load_latest_series(path: Path) -> pd.Series:
    df = pd.read_csv(path)
    df["observation_date"] = pd.to_datetime(df["observation_date"], errors="coerce")
    df["vintage_date"] = pd.to_datetime(df["vintage_date"], errors="coerce")
    df = df.dropna(subset=["observation_date", "vintage_date", "value"])  # keep valid

    # For each observation date, take the most recent vintage value
    idx = df.groupby("observation_date")["vintage_date"].idxmax()
    latest = df.loc[idx, ["observation_date", "value"]].sort_values("observation_date")
    series = latest.set_index("observation_date")["value"].asfreq("MS")  # month start
    series = series.interpolate(limit_direction="forward")
    return series


def fit_ets_and_forecast(y: pd.Series, horizon: int) -> tuple[pd.DataFrame, str]:
    # Try multiplicative seasonality first; fall back to additive if needed
    model_type = "ETS(add, mul, add)"
    try:
        model = ExponentialSmoothing(
            y,
            trend="add",
            seasonal="mul",
            seasonal_periods=12,
            initialization_method="estimated",
        ).fit(optimized=True)
    except Exception:
        model_type = "ETS(add, add, add)"
        model = ExponentialSmoothing(
            y,
            trend="add",
            seasonal="add",
            seasonal_periods=12,
            initialization_method="estimated",
        ).fit(optimized=True)

    fcst = model.forecast(horizon)
    df_fcst = fcst.to_frame(name="forecast_value").reset_index().rename(columns={"index": "forecast_date"})
    return df_fcst, model_type


def plot_history_and_forecast(y: pd.Series, df_fcst: pd.DataFrame, out_path: Path, title: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 5))
    y.plot(ax=ax, label="History")
    ax.plot(df_fcst["forecast_date"], df_fcst["forecast_value"], label="Forecast", color="#d62728")
    ax.set_title(title)
    ax.set_ylabel("Vacancies (thousands)")
    ax.grid(True, linestyle=":", alpha=0.5)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main(argv: Optional[list[str]] = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    series = load_latest_series(args.input)
    df_fcst, model_type = fit_ets_and_forecast(series, args.h)

    # Save outputs
    args.outdir.mkdir(parents=True, exist_ok=True)
    csv_path = args.outdir / "forecast_latest.csv"
    df_fcst.assign(model=model_type).to_csv(csv_path, index=False)

    plot_path = args.outdir / "forecast_latest.png"
    plot_history_and_forecast(series, df_fcst, plot_path, f"UK Vacancies Forecast (ETS) – horizon {args.h}")
    print(f"Saved forecast CSV: {csv_path}")
    print(f"Saved forecast plot: {plot_path}")


if __name__ == "__main__":
    main()



