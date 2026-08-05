# 短剧生成工作流

基于 LangGraph 的端到端短剧视频生成系统。输入 Word 格式剧本，自动完成从解析到视频生成的全流程。

## 功能特性

- 📝 **剧本解析** - 自动解析 Word 格式剧本，提取场景、人物、对话
- 🎭 **资产包生成** - 识别角色、场景、道具，生成统一风格的视觉描述
- 🎬 **智能分镜** - 自动生成分镜脚本，包含机位设计和镜头序列
- 🔗 **一致性检查** - 确保角色造型、场景风格在全剧中统一
- ✨ **提示词优化** - 生成可直接用于视频生成 API 的详细提示词
- 🎥 **视频生成** - 支持接入主流视频生成 API（Runway、Kling 等）
- 🎞️ **视频合成** - 自动合并视频片段（需 ffmpeg）

## 前置依赖

| 依赖 | 版本要求 | 说明 |
|------|----------|------|
| Python | >= 3.10 | 必需 |
| uv | 最新版 | Python 包管理工具，[安装指南](https://docs.astral.sh/uv/getting-started/installation/) |
| ffmpeg | 可选 | 仅在需要合并真实视频文件时使用，[下载](https://ffmpeg.org/download.html) |

## API Key 配置

本项目需要配置 LLM API Key 和视频生成 API Key 才能运行。

### 推荐方式：.env 文件

项目根目录下创建 `.env` 文件（已自动被 .gitignore 忽略）：

```bash
# 必填
OPENAI_API_KEY=sk-your-openai-api-key-here
KLING_API_KEY=your-kling-api-key-here

# 可选（图片生成用，不配置则跳过图片生成）
# VOLCENGINE_AK=your-access-key
# VOLCENGINE_SK=your-secret-key
```

### 环境变量方式

```bash
# Windows PowerShell
$env:OPENAI_API_KEY = "sk-..."
$env:KLING_API_KEY = "your-key"

# Linux/macOS
export OPENAI_API_KEY="sk-..."
export KLING_API_KEY="your-key"
```

### 可灵 (Kling) API Key 获取

1. 访问 [可灵官网](https://klingai.com) 注册账号
2. 进入控制台/API 管理页面
3. 创建 API Key 并复制
4. 视频生成默认使用 `kling-v1` 模型，可在 `config.yaml` 中修改

### 默认模型

默认使用 OpenAI GPT-4o，可在 `config.yaml` 中修改：

```yaml
models:
  default:
    model: gpt-4o          # 模型名称
    provider: openai      # 服务提供商
    temperature: 0.5      # 生成随机性（0-1）
```

如需为特定节点使用不同模型，在 `models.nodes` 下配置：

```yaml
models:
  nodes:
    parse_docx:
      model: gpt-4o-mini
      provider: openai
    step1_storyboard:
      model: gpt-4o
      provider: openai
    step3_optimize_prompts:
      model: gpt-4o
      provider: openai
      temperature: 0.3
```

## 安装步骤

```bash
# 1. 克隆项目
git clone <repository-url>
cd gen-video

# 2. 同步依赖（uv 会自动创建虚拟环境）
uv sync

# 3. 配置 API Key（二选一）
# 方式 A：设置环境变量
export OPENAI_API_KEY="your-api-key"

# 方式 B：修改 config.yaml 中的 api_keys.openai
```

## 使用方法

### 运行完整工作流

```bash
# 处理默认输入文件（参考资料/第01集.docx）
uv run python main.py

# 指定输入文件和剧集编号
uv run python main.py --input "参考资料/第01集.docx" --episode-id "01"

# 指定剧集标题
uv run python main.py --input "剧本.docx" --episode-id "02" --episode-title "第二集"
```

### 从指定步骤开始

```bash
# 跳过分镜，从一致性检查开始（需要已有 step1 输出）
uv run python main.py --start-step "step2_consistency"

# 可用步骤：
# parse_docx              - 解析剧本
# generate_asset_package  - 生成资产包
# step1_storyboard        - 生成分镜
# step2_consistency       - 一致性检查
# step3_optimize_prompts  - 优化提示词
# generate_videos         - 生成视频
# merge_videos            - 合并视频
```

### 临时覆盖模型配置

```bash
# 为特定节点指定不同模型
uv run python main.py --node-model "step1_storyboard:openai:gpt-4o"
uv run python main.py --node-model "step3_optimize_prompts:openai:gpt-4o-mini"
```

## 输出结构

```
输出/
└── 01/                          # 按剧集编号命名
    ├── 资产/                    # 资产包
    │   ├── 人物/                # 角色图片
    │   ├── 场景/                # 场景图片
    │   ├── 道具/                # 道具图片
    │   └── 资产包.md            # 资产包描述文件
    ├── 原始剧本.txt              # 原始剧本
    ├── 结构化剧本.md             # 结构化剧本
    ├── 分镜脚本.md               # 分镜脚本
    ├── 一致性检查报告.md         # 一致性检查报告
    ├── 优化提示词.md             # 优化后的提示词
    ├── 视频提示词.json           # 提示词结构化数据
    ├── 视频/                     # 视频片段
    ├── 视频片段清单.json         # 视频片段清单
    ├── 最终视频.mp4              # 最终合成视频
    └── 输出清单.json             # 输出清单
```

## 项目结构

```
gen-video/
├── main.py                 # 主入口
├── config.yaml             # 配置文件（模型、API Key 等）
├── pyproject.toml          # 项目依赖声明
├── uv.lock                 # 依赖版本锁定
├── .python-version         # Python 版本锁定
├── src/
│   ├── workflow.py         # LangGraph 工作流定义
│   ├── state.py            # 状态数据结构
│   ├── config_manager.py   # 配置管理
│   ├── model_manager.py    # 模型管理
│   ├── prompt_manager.py   # 提示词模板管理
│   ├── models/             # LLM 实现
│   │   ├── base_llm.py     # LLM 基类
│   │   ├── llm_factory.py  # LLM 工厂
│   │   └── providers.py    # Provider 实现（OpenAI 等）
│   ├── nodes/              # 工作流节点
│   │   ├── parse_docx.py
│   │   ├── generate_asset_package.py
│   │   ├── step1_storyboard.py
│   │   ├── step2_consistency.py
│   │   ├── step3_optimize_prompts.py
│   │   ├── generate_videos.py
│   │   └── merge_videos.py
│   └── prompts/            # 提示词模板（.txt 文件）
└── 参考资料/               # 输入文件目录
    └── 第01集.docx         # 示例剧本
```

## 常见问题

### Q: 提示 API Key 未找到？
确保已设置环境变量 `OPENAI_API_KEY`，或在 `config.yaml` 的 `api_keys.openai` 中填入密钥。

### Q: 可以支持其他 LLM 提供商吗？
目前内置 OpenAI 兼容接口。如需支持更多提供商，在 `src/models/providers.py` 中继承 `BaseLLM` 并注册到 `LLMFactory` 即可。

### Q: 视频生成如何接入真实 API？
编辑 `config.yaml` 添加：
```yaml
models:
  nodes:
    generate_videos:
      provider: runway    # 或 kling
      video_model: gen-3
```
并在 `api_keys` 中配置对应服务商的密钥。

### Q: 如何添加自定义提示词？
编辑 `src/prompts/` 下对应的 `.txt` 文件（Jinja2 模板格式），或在 `config.yaml` 的 `prompt_templates` 中指定自定义路径。

## 许可证

MIT License
