# TIAS - Team Intelligence Alignment System

团队智能对齐系统 - 团队与代码智能体之间对齐进度的桥梁

## 项目目标

减少团队沟通效率低的问题，通过自动化采集、整合、分析团队协作过程中的各类数据，为团队和AI提供统一的工作视图。

## 项目结构

```
tias/
├── src/tias/              # 主代码包
│   ├── __init__.py
│   ├── config.py         # 配置管理
│   ├── main.py           # FastAPI入口
│   ├── api/              # API路由
│   ├── collectors/       # 数据采集器
│   │   ├── base.py       # 采集器基类
│   │   └── git_collector.py
│   ├── storage/          # 数据存储
│   │   └── models.py     # 数据模型
│   ├── reporters/        # 报告生成器
│   │   └── base.py       # 报告基类及实现
│   ├── analyzers/        # 分析器
│   ├── intelligence/     # 智能决策
│   └── cli/              # 命令行工具
│       ├── daily_report.py
│       ├── weekly_report.py
│       └── config.py
├── configs/              # 配置文件
├── prompts/             # Prompt模板
├── scripts/             # 脚本
├── tests/              # 测试
└── docs/design/         # 设计文档
```

## 核心模块

| 模块 | 功能 |
|-----|------|
| `collectors/` | 数据采集（Git/禅道/钉钉/飞书等） |
| `storage/` | 数据模型（Person, Project, Commit, Task, Report） |
| `reporters/` | 报告生成（小时报/日报/周报/AI简报） |
| `analyzers/` | 分析引擎（进度分析/风险检测） |
| `intelligence/` | 智能决策（中心大脑） |
| `cli/` | 命令行工具（兼容原有daily/weekly report） |

## 快速开始

### 1. 安装依赖

```bash
cd tias
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑.env设置API Key等
```

### 3. 运行

**FastAPI服务**:
```bash
cd tias
python -m uvicorn src.tias.main:app --reload --port 8000
```

**命令行工具**:
```bash
cd tias
python -m src.tias.cli.daily_report
python -m src.tias.cli.weekly_report
```

## API端点

| 方法 | 端点 | 描述 |
|-----|------|-----|
| GET | `/health` | 健康检查 |
| GET | `/api/v1/projects` | 项目列表 |
| POST | `/api/v1/reports/generate` | 生成报告 |
| GET | `/api/v1/ai/briefing/{project_code}` | 获取AI简报 |

## 报告类型

| 类型 | 频率 | 接收者 |
|-----|------|-------|
| 小时报 | 每小时/手动 | 团队 |
| 日报 | 每天 | 团队+上级 |
| 周报 | 每周一 | 团队+管理层 |
| AI简报 | 实时/定期 | 代码智能体 |

## 设计文档

详见 `docs/design/TIAS_Design_v1.0.md`

## 版本

v0.1.0 - 开发中