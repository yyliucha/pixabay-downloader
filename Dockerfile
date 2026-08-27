# Pixabay Image Downloader - scheduled download container
# Build:  docker compose build
# Run:    docker compose up -d
FROM python:3.12-alpine

# Defaults (all overridable via host .env / environment variables)
ENV TZ=Asia/Shanghai \
    CRON_EXPRESSION="0 2 * * *" \
    RUN_ON_START="false" \
    PIXABAY_KEYWORDS="mountain,landscape,forest,lake,nature" \
    PIXABAY_COUNT="50" \
    PIXABAY_SIZE="original" \
    PIXABAY_IMAGE_TYPE="photo" \
    PIXABAY_SAFE_SEARCH="true" \
    PIXABAY_OUTPUT_DIR="/data/images" \
    PIXABAY_WORKERS="4" \
    PIXABAY_DELAY="0.2" \
    PIXABAY_TIMEOUT="60" \
    PIXABAY_LOG="/data/logs/pixabay_download.log"

# tzdata: TZ timezone support (scheduled triggers follow the container timezone)
RUN apk add --no-cache tzdata

WORKDIR /app
COPY pixabay_downloader.py /app/pixabay_downloader.py
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Images / logs / download history all live under /data, mounted from the host
VOLUME ["/data"]

ENTRYPOINT ["/app/entrypoint.sh"]
