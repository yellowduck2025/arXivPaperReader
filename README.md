# arXiv Paper Analyzer

arXiv 论文分析工作台 — 搜索、下载、AI 提取 Idea 标签、统计聚类，支持 GUI 和命令行两种使用方式。

## 功能概览

- **arXiv 搜索** — 按关键词、标题、摘要、作者、分类搜索，支持日期范围和布尔运算
- **PDF 下载与解析** — 自动下载论文 PDF，用 PyMuPDF + pdfplumber 提取全文
- **AI 深度分析** — 调用 DeepSeek API 提取创新点、方法、实验、数据集、局限等结构化信息
- **Idea 标签系统** — 自动生成 idea tags，支持手动编辑、合并、删除、批量重分析
- **统计与聚类** — 标签频次统计 + 基于编辑距离的相似标签聚类
- **翻译支持** — 内置 7 种翻译后端（LLM / Google / Bing / DeepL / 百度 / 腾讯 / 自定义）
- **双模式** — GUI 桌面应用 + 命令行 pipeline

## 环境要求

- Python 3.11+
- DeepSeek API Key（或其他 OpenAI 兼容接口）

## 快速开始

### 1. 克隆项目

```bash
git clone <repo-url>
cd arXivPaperReader
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
pip install customtkinter
```

### 3. 配置 API Key

```bash
cp .env.example .env
```

编辑 `.env`，填入你的 DeepSeek API Key：

```ini
DEEPSEEK_API_KEY=sk-your-key-here
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
```

> 支持任意 OpenAI 兼容接口，修改 `DEEPSEEK_BASE_URL` 即可切换到其他服务商。

### 4. 启动

**GUI 模式：**

```bash
python gui.py
```

**命令行模式：**

```bash
# 搜索 + 下载 + 分析一条龙
python main.py run -q "large language model agent" -n 20

# 只看搜索结果
python main.py search -q "diffusion model" -n 10

# 对已有 CSV 做统计
python main.py stats
```

## GUI 使用指南

### 主界面布局

```
┌────────────── 左侧面板 ──────────────┐  ┌───── 右侧面板 ─────┐
│  [搜索栏]                             │  │  [论文列表]         │
│  [搜索按钮] [仅下载] [仅基础信息]      │  │  [搜索/过滤]        │
│  [仅摘要分析] [全文分析]              │  │                    │
│                                       │  │  [详情面板]         │
│  [进度与状态]                         │  │   - 论文信息        │
│                                       │  │   - AI 分析结果     │
│  [日志输出区]                         │  │   - 翻译面板        │
│                                       │  │                    │
│  [Idea 标签统计树]                    │  │                    │
│  [聚类树]                             │  │                    │
└───────────────────────────────────────┘  └────────────────────┘
```

### 基本工作流

1. **搜索论文** — 在搜索栏输入关键词（如 `reinforcement learning`），点击搜索
2. **选择分析模式** — 可以选择仅下载 PDF、仅提取基础信息（不消耗 token）、仅摘要分析（省 token）、全文分析（最详尽）
3. **查看结果** — 右侧论文列表显示所有结果，点击可查看详细信息
4. **管理标签** — 在 Idea 标签树中右键可编辑、合并、删除标签
5. **导出数据** — 支持导出 CSV 和统计结果

### 论文分析字段

AI 会为每篇论文提取以下结构化信息：

| 字段 | 说明 |
|------|------|
| Innovation | 核心创新点 |
| Method | 方法概述 |
| Experiments | 实验设计 |
| Datasets | 使用的数据集 |
| Metrics | 评估指标 |
| Results | 关键结果 |
| Limitations | 局限性 |
| Idea Tags | 自动提取的简洁标签 |
| Evidence | 支持结论的证据 |
| Confidence | 置信度评分 |

### 翻译功能

在论文详情面板中选中英文文本即可翻译。支持的后端：

| 后端 | 需要配置 | 费用 |
|------|----------|------|
| Google | 无需配置 | 免费 |
| LLM | API Key | 按 token |
| Bing | API Key + Region | 按量 |
| DeepL | API Key | 免费/付费 |
| 百度 | APPID + SecretKey | 按量 |
| 腾讯 | SecretId + SecretKey | 按量 |
| 自定义 | URL + API Key | 视服务而定 |

在 GUI 中 **设置 → 翻译设置** 可切换后端和填写密钥。

### 数据存储

```
outputs/
  pdfs/                  # 下载的 PDF 文件
  arxiv_analysis.csv     # AI 分析结果
  idea_frequency.csv     # Idea 标签频次统计
  idea_clusters.csv      # Idea 标签聚类结果
logs/
  pipeline.log           # 运行日志
```

## 命令行用法

### 完整 Pipeline

```bash
python main.py run \
  -q "graph neural network" \
  -f ti abs \
  -n 30 \
  --operator AND \
  --sort-by submittedDate \
  -d 20240101 20241231
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-q` | 搜索关键词（必填） | — |
| `-f` | 搜索字段：ti/abs/au/cat | ti, abs |
| `-n` | 最大结果数 | 50 |
| `--operator` | 关键词逻辑：AND/OR/ANDNOT | AND |
| `--sort-by` | 排序：relevance/lastUpdatedDate/submittedDate | relevance |
| `-d` | 日期范围 YYYYMMDD YYYYMMDD | 不限 |
| `--no-download` | 跳过 PDF 下载，仅用摘要分析 | false |
| `--no-resume` | 忽略 CSV 已有记录，重新分析 | false |
| `--dry-run` | 仅显示查询不发起请求 | false |
| `--model` | 指定模型 | .env 中的值 |
| `-v` | 详细日志 | false |

### 仅搜索

```bash
python main.py search -q "transformer attention" -n 20
```

### 统计已有数据

```bash
python main.py stats
```

## 项目结构

```
arXivPaperReader/
  gui.py                  # GUI 主程序 (CustomTkinter)
  main.py                 # CLI 入口
  src/
    config.py             # 配置管理（从 .env 加载）
    models.py             # 数据模型
    searcher.py           # arXiv API 搜索
    downloader.py         # PDF 下载
    parser.py             # PDF 解析 (PyMuPDF + pdfplumber)
    extractor.py          # AI 提取 (DeepSeek API)
    csv_writer.py         # CSV 读写
    stats.py              # 标签统计与聚类
    translator.py         # 多后端翻译
    orchestrator.py       # Pipeline 编排
  outputs/                # 输出文件
  logs/                   # 日志
  .env.example            # 配置模板
```

## 打包为 exe（无需安装 Python）

```bash
# 创建干净的虚拟环境
conda create -n build python=3.11 -y
conda activate build

# 安装依赖
pip install -r requirements.txt
pip install customtkinter pyinstaller

# 打包
python -m PyInstaller --onefile --noconsole --name "arXivPaperReader" \
  --collect-all customtkinter \
  --add-binary "path/to/tcl86t.dll;." \
  --add-binary "path/to/tk86t.dll;." \
  --add-binary "path/to/libssl-3-x64.dll;." \
  --add-binary "path/to/libcrypto-3-x64.dll;." \
  --hidden-import src.searcher \
  --hidden-import src.downloader \
  --hidden-import src.parser \
  --hidden-import src.extractor \
  --hidden-import src.csv_writer \
  --hidden-import src.stats \
  --hidden-import src.models \
  --hidden-import src.config \
  --hidden-import src.translator \
  --hidden-import src.orchestrator \
  --hidden-import requests \
  --hidden-import deep_translator \
  gui.py

# 使用：复制 .env 到 dist/，双击 arXivPaperReader.exe
```

## 依赖项

| 包 | 用途 |
|----|------|
| customtkinter | GUI 框架 |
| openai | DeepSeek API 调用 |
| pymupdf | PDF 文本提取 |
| pdfplumber | PDF 表格/文本提取 |
| httpx | HTTP 请求 |
| lxml | arXiv Atom XML 解析 |
| pandas | 数据处理与统计 |
| textdistance | Idea 标签相似度聚类 |
| tenacity | 网络请求重试 |
| python-dotenv | 环境变量加载 |
| tqdm | 命令行进度条 |
| requests | 翻译 API 调用 |
| deep_translator | Google 翻译 |

## 注意事项

- arXiv API 免费公开，但建议遵守 3 秒以上的请求间隔
- DeepSeek API 按 token 计费，全文分析一篇论文约消耗 4000-6000 tokens
- 摘要分析模式的 token 消耗约为全文分析的 1/3，适合快速批量筛选
- 翻译功能中 Google 后端无需 API Key 即可使用
