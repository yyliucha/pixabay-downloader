#!/bin/sh
# Pixabay 下载器容器入口
# 职责: 配置时区 → (可选)启动即下载一次 → 注册定时任务 → 前台运行 cron
set -e

# ---------- 1) 时区 ----------
: "${TZ:=Asia/Shanghai}"
if [ -f "/usr/share/zoneinfo/$TZ" ]; then
    cp "/usr/share/zoneinfo/$TZ" /etc/localtime
    echo "$TZ" > /etc/timezone
    echo "[entrypoint] $(date '+%F %T %Z') 时区: $TZ"
else
    echo "[entrypoint] 警告: 时区 '$TZ' 无效, 使用容器默认时区(UTC)"
    unset TZ
fi

# ---------- 2) 数据目录 ----------
mkdir -p /data/images /data/logs

# ---------- 3) 可选: 启动时立即执行一次(首次部署验证用) ----------
if [ "$RUN_ON_START" = "true" ]; then
    echo "[entrypoint] RUN_ON_START=true, 立即执行一次下载..."
    python /app/pixabay_downloader.py || echo "[entrypoint] 启动时下载失败, 继续启动 cron"
fi

# ---------- 4) 注册定时任务 (cron 表达式: 分 时 日 月 周) ----------
# busybox crond 的 /etc/crontabs/<用户名> 文件无需也不含用户字段(用户名取自文件名)
: "${CRON_EXPRESSION:=0 2 * * *}"
CRON_LINE="$CRON_EXPRESSION /bin/sh -c 'cd /app && python /app/pixabay_downloader.py >> /proc/1/fd/1 2>&1'"
echo "$CRON_LINE" > /etc/crontabs/root
echo "[entrypoint] 定时任务: $CRON_LINE"
echo "[entrypoint] 每次触发自动下载新图(全局去重, 永不重复); 日志见 /data/logs 与 docker logs"

# ---------- 5) 前台运行 cron, 日志输出到容器 stdout ----------
exec crond -f -l 8
