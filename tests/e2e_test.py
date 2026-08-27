#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
End-to-end test: a local mock server emulates the Pixabay API to verify the
downloader's full workflow.

Scenarios:
  1. First run: the first 4 images download successfully (one lacks the
     imageURL field, verifying the automatic fallback to largeImageURL)
  2. Re-run -> fetch later images: automatically skips the 4 already
     downloaded and downloads the next 2 new images (dedupe + new images)
  3. Re-run after everything is downloaded: reports "no new images",
     nothing is re-downloaded
  4. dry-run: only prints URLs, creates no files
  5. Environment-variable configuration (equivalent to Docker deployment)

Run (no network, no API key needed):
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

# Valid 1x1 JPEG / PNG (just to verify files are really written)
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

# (id, extension, whether the imageURL original field is provided)
IMAGE_SPECS = [
    (1001, "jpg", True),
    (1002, "png", False),  # deliberately missing imageURL, tests fallback to largeImageURL
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
            "tags": "mock test",
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


def run_cli(extra_args, out_dir, logs_dir, env=None):
    """Run the downloader CLI; capture output via log files (pipe-free, works
    in restricted environments)."""
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
    cmd_env = dict(os.environ)
    if env:
        cmd_env.update(env)
    with open(log_stdout, "wb") as fo, open(log_stderr, "wb") as fe:
        proc = subprocess.run(cmd, stdout=fo, stderr=fe, env=cmd_env)
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

            # ---- Scenario 1: first run downloads 4 (also verifies --log) ----
            log_file = os.path.join(tmp, "run.log")
            r = run_cli(["--keywords", "mountain", "--count", "4", "--workers", "3",
                         "--log", log_file], out, tmp)
            print(r["stdout"])
            if r["returncode"] != 0:
                print("STDERR:", r["stderr"])
                raise SystemExit("Scenario 1 failed: non-zero return code on first run")
            assert "4 new" in r["stdout"], f"first run should add 4 new: {r['stdout']}"
            assert "0 failed" in r["stdout"], "there should be no failures"
            log_text = open(log_file, encoding="utf-8").read()
            assert "Run started" in log_text, f"log missing start banner: {log_text}"
            assert "4 new" in log_text, f"log missing completion stats: {log_text}"

            mountain_dir = os.path.join(out, "mountain")
            assert sorted(os.listdir(mountain_dir)) == \
                ["1001.jpg", "1002.png", "1003.jpg", "1004.jpg", "metadata.csv"], \
                f"mountain folder file list mismatch: {sorted(os.listdir(mountain_dir))}"
            for f in ["1001.jpg", "1002.png", "1003.jpg", "1004.jpg"]:
                p = os.path.join(mountain_dir, f)
                assert os.path.getsize(p) > 0, f"{f} is empty"

            # ---- Scenario 2: re-run fetches the NEXT images (skips 4, adds 2) ----
            r2 = run_cli(["--keywords", "mountain", "--count", "4"], out, tmp)
            assert r2["returncode"] == 0, r2["stderr"]
            assert "4 already downloaded" in r2["stdout"], \
                f"should detect 4 already downloaded: {r2['stdout']}"
            assert "will download 2 new" in r2["stdout"], \
                f"should download the next 2 new: {r2['stdout']}"
            assert "2 new" in r2["stdout"], f"should add 2 new: {r2['stdout']}"
            assert sorted(os.listdir(mountain_dir)) == \
                ["1001.jpg", "1002.png", "1003.jpg", "1004.jpg",
                 "1005.jpg", "1006.png", "metadata.csv"], \
                f"file list mismatch after re-run: {sorted(os.listdir(mountain_dir))}"

            hist = json.loads(open(os.path.join(out, "download_history.json"), encoding="utf-8").read())
            assert sorted(hist["ids"]) == ["1001", "1002", "1003", "1004", "1005", "1006"], \
                f"dedupe record mismatch: {sorted(hist['ids'])}"

            # ---- Scenario 3: re-run after everything is downloaded -> no new images ----
            r3 = run_cli(["--keywords", "mountain", "--count", "4"], out, tmp)
            assert r3["returncode"] == 0
            assert "no new images" in r3["stdout"], f"should report no new images: {r3['stdout']}"
            assert "0 new" in r3["stdout"]
            # File list unchanged: nothing was re-downloaded
            assert sorted(os.listdir(mountain_dir)) == \
                ["1001.jpg", "1002.png", "1003.jpg", "1004.jpg",
                 "1005.jpg", "1006.png", "metadata.csv"], \
                f"files should not change after re-run: {sorted(os.listdir(mountain_dir))}"

            # ---- Scenario 4: dry-run creates no files ----
            out2 = os.path.join(tmp, "dry")
            r4 = run_cli(["--keywords", "mountain", "--count", "4", "--dry-run"], out2, tmp)
            assert r4["returncode"] == 0
            assert "(dry-run)" in r4["stdout"]
            assert not os.path.exists(out2), "dry-run must not create the output directory"

            # ---- Scenario 5: environment-variable config (Docker-style) ----
            out_env = os.path.join(tmp, "env_images")
            r5 = run_cli([], out_env, tmp, env={
                "PIXABAY_KEYWORDS": "mountain",
                "PIXABAY_COUNT": "2",
                "PIXABAY_SIZE": "original",
            })
            assert r5["returncode"] == 0, r5["stderr"]
            assert "2 new" in r5["stdout"], f"env config should download 2: {r5['stdout']}"
            assert sorted(os.listdir(os.path.join(out_env, "mountain"))) == \
                ["1001.jpg", "1002.png", "metadata.csv"], \
                f"env config files mismatch: {sorted(os.listdir(os.path.join(out_env, 'mountain')))}"

            print("\nALL TESTS PASSED ✔")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
