#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for the cron logic in setup_schedule.py
(cross-platform, runs on any OS).

Run: python tests/test_cron_expr.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import setup_schedule as s


def test_to_cron_expr():
    assert s.to_cron_expr(daily="02:00") == "0 2 * * *", "daily 02:00"
    assert s.to_cron_expr(daily="13:05") == "5 13 * * *", "daily 13:05"
    assert s.to_cron_expr(hourly=6) == "0 */6 * * *", "every 6 hours"
    assert s.to_cron_expr(weekly=("10:00", "SUN")) == "0 10 * * 0", "every Sunday 10:00"
    assert s.to_cron_expr(weekly=("10:00", "MON")) == "0 10 * * 1", "every Monday 10:00"
    print("✔ to_cron_expr")


def test_valid_cron():
    assert s.valid_cron("0 2 * * *")
    assert s.valid_cron("*/15 8-18 * * 1-5")
    assert s.valid_cron("30 2,14 * * 0,6")
    assert s.valid_cron("0 */2 * * *")
    assert not s.valid_cron("0 2 * *")           # only 4 fields
    assert not s.valid_cron("a b c d e")         # illegal characters
    assert not s.valid_cron("0 25 * * *")        # hour out of range
    print("✔ valid_cron")


def test_describe_cron():
    assert s.describe_cron("0 2 * * *") == "Every day at 02:00"
    assert s.describe_cron("0 */6 * * *") == "Every 6 hours"
    assert s.describe_cron("0 10 * * 0") == "Every Sunday at 10:00"
    assert s.describe_cron("30 6 * * 1") == "Every Monday at 06:30"
    assert s.describe_cron("0 * * * *") == "Every hour"
    print("✔ describe_cron")


def test_crontab_block_roundtrip():
    block = s.crontab_block("0 2 * * *", "/usr/bin/python3 /app/pixabay_downloader.py")
    assert "# >>> PixabayDownloader start" in block
    assert "0 2 * * * /usr/bin/python3 /app/pixabay_downloader.py" in block
    assert "# <<< PixabayDownloader end" in block

    # A crontab with other user entries: after inserting and removing the block,
    # all other entries must be preserved verbatim
    text = ("# user's own comment\n0 5 * * * /usr/bin/backup\n" + block +
            "# trailing\n1 6 * * * /usr/bin/cleanup\n")
    cleaned = s.remove_old_block(text)
    assert "PixabayDownloader" not in cleaned
    assert "0 5 * * * /usr/bin/backup" in cleaned
    assert "1 6 * * * /usr/bin/cleanup" in cleaned
    assert "# user's own comment" in cleaned and "# trailing" in cleaned

    # Re-registering: remove the old block then insert a new one, no duplicates
    reinstall = s.remove_old_block(text).rstrip("\n") + "\n" + block
    assert reinstall.count("# >>> PixabayDownloader start") == 1
    print("✔ crontab marker block roundtrip")


def test_build_cron_command():
    cmd = s.build_cron_command(os.path.join(ROOT, "logs", "pixabay_download.log"))
    assert "pixabay_downloader.py" in cmd
    assert "--quiet" in cmd
    assert "--log" in cmd
    assert ">>" in cmd and "2>&1" in cmd
    assert "cron_stdout.log" in cmd
    print("✔ cron command building")


def main():
    test_to_cron_expr()
    test_valid_cron()
    test_describe_cron()
    test_crontab_block_roundtrip()
    test_build_cron_command()
    print("\nALL CRON TESTS PASSED ✔")


if __name__ == "__main__":
    main()
