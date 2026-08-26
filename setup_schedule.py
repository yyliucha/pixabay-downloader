#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pixabay 下载器 - 跨平台定时任务配置工具
========================================
统一使用 cron 表达式(分 时 日 月 周)调度, 跨平台:

  * Linux / macOS : 系统 cron (crontab 命令), 用户级 crontab, 无需管理员权限
  * Windows        : 无原生 cron, 自动回退到任务计划程序 (schtasks)
  * Docker         : 容器内置 cron (docker-compose 的 CRON_EXPRESSION 环境变量)

三种方式使用同一套 cron 表达式, 例如每天 02:00 = "0 2 * * *"。

用法:
  python setup_schedule.py --daily 02:00          # 每天 02:00
  python setup_schedule.py --hourly 6             # 每 6 小时
  python setup_schedule.py --weekly "10:00 SUN"   # 每周日 10:00
  python setup_schedule.py --cron "0 */2 * * *"   # 直接指定 cron 表达式(与 Docker 一致)
  python setup_schedule.py --list                 # 查看当前注册的定时任务
  python setup_schedule.py --remove               # 删除定时任务
  python setup_schedule.py --dry-run              # 只打印将执行的命令, 不实际注册
  python setup_schedule.py                        # 交互式引导
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
DAY_CN = {"SUN": "周日", "MON": "周一", "TUE": "周二", "WED": "周三",
          "THU": "周四", "FRI": "周五", "SAT": "周六"}


# ---------------------------------------------------------------- cron 表达式

def valid_time(s):
    return bool(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", s))


def valid_cron(expr):
    """校验 cron 表达式: 5 个字段, 格式与取值范围(轻量校验)。"""
    parts = expr.split()
    if len(parts) != 5:
        return False
    limits = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]  # 分 时 日 月 周
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
    """把友好时间描述转换为 cron 表达式(与 Docker CRON_EXPRESSION 格式一致)。"""
    if daily:
        hh, mm = daily.split(":")
        return f"{int(mm)} {int(hh)} * * *"
    if hourly:
        return f"0 */{hourly} * * *"
    if weekly:
        time_str, day = weekly
        hh, mm = time_str.split(":")
        return f"{int(mm)} {int(hh)} * * {WEEKDAY_MAP[day]}"
    raise ValueError("必须提供 daily / hourly / weekly 之一")


def describe_cron(expr):
    """把 cron 表达式转成人类可读描述。"""
    mm, hh, dom, mon, dow = expr.split()
    if dow != "*":
        day_key = next((k for k, v in WEEKDAY_MAP.items() if str(v) == dow), dow)
        return f"每周{DAY_CN.get(day_key, day_key)} {int(hh):02d}:{int(mm):02d}"
    if mm == "0" and (hh == "*" or hh.startswith("*/")):
        m = re.fullmatch(r"\*/(\d+)", hh)
        if m:
            return f"每 {m.group(1)} 小时"
        return "每小时"
    if dom == "*" and mon == "*":
        return f"每天 {int(hh):02d}:{int(mm):02d}"
    return f"cron({expr})"


# ---------------------------------------------------------------- 通用

def check_required_deps():
    if not IS_WINDOWS:
        try:
            subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
        except FileNotFoundError:
            print("错误: 未找到 crontab 命令, 请先安装 cron (如 Debian/Ubuntu: apt install cron)", file=sys.stderr)
            sys.exit(1)


def run_cmd(cmd, dry_run=False, **kwargs):
    """执行命令; dry_run 时只打印不执行。"""
    print("执行: " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
    if dry_run:
        print("[dry-run] 未实际执行。")
        return 0, "", ""
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kwargs)
    if r.stdout.strip():
        print(r.stdout.strip())
    if r.stderr.strip():
        print(r.stderr.strip(), file=sys.stderr)
    return r.returncode, r.stdout, r.stderr


def build_cron_command(log_path):
    """构建 cron 执行的命令行(带日志重定向, 防止 cron 邮件丢失输出)。"""
    py = shlex.quote(str(sys.executable))
    script = shlex.quote(str(DOWNLOADER))
    log = shlex.quote(str(Path(log_path).resolve()))
    cron_stdout = shlex.quote(str(Path(log_path).resolve().with_name("cron_stdout.log")))
    return f"{py} {script} --quiet --log {log} >> {cron_stdout} 2>&1"


# ---------------------------------------------------------------- Linux/macOS: 系统 cron

def get_crontab():
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode == 0:
        return r.stdout
    return ""  # 没有 crontab 时 crontab -l 返回非 0


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
    print(f"定时任务: {expr}  ({describe_cron(expr)})")
    if dry_run:
        print("将写入用户 crontab:")
        print(new_text)
        return 0
    rc, _, err = run_cmd(["crontab", "-"], dry_run=False, input=new_text)
    if rc != 0:
        print(f"crontab 安装失败: {err.strip()}", file=sys.stderr)
        return 1
    print("✔ 已写入用户 crontab(带标记块, 重复注册会自动替换)")
    return 0


def remove_posix(dry_run=False):
    check_required_deps()
    existing = get_crontab()
    if not has_block(existing):
        print("未找到已注册的定时任务(无 PixabayDownloader 标记块)")
        return 0
    new_text = remove_old_block(existing)
    if dry_run:
        start = existing.index("# >>>")
        end = existing.index("# <<<") + len("# <<< PixabayDownloader end")
        print("将删除的标记块:")
        print(existing[start:end])
        print("---- 删除后的 crontab ----")
        print(new_text)
        return 0
    rc, _, err = run_cmd(["crontab", "-"], input=new_text)
    if rc != 0:
        print(f"crontab 更新失败: {err.strip()}", file=sys.stderr)
        return 1
    print("✔ 已从 crontab 删除 PixabayDownloader 定时任务")
    return 0


def list_posix():
    check_required_deps()
    existing = get_crontab()
    if has_block(existing):
        start = existing.index("# >>>")
        end = existing.index("# <<<") + len("# <<< PixabayDownloader end")
        print("当前定时任务:")
        print(existing[start:end])
    else:
        print("未注册 PixabayDownloader 定时任务")


# ---------------------------------------------------------------- Windows: 任务计划程序(回退)

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
    # schtasks 无法表达任意 cron 表达式, 由 cron 表达式转 schtasks 参数
    mm, hh, dom, mon, dow = expr.split()
    if mon != "*" or dom != "*":
        print("错误: Windows 任务计划程序无法表达该 cron 表达式(含 月/日 限定), "
              "建议在 Docker(内置 cron)或 Linux/macOS(系统 cron)上运行", file=sys.stderr)
        return 2
    if dow != "*":
        cmd[cmd.index("/SC") + 1] = "WEEKLY"
        cmd += ["/D", next(k for k, v in WEEKDAY_MAP.items() if str(v) == dow)]
        st = f"{int(hh):02d}:{int(mm):02d}"
    elif hh.startswith("*/"):
        cmd[cmd.index("/SC") + 1] = "HOURLY"
        cmd += ["/MO", hh.split("/")[1]]
        st = "00:00"  # HOURLY 的 /ST 是起始时间, 间隔由 /MO 控制
    else:
        st = f"{int(hh):02d}:{int(mm):02d}"
    cmd[cmd.index("/ST") + 1] = st
    print(f"定时任务: {expr}  ({describe_cron(expr)})")
    print("注: Windows 无原生 cron, 使用任务计划程序(schtasks)作为回退")
    rc, _, _ = run_cmd(cmd, dry_run=dry_run)
    if rc != 0 or dry_run:
        return rc
    rc, _, _ = run_cmd(["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST"])
    if rc == 0:
        print(f"✔ 定时任务已就绪: {TASK_NAME}")
    return rc


def remove_windows(dry_run=False):
    return run_cmd(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], dry_run=dry_run)[0]


def list_windows():
    rc, out, _ = run_cmd(["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST"])
    if rc != 0:
        print("未注册 PixabayDownloader 定时任务")


# ---------------------------------------------------------------- 入口

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
        print(f"错误: 时间格式应为 HH:MM(24小时制), 例如 02:00", file=sys.stderr)
        sys.exit(1)
    return t


def interactive():
    print("=" * 52)
    print("Pixabay 下载器 - 定时任务设置 (cron 表达式, 跨平台)")
    print("=" * 52)
    print("请选择定时方式:")
    print("  1) 每天固定时间 (如 02:00)")
    print("  2) 每隔 N 小时 (如每 6 小时)")
    print("  3) 每周某天 (如周日 10:00)")
    print("  4) 自定义 cron 表达式 (如 0 */2 * * *)")
    print("  5) 查看当前定时任务")
    print("  6) 删除定时任务")
    choice = input("输入编号 [1]: ").strip() or "1"
    if choice == "6":
        return remove()
    if choice == "5":
        return list_tasks()
    if choice == "4":
        expr = input("cron 表达式 (分 时 日 月 周) [0 2 * * *]: ").strip() or "0 2 * * *"
        if not valid_cron(expr):
            print(f"错误: cron 表达式 '{expr}' 格式不正确", file=sys.stderr)
            return 1
        return install(expr, DEFAULT_LOG)
    if choice == "2":
        n = input("每隔几小时 [6]: ").strip() or "6"
        if not n.isdigit() or int(n) < 1:
            print("错误: 请输入正整数小时数", file=sys.stderr)
            return 1
        return install(to_cron_expr(hourly=int(n)), DEFAULT_LOG)
    if choice == "3":
        day = input(f"星期几 [{', '.join(WEEKDAYS)}]: ").strip().upper()
        if day not in WEEKDAY_MAP:
            print("错误: 星期几应为 " + "/".join(WEEKDAYS), file=sys.stderr)
            return 1
        t = parse_time(input("几点开始 (HH:MM) [10:00]: ").strip() or "10:00")
        return install(to_cron_expr(weekly=(t, day)), DEFAULT_LOG)
    t = parse_time(input("几点下载 (HH:MM) [02:00]: ").strip() or "02:00")
    return install(to_cron_expr(daily=t), DEFAULT_LOG)


def parse_args(argv):
    p = argparse.ArgumentParser(
        prog="setup_schedule",
        description="Pixabay 下载器 - 跨平台定时任务配置工具 (cron 表达式: 分 时 日 月 周)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python setup_schedule.py --daily 02:00\n"
            "  python setup_schedule.py --hourly 6\n"
            "  python setup_schedule.py --weekly \"10:00 SUN\"\n"
            "  python setup_schedule.py --cron \"0 */2 * * *\"\n"
            "  python setup_schedule.py --list\n"
            "  python setup_schedule.py --remove\n"
        ),
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--daily", metavar="HH:MM", help="每天固定时间, 如 02:00")
    g.add_argument("--hourly", metavar="N", type=int, help="每隔 N 小时")
    g.add_argument("--weekly", metavar="'HH:MM DAY'", help="每周某天, 如 '10:00 SUN'")
    g.add_argument("--cron", metavar="EXPR", help="直接使用 cron 表达式, 如 \"0 2 * * *\" (与 Docker CRON_EXPRESSION 一致)")
    g.add_argument("--list", action="store_true", help="查看当前定时任务")
    g.add_argument("--remove", action="store_true", help="删除定时任务")
    p.add_argument("--log", metavar="FILE", default=str(DEFAULT_LOG),
                   help=f"下载日志文件 (默认 {DEFAULT_LOG})")
    p.add_argument("--dry-run", action="store_true", help="只打印将执行的命令, 不实际注册")
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
            print(f"错误: cron 表达式 '{expr}' 格式不正确(应为 5 个字段: 分 时 日 月 周)", file=sys.stderr)
            return 1
        return install(expr, args.log, dry)
    if args.daily:
        return install(to_cron_expr(daily=parse_time(args.daily)), args.log, dry)
    if args.hourly:
        if args.hourly < 1:
            print("错误: 小时数必须 >= 1", file=sys.stderr)
            return 1
        return install(to_cron_expr(hourly=args.hourly), args.log, dry)
    if args.weekly:
        parts = args.weekly.split()
        if len(parts) != 2 or parts[1].upper() not in WEEKDAY_MAP:
            print("错误: --weekly 格式应为 \"HH:MM DAY\", 例如 \"10:00 SUN\"", file=sys.stderr)
            return 1
        return install(to_cron_expr(weekly=(parse_time(parts[0]), parts[1].upper())), args.log, dry)
    return interactive()


if __name__ == "__main__":
    sys.exit(main())
