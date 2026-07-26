"""Collect validated game-highlight screenshots from Baidu Images.

By default, the crawler downloads 100 images for each supported search term,
normalizes them to JPEG, and records successful downloads in
``data_acquisition/dataset_images_metadata.csv``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import random
import sys
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import requests
from PIL import Image, ImageOps, UnidentifiedImageError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ACQUISITION_DIR = PROJECT_ROOT / "data_acquisition"
RAW_IMAGE_DIR = ACQUISITION_DIR / "raw_images"
CSV_PATH = ACQUISITION_DIR / "dataset_images_metadata.csv"

SEARCH_API = "https://image.baidu.com/search/acjson"
SUPPORTED_SEARCHES = {
    "LOL 五杀 游戏截图": "LOL",
    "CSGO 击杀信息 游戏截图": "CSGO",
}
CSV_FIELDS = [
    "image_id",
    "keyword",
    "image_url",
    "local_path",
    "fetch_time",
    "game_type",
]
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://image.baidu.com/",
}


class ImageCrawlerError(RuntimeError):
    """Raised when the requested dataset cannot be completed."""


def build_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=2,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session = requests.Session()
    session.headers.update(HEADERS)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def is_http_url(value: Any) -> bool:
    try:
        parsed = urlparse(str(value))
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def candidate_urls(item: dict[str, Any]) -> list[str]:
    """Return original-size URLs first and Baidu thumbnails last."""
    values: list[Any] = [item.get("objURL")]
    replacements = item.get("replaceUrl") or []
    if isinstance(replacements, list):
        for replacement in replacements:
            if isinstance(replacement, dict):
                values.append(replacement.get("ObjURL"))
    values.extend(
        item.get(key)
        for key in ("hoverURL", "middleURL", "thumbURL", "imageUrl")
    )

    result: list[str] = []
    for value in values:
        url = str(value or "").strip()
        if is_http_url(url) and url not in result:
            result.append(url)
    return result


def fetch_search_page(
    session: requests.Session,
    keyword: str,
    page: int,
    page_size: int,
    timeout: float,
) -> list[dict[str, Any]]:
    landing_params = {"tn": "baiduimage", "word": keyword}
    if page == 0:
        landing = session.get(
            "https://image.baidu.com/search/index",
            params=landing_params,
            headers={"Accept": "text/html,application/xhtml+xml"},
            timeout=(5, timeout),
        )
        landing.raise_for_status()
        referer = landing.url
    else:
        prepared = requests.Request(
            "GET", "https://image.baidu.com/search/index", params=landing_params
        ).prepare()
        referer = prepared.url

    params = {
        "tn": "resultjson_com",
        "ipn": "rj",
        "ct": "201326592",
        "is": "",
        "fp": "result",
        "fr": "",
        "queryWord": keyword,
        "word": keyword,
        "cl": "2",
        "lm": "-1",
        "pn": page * page_size,
        "rn": page_size,
        "ie": "utf-8",
        "oe": "utf-8",
        "adpicid": "",
        "st": "-1",
        "z": "",
        "ic": "0",
        "hd": "",
        "latest": "",
        "copyright": "",
        "face": "0",
        "istype": "2",
        "nc": "1",
        "gsm": "1e",
    }
    response = session.get(
        SEARCH_API,
        params=params,
        headers={
            "Accept": "application/json, text/plain, */*",
            "Referer": referer,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        },
        timeout=(5, timeout),
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("antiFlag") or payload.get("message") == "Forbid spider access":
        raise ImageCrawlerError("Baidu Images rejected the search session")
    results = payload.get("data", [])
    if not isinstance(results, list):
        raise ImageCrawlerError("Baidu Images returned an invalid data field")
    return [item for item in results if isinstance(item, dict)]


def fetch_image_bytes(
    session: requests.Session,
    url: str,
    timeout: float,
    max_bytes: int,
) -> bytes:
    """Download an image with timeout and response-size protections."""
    with session.get(
        url,
        headers={
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": "https://image.baidu.com/",
        },
        timeout=(5, timeout),
        stream=True,
    ) as response:
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").lower()
        if content_type and not content_type.startswith("image/"):
            raise ImageCrawlerError(f"unexpected Content-Type: {content_type}")

        try:
            declared_size = int(response.headers.get("Content-Length") or 0)
        except ValueError:
            declared_size = 0
        if declared_size > max_bytes:
            raise ImageCrawlerError(f"image is larger than {max_bytes} bytes")

        chunks: list[bytes] = []
        received = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            received += len(chunk)
            if received > max_bytes:
                raise ImageCrawlerError(f"image exceeded {max_bytes} bytes")
            chunks.append(chunk)

    content = b"".join(chunks)
    if not content:
        raise ImageCrawlerError("download returned an empty file")
    return content


def normalize_and_save_image(
    content: bytes,
    destination: Path,
    min_width: int,
    min_height: int,
) -> None:
    """Decode, validate, and normalize one source image as RGB JPEG."""
    temporary = destination.with_suffix(".jpg.part")
    try:
        with Image.open(BytesIO(content)) as source:
            source.load()
            image = ImageOps.exif_transpose(source)
            width, height = image.size
            if width < min_width or height < min_height:
                raise ImageCrawlerError(
                    f"image is too small ({width}x{height}); "
                    f"minimum is {min_width}x{min_height}"
                )
            aspect_ratio = width / height
            if not 1.2 <= aspect_ratio <= 2.4:
                raise ImageCrawlerError(
                    f"image aspect ratio {aspect_ratio:.2f} is not screenshot-like"
                )
            if image.mode in {"RGBA", "LA"}:
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")

            destination.parent.mkdir(parents=True, exist_ok=True)
            image.save(temporary, format="JPEG", quality=92, optimize=True)
        if not temporary.exists() or temporary.stat().st_size == 0:
            raise ImageCrawlerError("image encoder produced an empty file")
        temporary.replace(destination)
    except (
        OSError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
    ) as exc:
        raise ImageCrawlerError(f"invalid image data: {exc}") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def write_metadata(
    records: Iterable[dict[str, str]], csv_path: Path = CSV_PATH
) -> None:
    rows = list(records)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = csv_path.with_suffix(".csv.tmp")
    try:
        with temporary.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(csv_path)
    except OSError as exc:
        raise ImageCrawlerError(f"failed to write metadata: {exc}") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def load_existing_metadata(csv_path: Path = CSV_PATH) -> list[dict[str, str]]:
    if not csv_path.exists():
        return []
    try:
        with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except (OSError, csv.Error) as exc:
        raise ImageCrawlerError(f"failed to read existing metadata: {exc}") from exc


def record_is_usable(record: dict[str, str]) -> bool:
    local_path = record.get("local_path", "")
    if not local_path:
        return False
    path = PROJECT_ROOT / Path(local_path)
    return path.is_file() and path.stat().st_size > 0


def collect_keyword(
    session: requests.Session,
    keyword: str,
    game_type: str,
    target_count: int,
    records: list[dict[str, str]],
    attempted_urls: set[str],
    content_hashes: set[str],
    args: argparse.Namespace,
) -> None:
    existing_count = sum(
        record.get("keyword") == keyword and record_is_usable(record)
        for record in records
    )
    print(f"[info] {keyword!r}: resuming at {existing_count}/{target_count}")

    for page in range(args.max_pages):
        if existing_count >= target_count:
            return
        try:
            items = fetch_search_page(
                session, keyword, page, args.page_size, args.timeout
            )
        except (requests.RequestException, ValueError, ImageCrawlerError) as exc:
            print(f"[warn] search page {page + 1} failed: {exc}", file=sys.stderr)
            time.sleep(args.request_delay + random.uniform(0.3, 1.0))
            continue
        if not items:
            break

        for item in items:
            if existing_count >= target_count:
                return
            for image_url in candidate_urls(item):
                if image_url in attempted_urls:
                    continue
                attempted_urls.add(image_url)
                try:
                    content = fetch_image_bytes(
                        session, image_url, args.timeout, args.max_image_mb * 1024 * 1024
                    )
                    digest = hashlib.sha256(content).hexdigest()
                    digest_key = digest[:16]
                    if digest_key in content_hashes:
                        continue
                    image_id = f"{game_type.lower()}_{digest_key}"
                    destination = RAW_IMAGE_DIR / game_type.lower() / f"{image_id}.jpg"
                    normalize_and_save_image(
                        content, destination, args.min_width, args.min_height
                    )
                    relative_path = destination.relative_to(PROJECT_ROOT).as_posix()
                    records.append(
                        {
                            "image_id": image_id,
                            "keyword": keyword,
                            "image_url": image_url,
                            "local_path": relative_path,
                            "fetch_time": datetime.now().astimezone().isoformat(
                                timespec="seconds"
                            ),
                            "game_type": game_type,
                        }
                    )
                    content_hashes.add(digest_key)
                    existing_count += 1
                    write_metadata(records)
                    print(f"[info] {keyword!r}: {existing_count}/{target_count}")
                    break
                except (requests.RequestException, ImageCrawlerError, OSError) as exc:
                    print(f"[skip] {image_url}: {exc}", file=sys.stderr)

        if existing_count < target_count:
            time.sleep(args.request_delay + random.uniform(0.3, 1.0))

    if existing_count < target_count:
        raise ImageCrawlerError(
            f"only collected {existing_count}/{target_count} images for {keyword!r}; "
            "increase --max-pages or relax the minimum dimensions"
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keyword",
        action="append",
        choices=tuple(SUPPORTED_SEARCHES),
        help="keyword to collect; repeat for both (default: both)",
    )
    parser.add_argument("--target-per-keyword", type=int, default=100)
    parser.add_argument("--page-size", type=int, default=30)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--request-delay", type=float, default=1.0)
    parser.add_argument("--min-width", type=int, default=640)
    parser.add_argument("--min-height", type=int, default=360)
    parser.add_argument("--max-image-mb", type=int, default=20)
    args = parser.parse_args(argv)

    if args.target_per_keyword < 30:
        parser.error("--target-per-keyword must be at least 30")
    if not 1 <= args.page_size <= 30:
        parser.error("--page-size must be between 1 and 30")
    if args.max_pages < 1:
        parser.error("--max-pages must be at least 1")
    if args.timeout < 3:
        parser.error("--timeout must be at least 3 seconds")
    if args.request_delay < 0.5:
        parser.error("--request-delay must be at least 0.5 seconds")
    if args.min_width < 1 or args.min_height < 1:
        parser.error("minimum dimensions must be positive")
    if not 1 <= args.max_image_mb <= 100:
        parser.error("--max-image-mb must be between 1 and 100")
    return args


def run(args: argparse.Namespace) -> int:
    RAW_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    records = [record for record in load_existing_metadata() if record_is_usable(record)]
    attempted_urls = {record["image_url"] for record in records if record.get("image_url")}
    content_hashes = {
        record["image_id"].rsplit("_", 1)[-1]
        for record in records
        if record.get("image_id")
    }
    keywords = args.keyword or list(SUPPORTED_SEARCHES)

    with build_session() as session:
        for keyword in keywords:
            collect_keyword(
                session,
                keyword,
                SUPPORTED_SEARCHES[keyword],
                args.target_per_keyword,
                records,
                attempted_urls,
                content_hashes,
                args,
            )

    write_metadata(records)
    selected_count = sum(record.get("keyword") in keywords for record in records)
    if selected_count < 30:
        raise ImageCrawlerError(
            f"dataset contains only {selected_count} selected records; at least 30 are required"
        )
    print(f"[info] complete: {selected_count} images, metadata at {CSV_PATH}")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return run(parse_args(argv))
    except (ImageCrawlerError, OSError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
