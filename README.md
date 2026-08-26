# Pixabay 图片下载器 · Pixabay Image Downloader

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED.svg?logo=docker)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![GitHub last commit](https://img.shields.io/github/last-commit/yyliucha/pixabay-downloader)](https://github.com/yyliucha/pixabay-downloader)

通过 **Pixabay 官方 API** 按关键词批量下载图片到本地。合规、稳定、无需模拟浏览器。

> **English**: Batch download images from [Pixabay](https://pixabay.com/) via the official API — keyword search, global dedupe (never re-download the same image), cron-based scheduled downloads, cross-platform, and one-command Docker deployment. Pure Python standard library, no third-party dependencies.

## 特性

- ✅ **官方 API**：不爬网页、不反爬，稳定合规
- ✅ **不重复下载**：双重去重机制
  - 全局下载历史 `download_history.json`（按 Pixabay 图片 ID 记录）：下载过的图片**永远不重复下载**，即使换关键词、换目录、文件被移动过
  - 文件存在检查：目标文件已存在则自动跳过（断点续传）
- ✅ **再次运行自动下载后面的新图**：已下载的自动跳过，自动翻页继续下载后续的新图片，直到该关键词结果全部下完
- ✅ **定时自动下载（cron 表达式，跨平台）**：Linux/macOS 系统 cron、Windows 任务计划程序回退、Docker 容器内置 cron，三端统一 `0 2 * * *` 格式
- ✅ **环境变量全量可配**（`PIXABAY_API_KEY`、关键词、数量、尺寸、目录、日志等），Docker/服务器部署无需改代码
- ✅ **多线程并发下载**，失败自动重试（3 次，指数退避）
- ✅ 支持**原图 / 大图 / 中等 / 缩略图**四档尺寸
- ✅ 每个关键词目录下生成 `metadata.csv` 元数据清单（图片 ID、来源页、标签、作者、下载地址）
- ✅ 纯 Python 标准库，**无需安装任何第三方包**（Python 3.8+）
- ✅ `--dry-run` 模式：先搜索看看有哪些图，不实际下载

## 目录结构

```
pixabay-downloader/
├── pixabay_downloader.py   # 主程序（纯 Python，跨平台）
├── setup_schedule.py       # 跨平台定时任务配置工具（cron 表达式）
├── Dockerfile              # Docker 镜像构建（服务器部署）
├── docker-compose.yml      # Docker 编排（宿主机目录挂载、日志轮转）
├── entrypoint.sh           # 容器入口（时区/cron 注册/日志重定向）
├── .dockerignore
├── config.json             # 配置文件（关键词、数量、尺寸、保存路径等）
├── .env.example            # 宿主配置模板（本地 + Docker 通用，复制为 .env）
├── LICENSE                 # MIT License
├── run.bat                 # Windows 双击运行
├── scheduled_run.bat       # Windows 定时任务启动脚本（setup_schedule.py 自动生成）
├── logs/                   # 运行日志（自动生成）
└── tests/
    └── e2e_test.py         # 本地端到端测试（无需网络、无需 key）
```

## 快速开始

### 第一步：获取 API Key（免费）

1. 打开 https://pixabay.com/accounts/register/ 注册免费账号（也可直接用 Google/Facebook 账号登录）
2. 登录后打开 https://pixabay.com/api/docs/ ，页面里会显示你的 API key
   （格式类似 `1234567-abcdef0123456789abcdef01`）
3. 把本项目里的 `.env.example` 复制一份，改名为 `.env`，填入你的 key：

```
PIXABAY_API_KEY=1234567-abcdef0123456789abcdef01
```

> 也可以不建 `.env`，改为设置系统环境变量 `PIXABAY_API_KEY`，或运行时用 `--key` 参数传入。

### 第二步：配置下载参数（可选）

编辑 `config.json`：

| 配置项 | 说明 | 默认值 |
|---|---|---|
| `keywords` | 搜索关键词列表，每个关键词存一个子目录 | `["山", "风景", "森林", "湖泊", "自然"]` |
| `per_keyword` | 每个关键词下载多少张（再次运行时 = 还要下载多少张新图） | `50` |
| `image_size` | `original`=原图 / `large`=大图(约1280px) / `webformat`=中等(640px) / `preview`=缩略图(150px) | `original` |
| `image_type` | `photo`=照片 / `illustration`=插画 / `vector`=矢量图 / `all`=全部 | `photo` |
| `safe_search` | 安全搜索（过滤不适宜内容） | `true` |
| `output_dir` | 图片保存目录 | `F:/dsh/pixabay_images` |
| `workers` | 并发下载线程数 | `4` |
| `api_delay_seconds` | 两次搜索请求间隔（被限流时调大） | `0.2` |

### 第三步：运行

```bash
# 按 config.json 的配置下载
python pixabay_downloader.py

# 或直接双击 run.bat（Windows）
```

常用参数（优先级高于 config.json）：

```bash
# 指定关键词和数量
python pixabay_downloader.py --keywords "山,风景" --count 100

# 下载大图（约1280px）到指定目录
python pixabay_downloader.py --size large --output D:/pictures

# 只搜索不下载，先看看有哪些图片
python pixabay_downloader.py --dry-run

# 安静模式（不打印每张图的进度）
python pixabay_downloader.py --quiet
```

## 再次运行：下载后面的图片

直接**再运行一次**即可，不需要任何额外操作：

- 程序会自动跳过所有已下载过的图片（依据 `download_history.json`），自动翻页**继续下载后面的新图**
- `per_keyword` / `--count` 表示"还要下载多少张**新**图"
- 该关键词的结果全部下完后，会提示 `没有新的图片可下载`

示例：第一次 `--count 50` 下载了前 50 张 → 再次运行 `--count 50` 就会继续下载第 51~100 张 → 每多跑一次就往后多下 50 张，永不重复。

## 定时自动下载（cron 表达式，跨平台）

统一使用 **cron 表达式（分 时 日 月 周）** 调度，三个平台一致：

| 平台 | 调度方式 |
|---|---|
| Linux / macOS | 系统 cron（`crontab` 命令，用户级，无需 root） |
| Windows | 无原生 cron，自动回退到任务计划程序（schtasks） |
| Docker | 容器内置 cron（`CRON_EXPRESSION` 环境变量） |

结合「再次运行自动下载新图」机制，定时任务每次触发都会自动下载一批新图，**长期运行 = 图片持续自动积累，永不重复**。

### 注册定时任务

```bash
python setup_schedule.py --daily 02:00          # 每天 02:00 自动下载
python setup_schedule.py --hourly 6             # 每 6 小时下载一次
python setup_schedule.py --weekly "10:00 SUN"   # 每周日 10:00
python setup_schedule.py --cron "0 */2 * * *"   # 直接使用 cron 表达式(与 Docker CRON_EXPRESSION 一致)
python setup_schedule.py                        # 交互式引导
```

### 管理定时任务

```bash
python setup_schedule.py --list                 # 查看当前定时任务
python setup_schedule.py --remove               # 删除定时任务
python setup_schedule.py --dry-run              # 只打印将要执行的命令, 不实际注册
```

### 平台说明

- **Linux / macOS**：写入用户 crontab（带 `# >>> PixabayDownloader start/end` 标记块，重复注册自动替换，不影响你已有的其它 cron 条目）；命令输出重定向到 `logs/cron_stdout.log`，下载明细写入 `logs/pixabay_download.log`；需要系统已安装 cron（主流发行版默认自带）
- **Windows**：系统无原生 cron，自动使用任务计划程序（schtasks）回退，任务名 `PixabayDownloader`，默认仅当用户登录时运行；cron 表达式中含「月/日」限定（如 `0 2 15 * *`）时 Windows 无法表达，会提示改用 Docker 或 Linux/macOS
- **Docker**：容器内置 busybox cron，`CRON_EXPRESSION` 环境变量即 cron 表达式（默认 `0 2 * * *`），时区由 `TZ` 控制，日志见 `/data/logs` 与 docker logs
- 每次触发会按 `config.json` 自动下载下一批新图（每关键词 `per_keyword` 张）；下载完该关键词全部结果后会自动跳过，不影响其他关键词
- 修改项目路径或升级 Python 后，请重新运行 `setup_schedule.py` 刷新任务

## Docker 部署（服务器定时下载，推荐）

容器内置 cron，每天固定时间自动下载新图（全局去重，永不重复），适合部署到 Linux 服务器长期运行。

### 快速开始

```bash
# 1. 克隆项目
git clone https://github.com/yyliucha/pixabay-downloader.git
cd pixabay-downloader

# 2. 复制宿主配置文件并填写（重点是 PIXABAY_API_KEY）
cp .env.example .env
vi .env

# 3. 启动（首次建议设 RUN_ON_START=true，启动即下载一次验证）
docker compose up -d --build

# 4. 查看日志
docker compose logs -f
```

### 宿主配置（.env 文件，全部可选覆盖）

| 变量 | 说明 | 默认值 |
|---|---|---|
| `PIXABAY_API_KEY` | **必填**，Pixabay API key | 无 |
| `PIXABAY_KEYWORDS` | 搜索关键词，逗号分隔 | `山,风景,森林,湖泊,自然` |
| `PIXABAY_COUNT` | 每个关键词下载的新图数量 | `50` |
| `PIXABAY_SIZE` | `original`/`large`/`webformat`/`preview` | `original` |
| `PIXABAY_IMAGE_TYPE` | `photo`/`illustration`/`vector`/`all` | `photo` |
| `PIXABAY_SAFE_SEARCH` | `true`/`false` | `true` |
| `PIXABAY_WORKERS` | 并发下载线程数 | `4` |
| `PIXABAY_DELAY` | API 请求间隔秒（429 限流时调大） | `0.2` |
| `PIXABAY_TIMEOUT` | 单图下载超时秒 | `60` |
| `TZ` | 容器时区（**定时触发时间按此时区**） | `Asia/Shanghai` |
| `CRON_EXPRESSION` | cron 表达式：分 时 日 月 周 | `0 2 * * *`（每天 02:00） |
| `RUN_ON_START` | 启动时立即下载一次（`true`/`false`） | `false` |
| `PIXABAY_HOST_IMAGES_DIR` | **宿主机图片保存目录** | `./pixabay_images` |
| `PIXABAY_HOST_LOG_DIR` | **宿主机日志保存目录** | `./logs` |

> 配置优先级：命令行参数 > 环境变量 > `config.json` > 默认值。如需更多控制，可把 `config.json` 挂载进容器（docker-compose.yml 已预置 `./config.json:/app/config.json:ro`）。

### 日志与数据

- **完整日志双通道**：容器内 `/data/logs/pixabay_download.log`（挂载到宿主机 `./logs/`，含每次运行的时间戳、搜索/下载/去重/失败明细）+ `docker compose logs`（stdout 同步输出，含 cron 触发记录）
- 图片保存：宿主机 `./pixabay_images/关键词/`（按关键词分子目录 + `metadata.csv` + 全局去重记录 `download_history.json`）
- 修改配置：编辑 `.env` 后 `docker compose up -d` 生效（无需重建镜像）
- 更新代码：`git pull` 后 `docker compose up -d --build`
- 删除服务：`docker compose down`（宿主机图片/日志保留）

### 常用管理命令

```bash
docker compose logs -f                 # 实时查看日志
docker compose exec pixabay-downloader cat /etc/crontabs/root   # 查看容器内定时任务
docker compose exec pixabay-downloader python pixabay_downloader.py --dry-run  # 试运行(只搜索不下载)
docker compose restart                  # 重启
```

### 从 Docker Hub 拉取镜像部署（无需克隆/构建）

镜像由 **GitHub Actions 自动构建并推送**到 Docker Hub（推 `main` → `latest`；打 `v*` 标签 → `vX.Y.Z` + `latest`，支持 linux/amd64 与 linux/arm64）。镜像就绪后，服务器上**无需克隆仓库、无需构建**：

```bash
# 方式一: docker run 一条命令部署(每天 02:00 自动下载)
docker run -d --name pixabay-downloader --restart unless-stopped \
  -e PIXABAY_API_KEY=你的PixabayKey \
  -e TZ=Asia/Shanghai \
  -e CRON_EXPRESSION="0 2 * * *" \
  -e PIXABAY_KEYWORDS="山,风景,森林" \
  -v /服务器/图片目录:/data/images \
  -v /服务器/日志目录:/data/logs \
  <DockerHub用户名>/pixabay-downloader:latest

# 方式二: compose 方式(推荐, 配置更清晰) —— 编辑 docker-compose.yml:
#   将 `build: .` 行删除, 并把 image 改为: <DockerHub用户名>/pixabay-downloader:latest
#   然后: docker compose up -d   (自动拉取镜像)
```

**镜像自动构建的配置方法**（一次性，约 2 分钟）：

1. 登录 [Docker Hub](https://hub.docker.com) → Account Settings → Security → **New Access Token**（权限选 **Read & Write**）
2. GitHub 仓库 → Settings → Secrets and variables → Actions → **New repository secret**，添加两个：
   - `DOCKERHUB_USERNAME` = 你的 Docker Hub 用户名
   - `DOCKERHUB_TOKEN` = 上一步生成的 token
3. 完成后，**推一次 `main` 或打 `v*` 标签**即自动构建推送；未配置前工作流会自动跳过，不影响其它功能

### 从镜像更新的注意事项

- 镜像默认配置与源码一致：所有 `PIXABAY_*` 环境变量、`TZ`、`CRON_EXPRESSION`、`RUN_ON_START` 均可用
- 镜像内不含 `config.json`（用环境变量配置即可）；如需挂载自定义配置，用 `-v /路径/config.json:/app/config.json:ro`

## 输出说明

```
F:/dsh/pixabay_images/
├── download_history.json   # 全局下载历史（去重依据，可删除以重置去重记录）
├── 山/
│   ├── 1234567.jpg         # 图片文件（以 Pixabay 图片 ID 命名）
│   ├── 7654321.png
│   └── metadata.csv        # 元数据清单（ID/来源页/标签/作者/地址/状态）
└── 风景/
    └── metadata.csv        # 若图片都已下载过，则只记录跳过信息
```

## 常见问题

| 问题 | 解决办法 |
|---|---|
| `API key 无效... Invalid API key` | key 填错了或没复制全，重新检查 `.env`（注意大小写敏感） |
| 中文关键词结果很少 | Pixabay 英文标签更全，试试 `mountain` / `landscape` / `forest` 等英文词 |
| 提示 429 限流 | 把 `config.json` 里的 `api_delay_seconds` 调大到 `1` 或更高 |
| 部分图片下载失败 | 程序会自动重试 3 次；重跑一次即可，已成功的会自动跳过 |
| 想继续下载同一关键词后面的图片 | 直接再运行一次即可，程序会自动跳过已下载的、继续下载后续新图，直到全部下完 |
| 想重新下载已下载过的图 | 删除保存目录下的 `download_history.json`（或整个关键词子目录）后重跑 |
| 定时任务没到点不运行 | 电脑关机/睡眠时任务不会执行。Windows 可勾选「如果错过了计划开始时间, 立即启动任务」；Linux 可用 anacron 补跑 |
| 下载的是 SVG 矢量图 | 把 `image_type` 改为 `photo`（默认即照片） |

## 本地测试（可选）

无需网络、无需 API key，用本地模拟服务器验证全部功能（下载、去重、断点续传、环境变量配置、dry-run）：

```bash
python tests/e2e_test.py
python tests/test_cron_expr.py   # cron 表达式与跨平台调度逻辑单元测试
```

预期输出：`ALL TESTS PASSED ✔` / `ALL CRON TESTS PASSED ✔`

## 合规说明

- 本项目代码以 **MIT License** 开源（见 `LICENSE`）；下载的图片遵循 [Pixabay Content License](https://pixabay.com/service/license-summary/)，可免费用于商业与非商业用途。
- 本项目使用 Pixabay 官方 API，请遵守 [Pixabay API 文档](https://pixabay.com/api/docs/) 与 [服务条款](https://pixabay.com/service/terms/)。
- 通过 API 获取图片时，建议保留作者与来源信息（`metadata.csv` 已自动记录），并控制合理请求频率。
