
from __future__ import annotations

import argparse
import itertools
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from time import sleep


ONS_BASE = "https://www.ons.gov.uk"
PREVIOUS_URL = (
    "https://www.ons.gov.uk/employmentandlabourmarket/peopleinwork/"
"employmentandemployeetypes/timeseries/ap2y/lms/previous"
)


@dataclass(frozen=True)
class CsvLink:
    url: str
    uri: str
    version_label: str  # e.g., v117 or latest


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "ONS-AP2Y-Downloader/1.0 (+https://www.ons.gov.uk/) "
                "DataScienceTakeHome"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    return session


def http_get_with_retries(
    session: requests.Session,
    url: str,
    timeout: int = 30,
    max_retries: int = 5,
    base_delay_sec: float = 1.5,
) -> requests.Response:
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            resp = session.get(url, timeout=timeout)
            if resp.status_code == 429:
                # Respect Retry-After if present
                retry_after = resp.headers.get("Retry-After")
                if retry_after is not None:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        delay = base_delay_sec * (2 ** attempt)
                else:
                    delay = base_delay_sec * (2 ** attempt)
                sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            # Backoff on network/server errors
            delay = base_delay_sec * (2 ** attempt)
            sleep(delay)
    if last_exc:
        raise last_exc
    raise RuntimeError("HTTP request failed with unknown error")


def fetch_html(url: str, timeout: int = 30, session: Optional[requests.Session] = None) -> str:
    sess = session or build_session()
    response = http_get_with_retries(sess, url, timeout=timeout)
    return response.text


def find_generator_csv_links(html: str) -> List[CsvLink]:
    """Parse all CSV generator links present on the page.

    The ONS page includes links of the form:
    /generator?format=csv&uri=/employmentandlabourmarket/.../previous/v117
    and also the latest version without the /previous/vXXX suffix.
    """
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href.startswith("/generator?format=csv&uri="):
            continue
        abs_url = ONS_BASE + href
        # Extract the uri param value for de-duplication and labeling
        m = re.search(r"uri=([^#&]+)", href)
        uri = requests.utils.unquote(m.group(1)) if m else href

        # Determine version label
        version_match = re.search(r"/previous/(v\d+)$", uri)
        version_label = version_match.group(1) if version_match else "latest"
        links.append(CsvLink(url=abs_url, uri=uri, version_label=version_label))

    # De-duplicate by uri preserving order
    unique = []
    seen = set()
    for link in links:
        if link.uri in seen:
            continue
        unique.append(link)
        seen.add(link.uri)
    return unique


def download_text(url: str, timeout: int = 60, session: Optional[requests.Session] = None) -> str:
    sess = session or build_session()
    # CSV preference
    sess.headers.update({"Accept": "text/csv,application/octet-stream;q=0.9,*/*;q=0.8"})
    response = http_get_with_retries(sess, url, timeout=timeout)
    response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def extract_metadata_from_csv_text(csv_text: str) -> Tuple[dict, str]:
    """Extract simple header metadata and return (metadata_dict, data_csv_text).

    ONS CSVs often start with key,value metadata lines until a blank line.
    We split the metadata and return the remainder as the data CSV.
    """
    lines = csv_text.splitlines()
    metadata: dict = {}
    data_start_idx = 0
    def strip_quotes(text: str) -> str:
        t = text.strip()
        if len(t) >= 2 and t[0] == '"' and t[-1] == '"':
            return t[1:-1]
        return t

    time_series_key_pattern = re.compile(r"^\d{4}(?:\s+Q[1-4]|\s+M\d{2})?$")

    for idx, line in enumerate(lines):
        raw = line.strip()
        if raw == "":
            data_start_idx = idx + 1
            break
        parts = [p.strip() for p in line.split(",", 1)]
        if len(parts) == 2:
            key = strip_quotes(parts[0])
            value = strip_quotes(parts[1])
            # If we hit the time series, stop header parsing and start data here
            if time_series_key_pattern.match(key):
                data_start_idx = idx
                break
            metadata[key] = value
            # Common ONS marker line; next line is typically data
            if key.lower().startswith("important notes"):
                data_start_idx = idx + 1
                break
        else:
            data_start_idx = idx
            break
    data_csv_text = "\n".join(lines[data_start_idx:])
    return metadata, data_csv_text


def parse_vintage_date(metadata: dict) -> Optional[datetime]:
    """Attempt to parse a vintage date from header metadata.

    Tries common fields observed in ONS generator CSVs.
    """
    candidate_keys = [
        "Last updated",
        "Release date",
        "Date",
    ]
    for key in candidate_keys:
        value = metadata.get(key)
        if not value:
            continue
        for fmt in ("%d %B %Y", "%d %b %Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(value, fmt)
            except Exception:
                continue
    return None


def sanitize_filename(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", text)


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def download_n_csvs(n: int, out_dir: Path, order: str = "recent") -> List[Path]:
    if n < 1:
        raise ValueError("n must be >= 1")
    ensure_directory(out_dir)

    session = build_session()
    html = fetch_html(PREVIOUS_URL, session=session)
    links = find_generator_csv_links(html)
    if not links:
        raise RuntimeError("No CSV links found on the ONS page.")

    # Prefer the latest first, then previous versions in the order they appear
    # Ordering strategy
    if order not in {"recent", "oldest"}:
        raise ValueError("order must be 'recent' or 'oldest'")

    def version_num(l: CsvLink) -> int:
        if l.version_label.startswith("v"):
            try:
                return int(l.version_label[1:])
            except Exception:
                return -1
        return -1

    if order == "recent":
        # latest first, then highest version number to lowest (most recent previous → older)
        links_sorted = sorted(
            links,
            key=lambda l: (0 if l.version_label == "latest" else 1, -version_num(l)),
        )
    else:
        # oldest: latest first, then lowest version upwards (legacy behavior)
        links_sorted = sorted(
            links,
            key=lambda l: (0 if l.version_label == "latest" else 1, version_num(l)),
        )

    saved_paths: List[Path] = []
    for link in itertools.islice(links_sorted, 0, n):
        csv_text = download_text(link.url, session=session)
        metadata, _ = extract_metadata_from_csv_text(csv_text)
        vintage_dt = parse_vintage_date(metadata)
        vintage_str = vintage_dt.strftime("%Y-%m-%d") if vintage_dt else "unknown"
        filename = f"ap2y_{sanitize_filename(link.version_label)}_{vintage_str}.csv"
        out_path = out_dir / filename
        out_path.write_text(csv_text, encoding="utf-8")
        saved_paths.append(out_path)
        print(f"Saved {out_path.name} (vintage={vintage_str})")
        # Polite pause between downloads
        sleep(1.25)

    return saved_paths


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download ONS AP2Y vacancy CSV vintages")
    parser.add_argument(
        "--n",
        type=int,
        default=25,
        help="Number of CSV files to download (includes latest)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data") / "raw",
        help="Directory to save downloaded CSVs",
    )
    parser.add_argument(
        "--order",
        type=str,
        choices=["recent", "oldest"],
        default="recent",
        help="Download order after latest: recent (descending versions) or oldest (ascending)",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    paths = download_n_csvs(n=args.n, out_dir=args.out, order=args.order)
    print(f"Downloaded {len(paths)} files to {args.out}")


if __name__ == "__main__":
    main()


