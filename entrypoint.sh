#!/bin/sh
# Pixabay Downloader container entrypoint
# Tasks: configure timezone -> (optional) run once on start -> register cron -> run cron in foreground
set -e

# ---------- 1) Timezone ----------
: "${TZ:=Asia/Shanghai}"
if [ -f "/usr/share/zoneinfo/$TZ" ]; then
    cp "/usr/share/zoneinfo/$TZ" /etc/localtime
    echo "$TZ" > /etc/timezone
    echo "[entrypoint] $(date '+%F %T %Z') timezone: $TZ"
else
    echo "[entrypoint] Warning: timezone '$TZ' is invalid, using container default (UTC)"
    unset TZ
fi

# ---------- 2) Data directories ----------
mkdir -p /data/images /data/logs

# ---------- 3) Optional: run one download on start (first deployment verification) ----------
if [ "$RUN_ON_START" = "true" ]; then
    echo "[entrypoint] RUN_ON_START=true, running one download now..."
    python /app/pixabay_downloader.py || echo "[entrypoint] Startup download failed, continuing to start cron"
fi

# ---------- 4) Register the cron job (cron expression: min hour dom month dow) ----------
# busybox crond reads /etc/crontabs/<username>; the user comes from the file name,
# so no user field is included in the line
: "${CRON_EXPRESSION:=0 12 27 * *}"
CRON_LINE="$CRON_EXPRESSION /bin/sh -c 'cd /app && python /app/pixabay_downloader.py >> /proc/1/fd/1 2>&1'"
echo "$CRON_LINE" > /etc/crontabs/root
echo "[entrypoint] Cron job: $CRON_LINE"
echo "[entrypoint] Each trigger downloads new images only (global dedupe); logs: /data/logs and docker logs"

# ---------- 5) Run cron in the foreground, output to container stdout ----------
exec crond -f -l 8
