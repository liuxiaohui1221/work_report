# TIAS - Team Intelligence Alignment System

**团队智能对齐系统** - 团队与代码智能体之间对齐进度的桥梁

## 重要更新

v0.1.0 正在开发中，主代码已移至 `tias/` 目录。

## 项目结构

```
.
├── tias/                    # 主项目目录 (TIAS v0.1.0)
│   ├── src/tias/           # 源代码
│   │   ├── api/           # API层
│   │   ├── collectors/     # 数据采集器
│   │   ├── storage/       # 数据存储
│   │   ├── reporters/     # 报告生成器
│   │   ├── analyzers/     # 分析器
│   │   ├── intelligence/  # 智能决策
│   │   └── cli/           # 命令行工具
│   ├── prompts/           # Prompt模板
│   ├── configs/           # 配置
│   ├── docs/design/       # 设计文档
│   └── requirements.txt
├── prompts/               # (旧) Prompt模板 - 已迁移至tias/prompts
├── output/                 # 报告输出目录
├── input/                  # 输入文件目录
└── docs/                   # 文档目录
```

## 快速开始

```bash
cd tias

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env

# 运行API服务
python -m uvicorn src.tias.main:app --reload --port 8000

# 或运行命令行工具
python -m src.tias.cli.daily_report
python -m src.tias.cli.weekly_report
```

## 核心功能

- **多数据源采集**: Git、禅道、钉钉、飞书
- **多种报告类型**: 小时报、日报、周报、AI简报
- **智能分析**: 进度追踪、风险检测、团队动力学
- **角色化汇报**: 根据成员角色生成不同详略的报告
- **AI对齐**: 为代码智能体提供结构化项目简报

## 设计文档

详见 [docs/design/TIAS_Design_v1.0.md](docs/design/TIAS_Design_v1.0.md)