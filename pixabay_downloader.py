#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pixabay Image Downloader
========================
Batch download images from Pixabay via the official API, organized by keyword.

Features:
  * Official API - stable and compliant, no browser automation
  * Multithreaded downloads with automatic retries
  * Global dedupe + resume: images already downloaded (recorded by Pixabay
    image ID in <output_dir>/download_history.json) are never re-downloaded,
    even if you change keywords, move the output folder, or move files
  * Re-running automatically fetches the NEXT new images until all results
    for a keyword are exhausted
  * A metadata.csv manifest is generated in each keyword folder
    (image ID / source page / tags / author / file / status)

Usage:
    python pixabay_downloader.py                          # download per config.json
    python pixabay_downloader.py --keywords "mountain,landscape" --count 100
    python pixabay_downloader.py --size large --output D:/pictures
    python pixabay_downloader.py --dry-run                # search only, print URLs

Config precedence: CLI arguments > env vars / .env file > config.json > defaults
Pure Python standard library (Python 3.8+), no third-party dependencies.
"""

import argparse
import concurrent.futures
import csv
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "config.json"
ENV_FILE = SCRIPT_DIR / ".env"
HISTORY_FILE_NAME = "download_history.json"

DEFAULT_CONFIG = {
    "keywords": ["mountain", "landscape", "forest", "lake", "nature"],
    "per_keyword": 50,
    "image_size": "original",
    "image_type": "photo",
    "safe_search": True,
    "output_dir": "F:/dsh/pixabay_images",
    "workers": 4,
    "api_delay_seconds": 0.2,
    "timeout_seconds": 60,
    "base_url": "https://pixabay.com/api/",
}

# API response fields for each size tier (in priority order, auto-fallback if missing)
SIZE_FIELDS = {
    "original": ("imageURL", "largeImageURL", "webformatURL", "previewURL"),
    "large": ("largeImageURL", "imageURL", "webformatURL", "previewURL"),
    "webformat": ("webformatURL", "previewURL"),
    "preview": ("previewURL",),
}

HTTP_HINTS = {
    400: "bad request (check base_url or query parameters)",
    401: "invalid API key, check PIXABAY_API_KEY in .env",
    403: "access denied (account issue or region restriction)",
    404: "endpoint not found (check base_url)",
    429: "rate limited, increase api_delay_seconds in config.json",
}


class ApiError(Exception):
    """Raised when the API call fails."""


class _Tee:
    """Write to both the terminal and a log file (used by --log)."""

    def __init__(self, stream, file):
        self.stream = stream
        self.file = file

    def write(self, data):
        self.stream.write(data)
        self.file.write(data)
        return len(data)

    def flush(self):
        self.stream.flush()
        self.file.flush()


# ---------------------------------------------------------------- config & key

def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            user = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(user, dict):
                cfg.update({k: v for k, v in user.items() if v is not None})
        except json.JSONDecodeError as e:
            print(f"! Warning: {CONFIG_FILE.name} is not valid JSON, ignored: {e}", file=sys.stderr)
    return cfg


# Env var -> config mapping (for Docker / server deployment)
# Precedence: CLI arguments > env vars > config.json > defaults
ENV_CONFIG_MAP = {
    "PIXABAY_KEYWORDS": ("keywords", lambda v: [k.strip() for k in v.split(",") if k.strip()]),
    "PIXABAY_COUNT": ("per_keyword", lambda v: max(1, int(v))),
    "PIXABAY_SIZE": ("image_size", str),
    "PIXABAY_IMAGE_TYPE": ("image_type", str),
    "PIXABAY_SAFE_SEARCH": ("safe_search", lambda v: v.strip().lower() in ("1", "true", "yes", "on")),
    "PIXABAY_OUTPUT_DIR": ("output_dir", str),
    "PIXABAY_WORKERS": ("workers", lambda v: max(1, int(v))),
    "PIXABAY_DELAY": ("api_delay_seconds", float),
    "PIXABAY_TIMEOUT": ("timeout_seconds", float),
    "PIXABAY_BASE_URL": ("base_url", str),
}


def apply_env_overrides(cfg):
    """Override config with environment variables (for Docker / server deployment)."""
    for env_name, (key, conv) in ENV_CONFIG_MAP.items():
        raw = os.environ.get(env_name)
        if raw is None or raw.strip() == "":
            continue
        try:
            cfg[key] = conv(raw.strip())
        except ValueError:
            print(f"! Warning: env var {env_name}={raw} could not be parsed, ignored", file=sys.stderr)
    if cfg["image_size"] not in SIZE_FIELDS:
        print(f"! Warning: image_size={cfg['image_size']} is invalid, falling back to original",
              file=sys.stderr)
        cfg["image_size"] = "original"
    return cfg


def load_dotenv(path):
    d = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


def resolve_api_key(cli_key):
    if cli_key:
        return cli_key.strip()
    env = os.environ.get("PIXABAY_API_KEY")
    if env:
        return env.strip()
    if ENV_FILE.exists():
        return load_dotenv(ENV_FILE).get("PIXABAY_API_KEY", "").strip()
    return ""


# ---------------------------------------------------------------- API requests

def http_get_json(url, timeout, retries=3):
    """GET a URL and parse JSON, with retries; raises ApiError on failure."""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body_text = ""
            try:
                raw = e.read().decode("utf-8", "replace").strip()
                if raw:
                    body_text = raw[:300]
            except Exception:
                pass
            msg = HTTP_HINTS.get(e.code, f"HTTP {e.code}")
            if re.search(r"API\s*key", body_text, re.IGNORECASE):
                msg = HTTP_HINTS[401]  # server explicitly reported a key problem
            if body_text:
                msg = f"{msg}; server response: {body_text}"
            if e.code == 429 or e.code >= 500:
                last_err = f"HTTP {e.code}"
                time.sleep(2 ** attempt)
                continue
            raise ApiError(f"API request failed: {msg}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = str(e)
            time.sleep(2 ** attempt)
    raise ApiError(f"API request failed after retries: {last_err}")


def collect_hits(base_url, key, query, target, image_type, safe_search, delay, exclude_ids):
    """Search with pagination, collecting NEW image entries only
    (deduped by id, excluding already-downloaded ids).

    Returns (new hits, total matches, count of already-downloaded hits).
    On re-runs, downloaded images are skipped and pagination continues
    to fetch the next new images.
    """
    hits_new, seen = [], set()
    page = 1
    per_page = min(200, max(3, target))
    total_hits = 0
    already = 0
    while len(hits_new) < target:
        params = {
            "key": key,
            "q": query,
            "page": page,
            "per_page": per_page,
            "image_type": image_type,
            "safesearch": 1 if safe_search else 0,
        }
        url = base_url + "?" + urllib.parse.urlencode(params)
        data = http_get_json(url, timeout=30)
        if isinstance(data, dict) and data.get("status") == "error":
            raise ApiError(f"API returned an error: {data.get('message', data)}")
        total_hits = data.get("totalHits", 0) if isinstance(data, dict) else 0
        hits = data.get("hits") or [] if isinstance(data, dict) else []
        if not hits:
            break
        for h in hits:
            hid = h.get("id")
            if hid in seen:
                continue
            seen.add(hid)
            if str(hid) in exclude_ids:
                already += 1
                continue
            hits_new.append(h)
        if len(hits) < per_page or len(seen) >= total_hits:
            break
        page += 1
        time.sleep(delay)
    return hits_new[:target], total_hits, already


# ---------------------------------------------------------------- image download

def pick_image_url(hit, size):
    """Pick the image URL for the requested size tier; returns (url, field name),
    or (None, None) if no usable URL exists."""
    fields = SIZE_FIELDS.get(size, SIZE_FIELDS["original"])
    for f in fields:
        v = hit.get(f)
        if v:
            return v, f
    return None, None


def guess_ext(url, hit):
    path = urllib.parse.urlparse(url).path
    ext = os.path.splitext(path)[1].lower()
    if ext and len(ext) <= 6 and re.fullmatch(r"\.[a-z0-9]+", ext):
        return ext
    return ".jpg"


def download_file(url, dest, timeout, retries=3):
    """Stream download to dest (writes a .part temp file, atomically renames on
    completion), with automatic retries on failure."""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            part = Path(str(dest) + ".part")
            with urllib.request.urlopen(req, timeout=timeout) as resp, open(part, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
            os.replace(part, dest)
            return
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                last_err = f"HTTP {e.code}"
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"HTTP {e.code}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = str(e)
            time.sleep(2 ** attempt)
    raise RuntimeError(f"failed after retries: {last_err}")


def download_one(hit, folder, size, timeout, ids_done):
    """Download a single image. Returns a result dict; never raises."""
    hid = hit.get("id")
    url, field = pick_image_url(hit, size)
    base = {
        "id": hid,
        "tags": hit.get("tags", ""),
        "page_url": hit.get("pageURL", ""),
        "user": hit.get("user", ""),
        "size": size,
        "source_field": field or "",
    }
    if not url:
        return {**base, "status": "failed", "file": "", "source_url": "",
                "reason": "", "error": "no usable image URL in the response"}
    ext = guess_ext(url, hit)
    dest = folder / f"{hid}{ext}"
    entry = {"file": dest.name, "source_url": url}

    if str(hid) in ids_done:
        return {**base, "status": "skipped", "reason": "history", **entry, "error": ""}
    if dest.exists() and dest.stat().st_size > 0:
        return {**base, "status": "skipped", "reason": "exists", **entry, "error": ""}
    try:
        download_file(url, dest, timeout)
        return {**base, "status": "ok", "reason": "", **entry, "error": ""}
    except Exception as e:
        return {**base, "status": "failed", "reason": "", **entry, "error": str(e)}


# ---------------------------------------------------------------- download history (global dedupe)

def load_history(output_dir):
    p = Path(output_dir) / HISTORY_FILE_NAME
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("ids"), dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"ids": {}}


def save_history(output_dir, history):
    p = Path(output_dir) / HISTORY_FILE_NAME
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


# ---------------------------------------------------------------- keyword handling

def sanitize_dirname(name):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().rstrip(". ")
    return s or "keyword"


def write_metadata(folder, kw, rows):
    path = folder / "metadata.csv"
    cols = ["id", "page_url", "tags", "user", "size", "file", "source_url", "status"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in sorted(rows, key=lambda x: str(x.get("id"))):
            w.writerow({c: r.get(c, "") for c in cols})


def run_keyword(kw, cfg, key, history, dry_run, quiet):
    folder = Path(cfg["output_dir"]) / sanitize_dirname(kw)
    if not dry_run:
        folder.mkdir(parents=True, exist_ok=True)

    try:
        exclude_ids = set(history["ids"])
        hits, total, already = collect_hits(
            cfg["base_url"], key, kw, cfg["per_keyword"],
            cfg["image_type"], cfg["safe_search"], cfg["api_delay_seconds"],
            exclude_ids,
        )
    except ApiError as e:
        print(f"[{kw}] search failed: {e}", file=sys.stderr)
        return {"keyword": kw, "ok": 0, "skipped": 0, "failed": 0, "error": str(e)}

    if not hits:
        if total > 0:
            print(f"[{kw}] Found {total} result(s), {already} already downloaded - "
                  "no new images to download (delete download_history.json to re-download).")
        else:
            print(f"[{kw}] No results found (totalHits=0). Try different keywords.")
        return {"keyword": kw, "ok": 0, "skipped": 0, "failed": 0, "error": ""}

    print(f"[{kw}] Found {total} result(s), {already} already downloaded, "
          f"will download {len(hits)} new")

    if dry_run:
        for h in hits:
            url, fld = pick_image_url(h, cfg["image_size"])
            print(f"  (dry-run) id={h.get('id')} {fld}={url}")
        return {"keyword": kw, "ok": 0, "skipped": 0, "failed": 0, "error": ""}

    ids_done = set(history["ids"])
    rows = []
    counters = {"ok": 0, "skipped": 0, "failed": 0}
    with concurrent.futures.ThreadPoolExecutor(max_workers=cfg["workers"]) as ex:
        futs = {
            ex.submit(download_one, h, folder, cfg["image_size"],
                      cfg["timeout_seconds"], ids_done): h
            for h in hits
        }
        for fut in concurrent.futures.as_completed(futs):
            r = fut.result()
            rows.append(r)
            counters[r["status"]] += 1

            if r["status"] == "ok":
                history["ids"][str(r["id"])] = {
                    "file": r["file"], "source_url": r["source_url"],
                    "keyword": kw, "size": r["size"],
                }
            elif r["status"] == "skipped" and r["reason"] == "exists":
                history["ids"][str(r["id"])] = {
                    "file": r["file"], "source_url": r["source_url"],
                    "keyword": kw, "size": r["size"],
                }

            if not quiet:
                mark = {"ok": "✔", "skipped": "⏭", "failed": "✖"}[r["status"]]
                why = {"history": " (already downloaded)", "exists": " (file exists)"}.get(
                    r["reason"], " (failed: " + r["error"] + ")" if r["error"] else "")
                print(f"  {mark} {r['file'] or r['id']}{why}")

    write_metadata(folder, kw, rows)
    save_history(cfg["output_dir"], history)
    print(f"[{kw}] Done: {counters['ok']} new | {counters['skipped']} skipped | "
          f"{counters['failed']} failed -> {folder}")
    return {"keyword": kw, **counters, "error": ""}


# ---------------------------------------------------------------- entry point

def parse_args(argv):
    p = argparse.ArgumentParser(
        prog="pixabay_downloader",
        description="Pixabay image downloader via the official API (stdlib only, no dependencies)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python pixabay_downloader.py\n"
            "  python pixabay_downloader.py --keywords \"mountain,landscape\" --count 100\n"
            "  python pixabay_downloader.py --size large --output D:/pictures\n"
            "  python pixabay_downloader.py --dry-run\n"
        ),
    )
    p.add_argument("--keywords", help="comma-separated search keywords (overrides config.json)")
    p.add_argument("--count", type=int,
                   help="new images to download per keyword (overrides config.json per_keyword); "
                        "on re-runs already-downloaded images are skipped and later new ones are fetched")
    p.add_argument("--size", choices=list(SIZE_FIELDS),
                   help="image size: original=original (default) | large=~1280px | "
                        "webformat=640px | preview=150px thumbnail")
    p.add_argument("--output", help="save directory (overrides config.json output_dir)")
    p.add_argument("--key", help="Pixabay API key (or set in .env / env var PIXABAY_API_KEY)")
    p.add_argument("--base-url", help="API base URL (usually not needed, mainly for testing)")
    p.add_argument("--workers", type=int, help="number of concurrent download threads")
    p.add_argument("--image-type", choices=["all", "photo", "illustration", "vector"],
                   help="image type: photo=photos (default) | illustration | vector | all")
    p.add_argument("--dry-run", action="store_true", help="search only, print image URLs, no download")
    p.add_argument("--quiet", action="store_true", help="do not print per-image progress lines")
    p.add_argument("--log", metavar="FILE",
                   help="also append run output to a log file (recommended for scheduled runs)")
    return p.parse_args(argv)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    args = parse_args(argv)
    cfg = load_config()
    apply_env_overrides(cfg)

    if args.keywords is not None:
        cfg["keywords"] = [k.strip() for k in args.keywords.split(",") if k.strip()]
    if args.count:
        cfg["per_keyword"] = max(1, args.count)
    if args.size:
        cfg["image_size"] = args.size
    if args.output:
        cfg["output_dir"] = args.output
    if args.workers:
        cfg["workers"] = max(1, args.workers)
    if args.image_type:
        cfg["image_type"] = args.image_type
    if args.base_url:
        cfg["base_url"] = args.base_url
    cfg["base_url"] = cfg["base_url"].rstrip("/") + "/"

    if args.log or os.environ.get("PIXABAY_LOG"):
        log_path = Path(args.log or os.environ["PIXABAY_LOG"])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = open(log_path, "a", encoding="utf-8")
        sys.stdout = _Tee(sys.stdout, log_file)
        sys.stderr = _Tee(sys.stderr, log_file)
        print(f"========== Run started: {datetime.datetime.now():%Y-%m-%d %H:%M:%S} "
              f"(keywords: {cfg['keywords']}, {cfg['per_keyword']} per keyword) ==========")

    key = resolve_api_key(args.key)
    if not key:
        print("Error: Pixabay API key is not set.", file=sys.stderr)
        print("  1) Register a free account: https://pixabay.com/accounts/register/", file=sys.stderr)
        print("  2) Copy your key from https://pixabay.com/api/docs/", file=sys.stderr)
        print("  3) Copy .env.example to .env and fill in the key, "
              "or set the PIXABAY_API_KEY environment variable", file=sys.stderr)
        return 2
    if not re.match(r"^\d{5,8}-[0-9a-f]{16,32}$", key):
        print(f"! Warning: key format looks unusual (usually 7 digits + dash + 32 hex): {key[:12]}...",
              file=sys.stderr)

    out = Path(cfg["output_dir"]).resolve()
    print(f"Save directory: {out}")
    print(f"Dedupe record: {out / HISTORY_FILE_NAME} (downloaded images are never re-downloaded)")
    if not args.dry_run:
        out.mkdir(parents=True, exist_ok=True)

    history = load_history(cfg["output_dir"]) if not args.dry_run else {"ids": {}}
    if history["ids"]:
        print(f"{len(history['ids'])} image(s) already downloaded, they will be skipped")

    results = []
    for kw in cfg["keywords"]:
        results.append(run_keyword(kw, cfg, key, history, args.dry_run, args.quiet))
        time.sleep(cfg["api_delay_seconds"])

    failed_any = any(r.get("error") for r in results)

    if not args.dry_run:
        ok = sum(r["ok"] for r in results)
        sk = sum(r["skipped"] for r in results)
        fl = sum(r["failed"] for r in results)
        print("=" * 40)
        for r in results:
            tag = f"  ({r['error']})" if r.get("error") else ""
            print(f"  {r['keyword']}: {r['ok']} new | {r['skipped']} skipped | {r['failed']} failed{tag}")
        print(f"Total: {ok} new, {sk} skipped, {fl} failed")
        print(f"Saved to: {out}")
    return 1 if failed_any else 0


if __name__ == "__main__":
    sys.exit(main())
