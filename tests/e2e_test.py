#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端测试: 用本地模拟服务器模拟 Pixabay API, 验证下载器的完整流程。

覆盖场景:
  1. 首次下载: 前 4 张全部下载成功 (其中 1 张缺少 imageURL 字段,
     验证自动降级到 largeImageURL)
  2. 再次运行 → 下载后面的图片: 自动翻页跳过已下载的 4 张,
     继续下载后续 2 张新图 (验证"不重复下载 + 下载新图")
  3. 全部下完后重跑: 提示"没有新的图片可下载", 不重复下载任何一张
  4. dry-run: 只打印地址, 不创建任何文件

运行方式(无需网络、无需 API key):
    python tests/e2e_test.py
"""

import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADER = os.path.join(ROOT, "pixabay_downloader.py")

# 1x1 像素的合法 JPEG / PNG (仅用于验证文件确实被写入)
JPEG_BYTES = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwg"
    "JC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAA"
    "AAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AVN//2Q=="
)
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAA"
    "AABJRU5ErkJggg=="
)

PORT = {"v": 0}

# (id, 扩展名, 是否提供 imageURL 原图字段)
IMAGE_SPECS = [
    (1001, "jpg", True),
    (1002, "png", False),  # 故意缺 imageURL, 测试降级到 largeImageURL
    (1003, "jpg", True),
    (1004, "jpg", True),
    (1005, "jpg", True),
    (1006, "png", True),
]


def make_hits(start, end):
    hits = []
    for hid, ext, has_original in IMAGE_SPECS[start:end]:
        img_url = f"http://127.0.0.1:{PORT['v']}/img/{hid}.{ext}"
        hit = {
            "id": hid,
            "pageURL": f"https://pixabay.com/photos/demo-{hid}/",
            "type": "photo",
            "tags": "mock test 测试",
            "previewURL": img_url,
            "webformatURL": img_url,
            "largeImageURL": img_url,
            "imageURL": img_url if has_original else None,
            "imageWidth": 100,
            "imageHeight": 80,
            "imageSize": 1234,
            "views": 1,
            "downloads": 1,
            "user": "tester",
            "userImageURL": "",
        }
        hits.append(hit)
    return hits


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/":
            qs = urllib.parse.parse_qs(parsed.query)
            page = int(qs.get("page", ["1"])[0])
            per_page = int(qs.get("per_page", ["200"])[0])
            start = (page - 1) * per_page
            end = min(start + per_page, len(IMAGE_SPECS))
            hits = make_hits(start, end) if start < len(IMAGE_SPECS) else []
            body = {"total": len(IMAGE_SPECS), "totalHits": len(IMAGE_SPECS), "hits": hits}
            self._send(200, "application/json", json.dumps(body).encode("utf-8"))
        elif parsed.path.startswith("/img/"):
            name = os.path.basename(parsed.path)
            ext = os.path.splitext(name)[1].lower()
            data = PNG_BYTES if ext == ".png" else JPEG_BYTES
            ctype = "image/png" if ext == ".png" else "image/jpeg"
            self._send(200, ctype, data)
        else:
            self._send(404, "text/plain", b"not found")

    def _send(self, code, ctype, data):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


_LOG_COUNTER = {"n": 0}


def run_cli(extra_args, out_dir, logs_dir):
    """运行下载器 CLI, 输出重定向到日志文件后读回 (兼容无管道环境)。"""
    _LOG_COUNTER["n"] += 1
    log_stdout = os.path.join(logs_dir, f"stdout_{_LOG_COUNTER['n']}.log")
    log_stderr = os.path.join(logs_dir, f"stderr_{_LOG_COUNTER['n']}.log")
    cmd = [
        sys.executable, DOWNLOADER,
        "--key", "1234567-0123456789abcdef0123456789abcdef",
        "--base-url", f"http://127.0.0.1:{PORT['v']}/api/",
        "--output", out_dir,
        *extra_args,
    ]
    with open(log_stdout, "wb") as fo, open(log_stderr, "wb") as fe:
        proc = subprocess.run(cmd, stdout=fo, stderr=fe)
    return {
        "returncode": proc.returncode,
        "stdout": open(log_stdout, "rb").read().decode("utf-8", "replace"),
        "stderr": open(log_stderr, "rb").read().decode("utf-8", "replace"),
    }


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    PORT["v"] = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="pixabay_test_") as tmp:
            out = os.path.join(tmp, "images")

            # ---- 场景 1: 首次下载 4 张 (同时验证 --log 日志写入)
            log_file = os.path.join(tmp, "run.log")
            r = run_cli(["--keywords", "山", "--count", "4", "--workers", "3",
                         "--log", log_file], out, tmp)
            print(r["stdout"])
            if r["returncode"] != 0:
                print("STDERR:", r["stderr"])
                raise SystemExit("场景1失败: 首次下载返回码非0")
            assert "新增 4 张" in r["stdout"], "首次应新增 4 张"
            assert "失败 0 张" in r["stdout"], "不应有失败"
            log_text = open(log_file, encoding="utf-8").read()
            assert "开始运行" in log_text, f"日志缺少开始标记: {log_text}"
            assert "新增 4 张" in log_text, f"日志缺少完成统计: {log_text}"

            mountain_dir = os.path.join(out, "山")
            assert sorted(os.listdir(mountain_dir)) == \
                ["1001.jpg", "1002.png", "1003.jpg", "1004.jpg", "metadata.csv"], \
                f"山 目录文件列表不符: {sorted(os.listdir(mountain_dir))}"
            for f in ["1001.jpg", "1002.png", "1003.jpg", "1004.jpg"]:
                p = os.path.join(mountain_dir, f)
                assert os.path.getsize(p) > 0, f"{f} 为空文件"

            # ---- 场景 2: 再次运行 → 下载后面的图片 (跳过已下载的 4 张, 继续拿新 2 张)
            r2 = run_cli(["--keywords", "山", "--count", "4"], out, tmp)
            assert r2["returncode"] == 0, r2["stderr"]
            assert "其中 4 张已下载过" in r2["stdout"], f"应识别出已下载过的4张: {r2['stdout']}"
            assert "本次将下载 2 张新图" in r2["stdout"], f"应下载后续2张新图: {r2['stdout']}"
            assert "新增 2 张" in r2["stdout"], f"应新增 2 张: {r2['stdout']}"
            assert sorted(os.listdir(mountain_dir)) == \
                ["1001.jpg", "1002.png", "1003.jpg", "1004.jpg",
                 "1005.jpg", "1006.png", "metadata.csv"], \
                f"再次运行后文件列表不符: {sorted(os.listdir(mountain_dir))}"

            hist = json.loads(open(os.path.join(out, "download_history.json"), encoding="utf-8").read())
            assert sorted(hist["ids"]) == ["1001", "1002", "1003", "1004", "1005", "1006"], \
                f"去重记录不符: {sorted(hist['ids'])}"

            # ---- 场景 3: 全部下完后重跑 → 不重复下载, 提示没有新图
            r3 = run_cli(["--keywords", "山", "--count", "4"], out, tmp)
            assert r3["returncode"] == 0
            assert "没有新的图片可下载" in r3["stdout"], f"应提示没有新图: {r3['stdout']}"
            assert "新增 0 张" in r3["stdout"]
            # 文件数量不变, 一张都没重复下载
            assert sorted(os.listdir(mountain_dir)) == \
                ["1001.jpg", "1002.png", "1003.jpg", "1004.jpg",
                 "1005.jpg", "1006.png", "metadata.csv"], \
                f"重跑后文件不应变化: {sorted(os.listdir(mountain_dir))}"

            # ---- 场景 4: dry-run 不创建任何文件
            out2 = os.path.join(tmp, "dry")
            r4 = run_cli(["--keywords", "山", "--count", "4", "--dry-run"], out2, tmp)
            assert r4["returncode"] == 0
            assert "(dry-run)" in r4["stdout"]
            assert not os.path.exists(out2), "dry-run 不应创建目录"

            print("\nALL TESTS PASSED ✔")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
