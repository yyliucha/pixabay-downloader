#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pixabay Downloader - Cross-platform scheduled task configuration
================================================================
Unified scheduling via cron expressions (minute hour day month weekday):

  * Linux / macOS : system cron (crontab command), user-level crontab, no root needed
  * Windows        : no native cron - automatically falls back to Task Scheduler (schtasks)
  * Docker         : built-in cron in the container (CRON_EXPRESSION env var)

All three use the same cron expression format, e.g. daily 02:00 = "0 2 * * *".

Usage:
  python setup_schedule.py --daily 02:00          # every day at 02:00
  python setup_schedule.py --hourly 6             # every 6 hours
  python setup_schedule.py --weekly "10:00 SUN"   # every Sunday at 10:00
  python setup_schedule.py --cron "0 */2 * * *"   # raw cron expression (same as Docker)
  python setup_schedule.py --list                 # show the current scheduled task
  python setup_schedule.py --remove               # remove the scheduled task
  python setup_schedule.py --dry-run              # print commands only, don't apply
  python setup_schedule.py                        # interactive wizard
"""

import argparse
import datetime
import platform
import re
import shlex
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DOWNLOADER = SCRIPT_DIR / "pixabay_downloader.py"
TASK_NAME = "PixabayDownloader"
DEFAULT_LOG = SCRIPT_DIR / "logs" / "pixabay_download.log"
MARKER = "PixabayDownloader"

IS_WINDOWS = platform.system() == "Windows"

WEEKDAY_MAP = {"SUN": 0, "MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5, "SAT": 6}
WEEKDAYS = list(WEEKDAY_MAP)
DAY_NAMES = {"SUN": "Sunday", "MON": "Monday", "TUE": "Tuesday", "WED": "Wednesday",
             "THU": "Thursday", "FRI": "Friday", "SAT": "Saturday"}


# ---------------------------------------------------------------- cron expressions

def valid_time(s):
    return bool(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", s))


def valid_cron(expr):
    """Validate a cron expression: 5 fields, format and value ranges (light check)."""
    parts = expr.split()
    if len(parts) != 5:
        return False
    limits = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]  # min hour dom month dow
    for field, (lo, hi) in zip(parts, limits):
        for item in field.split(","):
            base = item
            if "/" in item:
                base, _, step = item.partition("/")
                if not step.isdigit() or int(step) < 1:
                    return False
            if base == "*":
                continue
            if "-" in base:
                a, _, b = base.partition("-")
                if not (a.isdigit() and b.isdigit()):
                    return False
                a, b = int(a), int(b)
                if not (lo <= a <= hi and lo <= b <= hi and a <= b):
                    return False
            else:
                if not base.isdigit():
                    return False
                if not (lo <= int(base) <= hi):
                    return False
    return True


def to_cron_expr(daily=None, hourly=None, weekly=None):
    """Convert friendly time descriptions to cron expressions
    (same format as the Docker CRON_EXPRESSION)."""
    if daily:
        hh, mm = daily.split(":")
        return f"{int(mm)} {int(hh)} * * *"
    if hourly:
        return f"0 */{hourly} * * *"
    if weekly:
        time_str, day = weekly
        hh, mm = time_str.split(":")
        return f"{int(mm)} {int(hh)} * * {WEEKDAY_MAP[day]}"
    raise ValueError("one of daily / hourly / weekly must be provided")


def describe_cron(expr):
    """Convert a cron expression to a human-readable description."""
    mm, hh, dom, mon, dow = expr.split()
    if dow != "*":
        day_key = next((k for k, v in WEEKDAY_MAP.items() if str(v) == dow), dow)
        return f"Every {DAY_NAMES.get(day_key, day_key)} at {int(hh):02d}:{int(mm):02d}"
    if mm == "0" and (hh == "*" or hh.startswith("*/")):
        m = re.fullmatch(r"\*/(\d+)", hh)
        if m:
            return f"Every {m.group(1)} hours"
        return "Every hour"
    if dom == "*" and mon == "*":
        return f"Every day at {int(hh):02d}:{int(mm):02d}"
    return f"cron({expr})"


# ---------------------------------------------------------------- common helpers

def check_required_deps():
    if not IS_WINDOWS:
        try:
            subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
        except FileNotFoundError:
            print("Error: crontab command not found. Please install cron "
                  "(e.g. Debian/Ubuntu: apt install cron)", file=sys.stderr)
            sys.exit(1)


def run_cmd(cmd, dry_run=False, **kwargs):
    """Run a command; only print it when dry_run is set."""
    print("Executing: " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
    if dry_run:
        print("[dry-run] not executed.")
        return 0, "", ""
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kwargs)
    if r.stdout.strip():
        print(r.stdout.strip())
    if r.stderr.strip():
        print(r.stderr.strip(), file=sys.stderr)
    return r.returncode, r.stdout, r.stderr


def build_cron_command(log_path):
    """Build the shell command for cron (with log redirection so cron mail
    never swallows the output)."""
    py = shlex.quote(str(sys.executable))
    script = shlex.quote(str(DOWNLOADER))
    log = shlex.quote(str(Path(log_path).resolve()))
    cron_stdout = shlex.quote(str(Path(log_path).resolve().with_name("cron_stdout.log")))
    return f"{py} {script} --quiet --log {log} >> {cron_stdout} 2>&1"


# ---------------------------------------------------------------- Linux/macOS: system cron

def get_crontab():
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode == 0:
        return r.stdout
    return ""  # `crontab -l` returns non-zero when no crontab exists


def crontab_block(expr, command):
    return (f"# >>> {MARKER} start\n"
            f"{expr} {command}\n"
            f"# <<< {MARKER} end\n")


def remove_old_block(text):
    pattern = re.compile(rf"^# >>> {re.escape(MARKER)} start\n.*?# <<< {re.escape(MARKER)} end\n?",
                         re.M | re.S)
    return pattern.sub("", text)


def has_block(text):
    return f"# >>> {MARKER} start" in text


def install_cron_posix(expr, log_path, dry_run=False):
    check_required_deps()
    command = build_cron_command(log_path)
    block = crontab_block(expr, command)
    existing = get_crontab()
    new_text = remove_old_block(existing).rstrip("\n")
    if new_text:
        new_text += "\n"
    new_text += block
    print(f"Scheduled task: {expr}  ({describe_cron(expr)})")
    if dry_run:
        print("Would write the following to your user crontab:")
        print(new_text)
        return 0
    rc, _, err = run_cmd(["crontab", "-"], dry_run=False, input=new_text)
    if rc != 0:
        print(f"crontab install failed: {err.strip()}", file=sys.stderr)
        return 1
    print("✔ Written to user crontab (marked block; re-registering replaces it automatically)")
    return 0


def remove_posix(dry_run=False):
    check_required_deps()
    existing = get_crontab()
    if not has_block(existing):
        print("No registered task found (no PixabayDownloader marker block)")
        return 0
    new_text = remove_old_block(existing)
    if dry_run:
        start = existing.index("# >>>")
        end = existing.index("# <<<") + len("# <<< PixabayDownloader end")
        print("Block that would be removed:")
        print(existing[start:end])
        print("---- Crontab after removal ----")
        print(new_text)
        return 0
    rc, _, err = run_cmd(["crontab", "-"], input=new_text)
    if rc != 0:
        print(f"crontab update failed: {err.strip()}", file=sys.stderr)
        return 1
    print("✔ Removed the PixabayDownloader task from crontab")
    return 0


def list_posix():
    check_required_deps()
    existing = get_crontab()
    if has_block(existing):
        start = existing.index("# >>>")
        end = existing.index("# <<<") + len("# <<< PixabayDownloader end")
        print("Current scheduled task:")
        print(existing[start:end])
    else:
        print("PixabayDownloader task is not registered")


# ---------------------------------------------------------------- Windows: Task Scheduler (fallback)

def build_runner_bat(log_path):
    py = sys.executable
    log = str(Path(log_path).resolve())
    runner = SCRIPT_DIR / "scheduled_run.bat"
    lines = [
        "@echo off",
        f'cd /d "{SCRIPT_DIR}"',
        f'"{py}" "{DOWNLOADER}" --quiet --log "{log}"',
    ]
    runner.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return runner


def install_windows(expr, log_path, dry_run=False):
    runner = build_runner_bat(log_path)
    cmd = ["schtasks", "/Create", "/TN", TASK_NAME, "/TR", str(runner),
           "/SC", "DAILY", "/ST", "00:00", "/F"]
    # schtasks cannot express arbitrary cron expressions; convert what it can
    mm, hh, dom, mon, dow = expr.split()
    if mon != "*" or dom != "*":
        print("Error: Windows Task Scheduler cannot express this cron expression "
              "(contains month/day restrictions). Use Docker (built-in cron) or "
              "Linux/macOS (system cron) instead.", file=sys.stderr)
        return 2
    if dow != "*":
        cmd[cmd.index("/SC") + 1] = "WEEKLY"
        cmd += ["/D", next(k for k, v in WEEKDAY_MAP.items() if str(v) == dow)]
        st = f"{int(hh):02d}:{int(mm):02d}"
    elif hh.startswith("*/"):
        cmd[cmd.index("/SC") + 1] = "HOURLY"
        cmd += ["/MO", hh.split("/")[1]]
        st = "00:00"  # for HOURLY, /ST is the start time; the interval comes from /MO
    else:
        st = f"{int(hh):02d}:{int(mm):02d}"
    cmd[cmd.index("/ST") + 1] = st
    print(f"Scheduled task: {expr}  ({describe_cron(expr)})")
    print("Note: Windows has no native cron, using Task Scheduler (schtasks) as a fallback")
    rc, _, _ = run_cmd(cmd, dry_run=dry_run)
    if rc != 0 or dry_run:
        return rc
    rc, _, _ = run_cmd(["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST"])
    if rc == 0:
        print(f"✔ Scheduled task ready: {TASK_NAME}")
    return rc


def remove_windows(dry_run=False):
    return run_cmd(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], dry_run=dry_run)[0]


def list_windows():
    rc, out, _ = run_cmd(["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST"])
    if rc != 0:
        print("PixabayDownloader task is not registered")


# ---------------------------------------------------------------- entry point

def install(expr, log_path, dry_run=False):
    if IS_WINDOWS:
        return install_windows(expr, log_path, dry_run)
    return install_cron_posix(expr, log_path, dry_run)


def remove(dry_run=False):
    if IS_WINDOWS:
        return remove_windows(dry_run)
    return remove_posix(dry_run)


def list_tasks():
    if IS_WINDOWS:
        list_windows()
    else:
        list_posix()


def parse_time(raw):
    t = raw.strip()
    if not valid_time(t):
        print(f"Error: time must be HH:MM (24-hour format), e.g. 02:00", file=sys.stderr)
        sys.exit(1)
    return t


def interactive():
    print("=" * 52)
    print("Pixabay Downloader - Scheduled Task Setup (cron, cross-platform)")
    print("=" * 52)
    print("Choose a schedule:")
    print("  1) Every day at a fixed time (e.g. 02:00)")
    print("  2) Every N hours (e.g. every 6 hours)")
    print("  3) A specific weekday (e.g. Sunday 10:00)")
    print("  4) Custom cron expression (e.g. 0 */2 * * *)")
    print("  5) Show the current scheduled task")
    print("  6) Remove the scheduled task")
    choice = input("Enter number [1]: ").strip() or "1"
    if choice == "6":
        return remove()
    if choice == "5":
        return list_tasks()
    if choice == "4":
        expr = input("Cron expression (min hour dom month dow) [0 2 * * *]: ").strip() or "0 2 * * *"
        if not valid_cron(expr):
            print(f"Error: cron expression '{expr}' is invalid", file=sys.stderr)
            return 1
        return install(expr, DEFAULT_LOG)
    if choice == "2":
        n = input("Every how many hours [6]: ").strip() or "6"
        if not n.isdigit() or int(n) < 1:
            print("Error: please enter a positive integer number of hours", file=sys.stderr)
            return 1
        return install(to_cron_expr(hourly=int(n)), DEFAULT_LOG)
    if choice == "3":
        day = input(f"Day of week [{', '.join(WEEKDAYS)}]: ").strip().upper()
        if day not in WEEKDAY_MAP:
            print("Error: day of week must be " + "/".join(WEEKDAYS), file=sys.stderr)
            return 1
        t = parse_time(input("Start time (HH:MM) [10:00]: ").strip() or "10:00")
        return install(to_cron_expr(weekly=(t, day)), DEFAULT_LOG)
    t = parse_time(input("Download at (HH:MM) [02:00]: ").strip() or "02:00")
    return install(to_cron_expr(daily=t), DEFAULT_LOG)


def parse_args(argv):
    p = argparse.ArgumentParser(
        prog="setup_schedule",
        description="Pixabay Downloader - cross-platform scheduled task config (cron: min hour dom month dow)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python setup_schedule.py --daily 02:00\n"
            "  python setup_schedule.py --hourly 6\n"
            "  python setup_schedule.py --weekly \"10:00 SUN\"\n"
            "  python setup_schedule.py --cron \"0 */2 * * *\"\n"
            "  python setup_schedule.py --list\n"
            "  python setup_schedule.py --remove\n"
        ),
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--daily", metavar="HH:MM", help="every day at a fixed time, e.g. 02:00")
    g.add_argument("--hourly", metavar="N", type=int, help="every N hours")
    g.add_argument("--weekly", metavar="'HH:MM DAY'", help="on a weekday, e.g. '10:00 SUN'")
    g.add_argument("--cron", metavar="EXPR",
                   help="raw cron expression, e.g. \"0 2 * * *\" (same format as Docker CRON_EXPRESSION)")
    g.add_argument("--list", action="store_true", help="show the current scheduled task")
    g.add_argument("--remove", action="store_true", help="remove the scheduled task")
    p.add_argument("--log", metavar="FILE", default=str(DEFAULT_LOG),
                   help=f"download log file (default {DEFAULT_LOG})")
    p.add_argument("--dry-run", action="store_true", help="only print the commands, don't apply")
    return p.parse_args(argv)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    args = parse_args(argv)
    dry = args.dry_run

    if args.list:
        return list_tasks()
    if args.remove:
        return remove(dry)
    if args.cron:
        expr = args.cron.strip()
        if not valid_cron(expr):
            print(f"Error: cron expression '{expr}' is invalid "
                  "(must be 5 fields: min hour dom month dow)", file=sys.stderr)
            return 1
        return install(expr, args.log, dry)
    if args.daily:
        return install(to_cron_expr(daily=parse_time(args.daily)), args.log, dry)
    if args.hourly:
        if args.hourly < 1:
            print("Error: hours must be >= 1", file=sys.stderr)
            return 1
        return install(to_cron_expr(hourly=args.hourly), args.log, dry)
    if args.weekly:
        parts = args.weekly.split()
        if len(parts) != 2 or parts[1].upper() not in WEEKDAY_MAP:
            print("Error: --weekly format is \"HH:MM DAY\", e.g. \"10:00 SUN\"", file=sys.stderr)
            return 1
        return install(to_cron_expr(weekly=(parse_time(parts[0]), parts[1].upper())), args.log, dry)
    return interactive()


if __name__ == "__main__":
    sys.exit(main())
