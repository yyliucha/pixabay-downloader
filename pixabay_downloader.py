#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pixabay 图片下载器
==================
通过 Pixabay 官方 API 按关键词批量下载图片到本地。

特性:
  * 官方 API, 合规稳定, 无需模拟浏览器
  * 多线程并发下载, 失败自动重试
  * 断点续传 + 全局去重: 下载过的图片(按 Pixabay 图片 ID 记录在
    <保存目录>/download_history.json)不会重复下载,
    即使换关键词、换目录或文件被移动过
  * 每个关键词目录下生成 metadata.csv 元数据清单
    (图片 ID / 来源页 / 标签 / 作者 / 文件 / 状态)

用法示例:
    python pixabay_downloader.py                          # 按 config.json 配置下载
    python pixabay_downloader.py --keywords "山,风景" --count 100
    python pixabay_downloader.py --size large --output D:/pictures
    python pixabay_downloader.py --dry-run                # 只搜索, 打印地址, 不下载

配置优先级: 命令行参数 > 环境变量 PIXABAY_API_KEY / .env 文件 > config.json
仅依赖 Python 标准库 (Python 3.8+), 无需安装任何第三方包。
"""

import argparse
import concurrent.futures
import csv
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
    "keywords": ["山", "风景", "森林", "湖泊", "自然"],
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

# 各尺寸档位对应的 API 响应字段（按优先级排列, 缺失时自动降级）
SIZE_FIELDS = {
    "original": ("imageURL", "largeImageURL", "webformatURL", "previewURL"),
    "large": ("largeImageURL", "imageURL", "webformatURL", "previewURL"),
    "webformat": ("webformatURL", "previewURL"),
    "preview": ("previewURL",),
}

HTTP_HINTS = {
    400: "请求参数有误(可能是 base_url 或查询参数问题)",
    401: "API key 无效, 请检查 .env 中的 PIXABAY_API_KEY 是否正确",
    403: "无访问权限(账号问题或地区限制)",
    404: "接口地址不存在(检查 base_url)",
    429: "请求过于频繁被限流, 可增大 config.json 中的 api_delay_seconds",
}


class ApiError(Exception):
    """API 调用失败。"""


# ---------------------------------------------------------------- 配置与密钥

def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            user = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(user, dict):
                cfg.update({k: v for k, v in user.items() if v is not None})
        except json.JSONDecodeError as e:
            print(f"! 警告: {CONFIG_FILE.name} 不是合法的 JSON, 已忽略: {e}", file=sys.stderr)
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


# ---------------------------------------------------------------- API 请求

def http_get_json(url, timeout, retries=3):
    """GET 请求并解析 JSON, 带重试; 失败抛 ApiError。"""
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
                msg = HTTP_HINTS[401]  # 服务端明确提示 key 问题
            if body_text:
                msg = f"{msg}; 服务端信息: {body_text}"
            if e.code == 429 or e.code >= 500:
                last_err = f"HTTP {e.code}"
                time.sleep(2 ** attempt)
                continue
            raise ApiError(f"API 请求失败: {msg}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = str(e)
            time.sleep(2 ** attempt)
    raise ApiError(f"API 请求多次重试后仍然失败: {last_err}")


def collect_hits(base_url, key, query, target, image_type, safe_search, delay, exclude_ids):
    """分页搜索, 收集指定数量的【新】图片条目(按 id 去重, 并排除已下载过的 id)。

    返回 (新图片列表, 总匹配数, 已下载过的数量)。
    再次运行时, 已下载的图片会被自动跳过, 继续翻页拿到后面的新图。
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
            raise ApiError(f"API 返回错误: {data.get('message', data)}")
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


# ---------------------------------------------------------------- 图片下载

def pick_image_url(hit, size):
    """按尺寸档位挑选图片地址, 返回 (url, 所用字段名); 没有可用地址返回 (None, None)。"""
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
    """流式下载到 dest(先写 .part 临时文件, 完成后原子改名), 失败自动重试。"""
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
    raise RuntimeError(f"多次重试失败: {last_err}")


def download_one(hit, folder, size, timeout, ids_done):
    """下载单张图片。返回结果字典, 绝不抛异常。"""
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
                "reason": "", "error": "响应中没有可用图片地址"}
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


# ---------------------------------------------------------------- 下载历史(全局去重)

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


# ---------------------------------------------------------------- 关键词处理

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
        print(f"[{kw}] 搜索失败: {e}", file=sys.stderr)
        return {"keyword": kw, "ok": 0, "skipped": 0, "failed": 0, "error": str(e)}

    if not hits:
        if total > 0:
            print(f"[{kw}] 共匹配 {total} 张, 其中 {already} 张已下载过, "
                  "没有新的图片可下载(如需重新下载, 请删除 download_history.json 后重跑)。")
        else:
            print(f"[{kw}] 没有找到结果 (totalHits=0)。"
                  "提示: 中文关键词结果可能较少, 可尝试英文关键词, 如 mountain / landscape / forest。")
        return {"keyword": kw, "ok": 0, "skipped": 0, "failed": 0, "error": ""}

    print(f"[{kw}] 共匹配 {total} 张, 其中 {already} 张已下载过, "
          f"本次将下载 {len(hits)} 张新图")

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
                why = {"history": " (已下载过, 跳过)", "exists": " (文件已存在, 跳过)"}.get(
                    r["reason"], " (失败: " + r["error"] + ")" if r["error"] else "")
                print(f"  {mark} {r['file'] or r['id']}{why}")

    write_metadata(folder, kw, rows)
    save_history(cfg["output_dir"], history)
    print(f"[{kw}] 完成: 新增 {counters['ok']} 张 | 跳过 {counters['skipped']} 张 | "
          f"失败 {counters['failed']} 张 → {folder}")
    return {"keyword": kw, **counters, "error": ""}


# ---------------------------------------------------------------- 入口

def parse_args(argv):
    p = argparse.ArgumentParser(
        prog="pixabay_downloader",
        description="Pixabay 官方 API 图片下载器(仅标准库, 无需安装依赖)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python pixabay_downloader.py\n"
            "  python pixabay_downloader.py --keywords \"山,风景\" --count 100\n"
            "  python pixabay_downloader.py --size large --output D:/pictures\n"
            "  python pixabay_downloader.py --dry-run\n"
        ),
    )
    p.add_argument("--keywords", help="要搜索的关键词, 逗号分隔 (覆盖 config.json)")
    p.add_argument("--count", type=int,
                   help="每个关键词下载的新图片数量 (覆盖 config.json 的 per_keyword); "
                        "再次运行时自动跳过已下载的, 继续下载后面的新图")
    p.add_argument("--size", choices=list(SIZE_FIELDS),
                   help="图片尺寸: original=原图(默认) | large=大图(约1280px) | "
                        "webformat=中等(640px) | preview=缩略图(150px)")
    p.add_argument("--output", help="保存目录 (覆盖 config.json 的 output_dir)")
    p.add_argument("--key", help="Pixabay API key (也可填在 .env 或环境变量 PIXABAY_API_KEY)")
    p.add_argument("--base-url", help="API 地址 (一般无需修改, 主要用于本地测试)")
    p.add_argument("--workers", type=int, help="并发下载线程数")
    p.add_argument("--image-type", choices=["all", "photo", "illustration", "vector"],
                   help="图片类型: photo=照片(默认) | illustration=插画 | vector=矢量图 | all=全部")
    p.add_argument("--dry-run", action="store_true", help="只搜索并打印图片地址, 不下载")
    p.add_argument("--quiet", action="store_true", help="不打印每张图片的进度行")
    return p.parse_args(argv)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    args = parse_args(argv)
    cfg = load_config()

    if args.keywords is not None:
        cfg["keywords"] = [k.strip() for k in re.split(r"[,，]", args.keywords) if k.strip()]
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

    key = resolve_api_key(args.key)
    if not key:
        print("错误: 未设置 Pixabay API key。", file=sys.stderr)
        print("  1) 免费注册账号: https://pixabay.com/accounts/register/", file=sys.stderr)
        print("  2) 登录后在 https://pixabay.com/api/docs/ 页面复制你的 key", file=sys.stderr)
        print("  3) 复制 .env.example 为 .env 并填入 key, 或设置环境变量 PIXABAY_API_KEY", file=sys.stderr)
        return 2
    if not re.match(r"^\d{5,8}-[0-9a-f]{16,32}$", key):
        print(f"! 警告: key 的格式看起来不太对(通常是 7位数字-32位十六进制): {key[:12]}...",
              file=sys.stderr)

    out = Path(cfg["output_dir"]).resolve()
    print(f"保存目录: {out}")
    print(f"去重记录: {out / HISTORY_FILE_NAME} (已下载的图片不会重复下载)")
    if not args.dry_run:
        out.mkdir(parents=True, exist_ok=True)

    history = load_history(cfg["output_dir"]) if not args.dry_run else {"ids": {}}
    if history["ids"]:
        print(f"已下载过 {len(history['ids'])} 张图片, 运行中会自动跳过")

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
            print(f"  {r['keyword']}: 新增 {r['ok']} | 跳过 {r['skipped']} | 失败 {r['failed']}{tag}")
        print(f"总计: 新增 {ok} 张, 跳过 {sk} 张, 失败 {fl} 张")
        print(f"保存位置: {out}")
    return 1 if failed_any else 0


if __name__ == "__main__":
    sys.exit(main())
