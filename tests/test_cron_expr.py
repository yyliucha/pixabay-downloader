#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup_schedule.py 的 cron 逻辑单元测试(跨平台, 任何系统均可运行)。

运行: python tests/test_cron_expr.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import setup_schedule as s


def test_to_cron_expr():
    assert s.to_cron_expr(daily="02:00") == "0 2 * * *", "每天02:00"
    assert s.to_cron_expr(daily="13:05") == "5 13 * * *", "每天13:05"
    assert s.to_cron_expr(hourly=6) == "0 */6 * * *", "每6小时"
    assert s.to_cron_expr(weekly=("10:00", "SUN")) == "0 10 * * 0", "每周日10:00"
    assert s.to_cron_expr(weekly=("10:00", "MON")) == "0 10 * * 1", "每周一10:00"
    print("✔ to_cron_expr")


def test_valid_cron():
    assert s.valid_cron("0 2 * * *")
    assert s.valid_cron("*/15 8-18 * * 1-5")
    assert s.valid_cron("30 2,14 * * 0,6")
    assert s.valid_cron("0 */2 * * *")
    assert not s.valid_cron("0 2 * *")           # 只有4个字段
    assert not s.valid_cron("a b c d e")         # 非法字符
    assert not s.valid_cron("0 25 * * *")        # 小时越界(轻量校验)
    print("✔ valid_cron")


def test_describe_cron():
    assert s.describe_cron("0 2 * * *") == "每天 02:00"
    assert s.describe_cron("0 */6 * * *") == "每 6 小时"
    assert s.describe_cron("0 10 * * 0") == "每周周日 10:00"
    assert s.describe_cron("30 6 * * 1") == "每周周一 06:30"
    assert s.describe_cron("0 * * * *") == "每小时"
    print("✔ describe_cron")


def test_crontab_block_roundtrip():
    block = s.crontab_block("0 2 * * *", "/usr/bin/python3 /app/pixabay_downloader.py")
    assert "# >>> PixabayDownloader start" in block
    assert "0 2 * * * /usr/bin/python3 /app/pixabay_downloader.py" in block
    assert "# <<< PixabayDownloader end" in block

    # 有其它用户条目的 crontab, 插入块后再移除, 其它条目必须原样保留
    text = "# 用户自己的注释\n0 5 * * * /usr/bin/backup\n" + block + "# 结尾\n1 6 * * * /usr/bin/cleanup\n"
    cleaned = s.remove_old_block(text)
    assert "PixabayDownloader" not in cleaned
    assert "0 5 * * * /usr/bin/backup" in cleaned
    assert "1 6 * * * /usr/bin/cleanup" in cleaned
    assert "# 用户自己的注释" in cleaned and "# 结尾" in cleaned

    # 重复注册: 先移除旧块再插入新块, 不产生重复
    reinstall = s.remove_old_block(text).rstrip("\n") + "\n" + block
    assert reinstall.count("# >>> PixabayDownloader start") == 1
    print("✔ crontab 标记块往返")


def test_build_cron_command():
    cmd = s.build_cron_command(os.path.join(ROOT, "logs", "pixabay_download.log"))
    assert "pixabay_downloader.py" in cmd
    assert "--quiet" in cmd
    assert "--log" in cmd
    assert ">>" in cmd and "2>&1" in cmd
    assert "cron_stdout.log" in cmd
    print("✔ cron 命令构建")


def main():
    test_to_cron_expr()
    test_valid_cron()
    test_describe_cron()
    test_crontab_block_roundtrip()
    test_build_cron_command()
    print("\nALL CRON TESTS PASSED ✔")


if __name__ == "__main__":
    main()
