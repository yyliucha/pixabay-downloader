#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pixabay 下载器 - Windows 定时任务配置工具
========================================
通过 Windows 任务计划程序 (schtasks) 注册定时自动下载任务。

原理: 每次任务触发时, 下载器只下载尚未下载过的新图片
(依据 download_history.json 全局去重), 因此定时任务长期运行
= 图片持续自动积累, 且永远不会重复下载。

用法:
  python setup_schedule.py                     # 交互式引导
  python setup_schedule.py --daily 02:00       # 每天 02:00 下载
  python setup_schedule.py --hourly 6          # 每 6 小时下载
  python setup_schedule.py --weekly 10:00 SUN  # 每周日 10:00 下载
  python setup_schedule.py --run-now           # 立即触发一次(测试用, 需已注册)
  python setup_schedule.py --remove            # 删除已注册的定时任务
  python setup_schedule.py --dry-run           # 只打印将执行的命令, 不实际注册
  python setup_schedule.py --log FILE          # 指定日志文件(默认 logs/pixabay_download.log)

说明:
  * 任务名称为 PixabayDownloader, 默认"仅当用户登录时运行"
  * 会生成 scheduled_run.bat(固化 Python 与脚本路径)供任务调用
  * 修改项目路径或升级 Python 后, 请重新运行本工具
"""

import argparse
import datetime
import platform
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DOWNLOADER = SCRIPT_DIR / "pixabay_downloader.py"
RUNNER_BAT = SCRIPT_DIR / "scheduled_run.bat"
TASK_NAME = "PixabayDownloader"
DEFAULT_LOG = SCRIPT_DIR / "logs" / "pixabay_download.log"

WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def check_windows():
    if platform.system() != "Windows":
        print("错误: 定时任务功能仅支持 Windows(依赖系统任务计划程序)。", file=sys.stderr)
        sys.exit(1)


def valid_time(s):
    return bool(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", s))


def run_schtasks(args, dry_run=False):
    """执行 schtasks 命令; dry_run 时只打印不执行。"""
    cmd = ["schtasks"] + args
    print("执行: " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
    if dry_run:
        print("[dry-run] 未实际执行。")
        return 0
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"schtasks 调用失败: {e}", file=sys.stderr)
        return 1
    if r.stdout.strip():
        print(r.stdout.strip())
    if r.stderr.strip():
        print(r.stderr.strip(), file=sys.stderr)
    return r.returncode


def build_runner_bat(log_path):
    """生成供任务计划程序调用的批处理: 固化 Python 解释器、脚本与日志路径。"""
    py = sys.executable
    log = str(Path(log_path).resolve())
    lines = [
        "@echo off",
        f'cd /d "{SCRIPT_DIR}"',
        f'"{py}" "{DOWNLOADER}" --quiet --log "{log}"',
    ]
    RUNNER_BAT.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    print(f"✔ 已生成启动脚本: {RUNNER_BAT}")
    return RUNNER_BAT


def register(schedule, log_path, dry_run=False):
    """schedule: dict, 含 sc/mo/d/st 字段(与 schtasks /SC 对应)。"""
    if dry_run:
        runner = RUNNER_BAT  # 仅展示, 不写入
    else:
        runner = build_runner_bat(log_path)
    cmd = ["/Create", "/TN", TASK_NAME, "/TR", str(runner), "/SC", schedule["sc"], "/F"]
    if schedule.get("mo"):
        cmd += ["/MO", str(schedule["mo"])]
    if schedule.get("d"):
        cmd += ["/D", schedule["d"]]
    if schedule.get("st"):
        cmd += ["/ST", schedule["st"]]
    if dry_run:
        run_schtasks(cmd, dry_run=True)
        return 0
    rc = run_schtasks(cmd)
    if rc != 0:
        return 1
    rc = run_schtasks(["/Query", "/TN", TASK_NAME, "/FO", "LIST"])
    if rc == 0:
        print(f"✔ 定时任务已就绪: {TASK_NAME}  (触发方式: {schedule_desc(schedule)})")
        print(f"  日志文件: {Path(log_path).resolve()}")
    return rc


def schedule_desc(schedule):
    sc = schedule["sc"]
    if sc == "DAILY":
        return f"每天 {schedule['st']}"
    if sc == "HOURLY":
        return f"每 {schedule['mo']} 小时"
    if sc == "WEEKLY":
        return f"每周{schedule['d']} {schedule['st']}"
    return sc


def parse_time(raw, what="时间"):
    t = raw.strip()
    if not valid_time(t):
        print(f"错误: {what}格式应为 HH:MM(24小时制), 例如 02:00", file=sys.stderr)
        sys.exit(1)
    return t


def interactive():
    print("=" * 52)
    print("Pixabay 下载器 - 定时任务设置")
    print("=" * 52)
    print("请选择定时方式:")
    print("  1) 每天固定时间 (如 02:00)")
    print("  2) 每隔 N 小时 (如每 6 小时)")
    print("  3) 每周某天 (如周日 10:00)")
    print("  4) 删除已注册的定时任务")
    choice = input("输入编号 [1]: ").strip() or "1"
    if choice == "4":
        return remove()
    if choice == "2":
        n = input("每隔几小时 [6]: ").strip() or "6"
        if not n.isdigit() or int(n) < 1:
            print("错误: 请输入正整数小时数", file=sys.stderr)
            return 1
        return register({"sc": "HOURLY", "mo": int(n)}, DEFAULT_LOG)
    if choice == "3":
        day = input(f"星期几 [{', '.join(WEEKDAYS)}]: ").strip().upper()
        if day not in WEEKDAYS:
            print("错误: 星期几应为 " + "/".join(WEEKDAYS), file=sys.stderr)
            return 1
        t = parse_time(input("几点开始 (HH:MM) [10:00]: ").strip() or "10:00")
        return register({"sc": "WEEKLY", "d": day, "st": t}, DEFAULT_LOG)
    t = parse_time(input("几点下载 (HH:MM) [02:00]: ").strip() or "02:00")
    return register({"sc": "DAILY", "st": t}, DEFAULT_LOG)


def remove(dry_run=False):
    cmd = ["/Delete", "/TN", TASK_NAME, "/F"]
    if dry_run:
        run_schtasks(cmd, dry_run=True)
        return 0
    rc = run_schtasks(cmd)
    if rc == 0:
        print(f"✔ 已删除定时任务: {TASK_NAME}")
        print("  (scheduled_run.bat 保留, 可手动双击执行一次下载)")
    return rc


def parse_args(argv):
    p = argparse.ArgumentParser(
        prog="setup_schedule",
        description="Pixabay 下载器 - Windows 定时任务配置工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python setup_schedule.py --daily 02:00\n"
            "  python setup_schedule.py --hourly 6\n"
            "  python setup_schedule.py --weekly 10:00 SUN\n"
            "  python setup_schedule.py --run-now\n"
            "  python setup_schedule.py --remove\n"
            "  python setup_schedule.py\n"
        ),
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--daily", metavar="HH:MM", help="每天固定时间下载, 如 02:00")
    g.add_argument("--hourly", metavar="N", type=int, help="每隔 N 小时下载")
    g.add_argument("--weekly", metavar="HH:MM DAY", help="每周某天下载, 如 10:00 SUN")
    g.add_argument("--run-now", action="store_true", help="立即触发一次已注册的任务")
    g.add_argument("--remove", action="store_true", help="删除已注册的定时任务")
    p.add_argument("--log", metavar="FILE", default=str(DEFAULT_LOG),
                   help=f"下载日志文件 (默认 {DEFAULT_LOG})")
    p.add_argument("--dry-run", action="store_true", help="只打印命令, 不实际执行")
    return p.parse_args(argv)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    check_windows()
    args = parse_args(argv)
    dry = args.dry_run

    if args.run_now:
        return run_schtasks(["/Run", "/TN", TASK_NAME], dry)
    if args.remove:
        return remove(dry)
    if args.daily:
        return register({"sc": "DAILY", "st": parse_time(args.daily)}, args.log, dry)
    if args.hourly:
        if args.hourly < 1:
            print("错误: 小时数必须 >= 1", file=sys.stderr)
            return 1
        return register({"sc": "HOURLY", "mo": args.hourly}, args.log, dry)
    if args.weekly:
        parts = args.weekly.split()
        if len(parts) != 2 or parts[1].upper() not in WEEKDAYS:
            print("错误: --weekly 格式应为 \"HH:MM DAY\", 例如 \"10:00 SUN\"", file=sys.stderr)
            return 1
        return register({"sc": "WEEKLY", "d": parts[1].upper(),
                         "st": parse_time(parts[0])}, args.log, dry)
    return interactive()


if __name__ == "__main__":
    sys.exit(main())
