from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import pandas as pd


MONTH_MAP = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def read_csv_with_header_metadata(path: Path) -> Tuple[dict, pd.DataFrame]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    metadata: dict = {}
    data_start = 0

    def uq(s: str) -> str:
        s = s.strip()
        if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
            return s[1:-1]
        return s

    ts_key = re.compile(r"^\d{4}(?:\s+Q[1-4]|\s+M\d{2})?$")
    for idx, line in enumerate(lines):
        raw = line.strip()
        if raw == "":
            data_start = idx + 1
            break
        parts = [p.strip() for p in line.split(",", 1)]
        if len(parts) == 2:
            key, val = uq(parts[0]), uq(parts[1])
            if ts_key.match(key):
                data_start = idx
                break
            metadata[key] = val
            if key.lower().startswith("important notes"):
                data_start = idx + 1
                break
        else:
            data_start = idx
            break

    # Now read the data lines into a simple two-column frame
    data_lines = lines[data_start:]
    records = []
    for ln in data_lines:
        if not ln.strip():
            continue
        parts = [uq(p) for p in ln.split(",", 1)]
        if len(parts) != 2:
            continue
        key, value = parts
        # Keep only monthly observations formatted like 'YYYY MON'
        if re.match(r"^\d{4}\s+[A-Z]{3}$", key):
            year_s, mon_s = key.split()
            year = int(year_s)
            mon = MONTH_MAP.get(mon_s.upper())
            if mon is None:
                continue
            try:
                val = float(value)
            except ValueError:
                continue
            obs_date = datetime(year, mon, 1)
            records.append({
                "observation_date": obs_date,
                "value": val,
            })

    df = pd.DataFrame.from_records(records)
    return metadata, df


def parse_vintage_date(metadata: dict) -> Optional[pd.Timestamp]:
    candidates = ["Release date", "Last updated", "Date"]
    fmts = ["%d %B %Y", "%d %b %Y", "%Y-%m-%d", "%d-%m-%Y"]
    for key in candidates:
        val = metadata.get(key)
        if not val:
            continue
        for fmt in fmts:
            try:
                return pd.to_datetime(datetime.strptime(val, fmt))
            except Exception:
                pass
    return None


def consolidate_monthlies(raw_dir: Path, out_path: Path) -> pd.DataFrame:
    raw_paths = sorted(Path(raw_dir).glob("ap2y_*.csv"))
    frames: List[pd.DataFrame] = []
    for p in raw_paths:
        meta, df = read_csv_with_header_metadata(p)
        if df.empty:
            continue
        vintage = parse_vintage_date(meta)
        df["vintage_date"] = vintage
        df["source_file"] = p.name
        frames.append(df)
    if not frames:
        raise RuntimeError("No monthly data found to consolidate.")
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.dropna(subset=["vintage_date"]).sort_values(["observation_date", "vintage_date"]).reset_index(drop=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out_path, index=False)
    return combined


def main() -> None:
    raw_dir = Path("data") / "raw"
    out_path = Path("data") / "processed" / "ap2y_consolidated.csv"
    df = consolidate_monthlies(raw_dir, out_path)
    print(f"Wrote consolidated dataset with {len(df)} rows to {out_path}")


if __name__ == "__main__":
    main()



