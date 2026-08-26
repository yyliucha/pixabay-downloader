# Pixabay 图片下载器

通过 **Pixabay 官方 API** 按关键词批量下载图片到本地。合规、稳定、无需模拟浏览器。

## 特性

- ✅ **官方 API**：不爬网页、不反爬，稳定合规
- ✅ **不重复下载**：双重去重机制
  - 全局下载历史 `download_history.json`（按 Pixabay 图片 ID 记录）：下载过的图片**永远不重复下载**，即使换关键词、换目录、文件被移动过
  - 文件存在检查：目标文件已存在则自动跳过（断点续传）
- ✅ **再次运行自动下载后面的新图**：已下载的自动跳过，自动翻页继续下载后续的新图片，直到该关键词结果全部下完
- ✅ **多线程并发下载**，失败自动重试（3 次，指数退避）
- ✅ 支持**原图 / 大图 / 中等 / 缩略图**四档尺寸
- ✅ 每个关键词目录下生成 `metadata.csv` 元数据清单（图片 ID、来源页、标签、作者、下载地址）
- ✅ 纯 Python 标准库，**无需安装任何第三方包**（Python 3.8+）
- ✅ `--dry-run` 模式：先搜索看看有哪些图，不实际下载

## 目录结构

```
pixabay-downloader/
├── pixabay_downloader.py   # 主程序
├── config.json             # 配置文件（关键词、数量、尺寸、保存路径等）
├── .env.example            # API key 模板（复制为 .env 使用）
├── run.bat                 # Windows 双击运行
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
