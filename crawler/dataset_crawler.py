"""Collect Bilibili game-highlight metadata and optional sample videos.

The default run collects 15 results for each supported keyword (30 total) and
downloads the first five videos. Use ``--skip-download`` when only refreshing
the metadata file.
"""

from __future__ import annotations

import argparse
import csv
import html
import random
import re
import sys
import time
from datetime import datetime, timezone
from math import ceil
from pathlib import Path
from typing import Any, Iterable

import requests
from requests.adapters import HTTPAdapter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
VIDEO_DIR = DATA_DIR / "videos"
CSV_PATH = DATA_DIR / "dataset_metadata.csv"

SEARCH_API = "https://api.bilibili.com/x/web-interface/search/type"
SUPPORTED_SEARCHES = {
    "LOL 五杀": "LOL",
    "CS GO 五杀": "CS GO",
}
CSV_FIELDS = [
    "id",
    "title",
    "source_url",
    "game_type",
    "tags",
    "download_status",
    "uploader",
    "duration",
    "published_at",
    "play_count",
]
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://search.bilibili.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class CrawlerError(RuntimeError):
    """Raised when a complete dataset cannot be collected."""


def build_session() -> requests.Session:
    """Create a browser-like session with connection-level retries."""
    session = requests.Session()
    session.headers.update(HEADERS)
    adapter = HTTPAdapter(max_retries=2)
    session.mount("https://", adapter)
    return session


def clean_title(value: Any) -> str:
    """Remove Bilibili search highlighting and other HTML markup."""
    text = re.sub(r"<[^>]+>", "", str(value or ""))
    return html.unescape(text).strip()


def normalize_play_count(value: Any) -> str:
    """Keep large numeric counts exact while tolerating API placeholders."""
    if isinstance(value, (int, float)):
        return str(int(value))
    return str(value or "").strip()


def format_publish_time(value: Any) -> str:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone().isoformat(
        timespec="seconds"
    )


def parse_result(item: dict[str, Any], game_type: str) -> dict[str, str]:
    bvid = str(item.get("bvid") or "").strip()
    aid = str(item.get("aid") or "").strip()
    video_id = bvid or (f"av{aid}" if aid else "")
    source_url = str(item.get("arcurl") or "").strip()
    if not source_url and video_id:
        source_url = f"https://www.bilibili.com/video/{video_id}"

    return {
        "id": video_id,
        "title": clean_title(item.get("title")),
        "source_url": source_url,
        "game_type": game_type,
        "tags": f"{game_type},五杀,高光,精彩时刻",
        "download_status": "pending",
        "uploader": clean_title(item.get("author")),
        "duration": str(item.get("duration") or "").strip(),
        "published_at": format_publish_time(item.get("pubdate")),
        "play_count": normalize_play_count(item.get("play")),
    }


def request_search_page(
    session: requests.Session,
    keyword: str,
    page: int,
    max_attempts: int = 4,
) -> list[dict[str, Any]]:
    params = {
        "search_type": "video",
        "keyword": keyword,
        "page": page,
        "page_size": 50,
    }
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = session.get(SEARCH_API, params=params, timeout=(5, 20))
            if response.status_code in {412, 429} or response.status_code >= 500:
                raise CrawlerError(f"HTTP {response.status_code}")
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != 0:
                raise CrawlerError(
                    f"Bilibili API code {payload.get('code')}: {payload.get('message', '')}"
                )
            result = payload.get("data", {}).get("result", [])
            return result if isinstance(result, list) else []
        except (requests.RequestException, ValueError, CrawlerError) as exc:
            last_error = exc
            if attempt < max_attempts:
                delay = min(2**attempt, 12) + random.uniform(0.2, 0.8)
                print(
                    f"[warn] {keyword!r} page {page} failed ({exc}); "
                    f"retrying in {delay:.1f}s",
                    file=sys.stderr,
                )
                time.sleep(delay)

    raise CrawlerError(
        f"failed to request {keyword!r} page {page} after {max_attempts} attempts: "
        f"{last_error}"
    )


def search_bilibili_videos(
    session: requests.Session,
    keyword: str,
    game_type: str,
    target_count: int,
    request_delay: float,
) -> list[dict[str, str]]:
    """Collect unique video records for one keyword."""
    records: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    page = 1

    print(f"[info] collecting {target_count} records for {keyword!r}")
    while len(records) < target_count:
        results = request_search_page(session, keyword, page)
        if not results:
            break

        for item in results:
            record = parse_result(item, game_type)
            if not record["id"] or not record["source_url"]:
                continue
            if record["id"] in seen_ids:
                continue
            seen_ids.add(record["id"])
            records.append(record)
            if len(records) >= target_count:
                break

        print(f"[info] {keyword!r}: {len(records)}/{target_count}")
        page += 1
        if len(records) < target_count:
            time.sleep(request_delay + random.uniform(0.2, 0.8))

    if len(records) < target_count:
        raise CrawlerError(
            f"only collected {len(records)}/{target_count} records for {keyword!r}"
        )
    return records


def write_metadata(records: Iterable[dict[str, str]], csv_path: Path = CSV_PATH) -> None:
    """Atomically replace the CSV so interrupted runs do not corrupt it."""
    rows = list(records)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = csv_path.with_suffix(".csv.tmp")
    with temporary_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary_path.replace(csv_path)


def download_video(record: dict[str, str], video_dir: Path = VIDEO_DIR) -> bool:
    """Download one video as an MP4 file, capped at 1080p."""
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        print(
            "[error] yt-dlp is not installed; run: python -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        return False

    video_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(video_dir / f"{record['game_type'].replace(' ', '_')}_{record['id']}.%(ext)s")
    options = {
        "format": (
            "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/"
            "b[height<=1080][ext=mp4]/best[height<=1080]"
        ),
        "merge_output_format": "mp4",
        "outtmpl": output_template,
        "noplaylist": True,
        "retries": 3,
        "fragment_retries": 3,
        "http_headers": HEADERS,
        "quiet": True,
        "no_warnings": True,
    }
    try:
        with YoutubeDL(options) as downloader:
            downloader.download([record["source_url"]])
        return True
    except Exception as exc:  # yt-dlp raises several extractor-specific errors
        print(f"[error] download failed for {record['id']}: {exc}", file=sys.stderr)
        return False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keyword",
        action="append",
        choices=tuple(SUPPORTED_SEARCHES),
        help="keyword to collect; repeat to select both (default: both)",
    )
    parser.add_argument(
        "--target-per-keyword",
        type=int,
        default=15,
        help="records required for each keyword (default: 15)",
    )
    parser.add_argument(
        "--download-count",
        type=int,
        default=5,
        help="number of sample videos to download, from 5 to 10 (default: 5)",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="collect metadata without downloading videos",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=1.5,
        help="minimum delay between search pages in seconds (default: 1.5)",
    )
    args = parser.parse_args(argv)
    if args.target_per_keyword < 1:
        parser.error("--target-per-keyword must be at least 1")
    if not 5 <= args.download_count <= 10:
        parser.error("--download-count must be between 5 and 10")
    if args.request_delay < 0.5:
        parser.error("--request-delay must be at least 0.5 seconds")
    return args


def run(args: argparse.Namespace) -> int:
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    keywords = args.keyword or list(SUPPORTED_SEARCHES)
    target_per_keyword = max(args.target_per_keyword, ceil(30 / len(keywords)))
    if target_per_keyword != args.target_per_keyword:
        print(
            f"[info] raised per-keyword target to {target_per_keyword} "
            "to satisfy the 30-record minimum"
        )

    all_records: list[dict[str, str]] = []
    with build_session() as session:
        for keyword in keywords:
            records = search_bilibili_videos(
                session=session,
                keyword=keyword,
                game_type=SUPPORTED_SEARCHES[keyword],
                target_count=target_per_keyword,
                request_delay=args.request_delay,
            )
            all_records.extend(records)

    # Persist the complete metadata before potentially long downloads begin.
    write_metadata(all_records)
    print(f"[info] wrote {len(all_records)} records to {CSV_PATH}")

    if args.skip_download:
        for record in all_records:
            record["download_status"] = "skipped"
        write_metadata(all_records)
        return 0

    for index, record in enumerate(all_records[: args.download_count], start=1):
        print(f"[info] downloading {index}/{args.download_count}: {record['title']}")
        record["download_status"] = "downloaded" if download_video(record) else "failed"
        write_metadata(all_records)
        time.sleep(random.uniform(1.0, 2.0))

    print(f"[info] videos saved under {VIDEO_DIR}")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return run(parse_args(argv))
    except (CrawlerError, OSError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
