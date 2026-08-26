# Pixabay 图片下载器

通过 **Pixabay 官方 API** 按关键词批量下载图片到本地。合规、稳定、无需模拟浏览器。

## 特性

- ✅ **官方 API**：不爬网页、不反爬，稳定合规
- ✅ **不重复下载**：双重去重机制
  - 全局下载历史 `download_history.json`（按 Pixabay 图片 ID 记录）：下载过的图片**永远不重复下载**，即使换关键词、换目录、文件被移动过
  - 文件存在检查：目标文件已存在则自动跳过（断点续传）
- ✅ **再次运行自动下载后面的新图**：已下载的自动跳过，自动翻页继续下载后续的新图片，直到该关键词结果全部下完
- ✅ **定时自动下载**：Windows 一键注册系统定时任务；**Docker 一键部署到服务器**（每天/每N小时/每周，时区可配）
- ✅ **环境变量全量可配**（`PIXABAY_API_KEY`、关键词、数量、尺寸、目录、日志等），Docker/服务器部署无需改代码
- ✅ **多线程并发下载**，失败自动重试（3 次，指数退避）
- ✅ 支持**原图 / 大图 / 中等 / 缩略图**四档尺寸
- ✅ 每个关键词目录下生成 `metadata.csv` 元数据清单（图片 ID、来源页、标签、作者、下载地址）
- ✅ 纯 Python 标准库，**无需安装任何第三方包**（Python 3.8+）
- ✅ `--dry-run` 模式：先搜索看看有哪些图，不实际下载

## 目录结构

```
pixabay-downloader/
├── pixabay_downloader.py   # 主程序
├── setup_schedule.py       # Windows 定时任务配置工具（可选）
├── Dockerfile              # Docker 镜像构建（服务器部署）
├── docker-compose.yml      # Docker 编排（宿主机目录挂载、日志轮转）
├── entrypoint.sh           # 容器入口（时区/cron 注册/日志重定向）
├── .dockerignore
├── config.json             # 配置文件（关键词、数量、尺寸、保存路径等）
├── .env.example            # 宿主配置模板（本地 + Docker 通用，复制为 .env）
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

## 定时自动下载（Windows）

结合「再次运行自动下载新图」机制，定时任务每次触发都会自动下载一批新图，**长期运行 = 图片持续自动积累，永不重复**。

### 注册定时任务

```bash
python setup_schedule.py --daily 02:00        # 每天 02:00 自动下载
python setup_schedule.py --hourly 6           # 每 6 小时下载一次
python setup_schedule.py --weekly "10:00 SUN" # 每周日 10:00
python setup_schedule.py                      # 交互式引导（推荐新手）
```

### 管理定时任务

```bash
python setup_schedule.py --run-now            # 立即触发一次（测试用）
python setup_schedule.py --remove             # 删除定时任务
schtasks /Query /TN PixabayDownloader         # 查看任务状态
```

### 说明

- 任务通过 **Windows 任务计划程序**注册，任务名称为 `PixabayDownloader`，默认**仅当用户登录时运行**
- 任务调用自动生成的 `scheduled_run.bat`（已固化 Python 与脚本路径），运行输出追加写入 `logs/pixabay_download.log`（`--log` 参数，控制台+文件双写）
- 每次触发会按 `config.json` 自动下载下一批新图（每关键词 `per_keyword` 张）；下载完该关键词全部结果后会自动跳过，不影响其他关键词
- 修改项目路径或升级 Python 后，请重新运行 `setup_schedule.py` 刷新任务
- 若需「开机未登录也运行」：打开任务计划程序 → 找到 PixabayDownloader → 属性 → 勾选「不管用户是否登录都要运行」（需设置密码）

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
| 定时任务没到点不运行 | 默认「仅当用户登录时运行」；电脑关机/睡眠/未登录时任务不会执行，开机后会错过（如需开机即补跑，可在任务计划程序中勾选「如果错过了计划开始时间, 立即启动任务」） |
| 下载的是 SVG 矢量图 | 把 `image_type` 改为 `photo`（默认即照片） |

## 本地测试（可选）

无需网络、无需 API key，用本地模拟服务器验证全部功能（下载、去重、断点续传、dry-run）：

```bash
python tests/e2e_test.py
```

预期输出：`ALL TESTS PASSED ✔`

## 合规说明

- 本项目使用 Pixabay 官方 API，请遵守 [Pixabay API 文档](https://pixabay.com/api/docs/) 与 [服务条款](https://pixabay.com/service/terms/)。
- Pixabay 图片遵循 [Pixabay Content License](https://pixabay.com/service/license-summary/)，可免费用于商业与非商业用途。
- 通过 API 获取图片时，建议保留作者与来源信息（`metadata.csv` 已自动记录），并控制合理请求频率。
