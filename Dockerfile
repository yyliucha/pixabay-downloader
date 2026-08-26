# Pixabay 图片下载器 - 定时自动下载容器
# 构建: docker compose build
# 运行: docker compose up -d
FROM python:3.12-alpine

# 默认配置(全部可通过宿主 .env / 环境变量覆盖)
ENV TZ=Asia/Shanghai \
    CRON_EXPRESSION="0 2 * * *" \
    RUN_ON_START="false" \
    PIXABAY_KEYWORDS="山,风景,森林,湖泊,自然" \
    PIXABAY_COUNT="50" \
    PIXABAY_SIZE="original" \
    PIXABAY_IMAGE_TYPE="photo" \
    PIXABAY_SAFE_SEARCH="true" \
    PIXABAY_OUTPUT_DIR="/data/images" \
    PIXABAY_WORKERS="4" \
    PIXABAY_DELAY="0.2" \
    PIXABAY_TIMEOUT="60" \
    PIXABAY_LOG="/data/logs/pixabay_download.log"

# tzdata: 支持 TZ 时区配置(定时任务按容器时区触发)
RUN apk add --no-cache tzdata

WORKDIR /app
COPY pixabay_downloader.py /app/pixabay_downloader.py
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# 图片/日志/下载历史统一存于 /data, 由宿主机目录挂载
VOLUME ["/data"]

ENTRYPOINT ["/app/entrypoint.sh"]
