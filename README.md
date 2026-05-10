# Work Report Automation

基于 Git 提交记录和项目规划文件，自动生成团队日报和周报。

## 功能特性

- **多角色支持**：支持团队成员在不同项目中担任不同角色
- **可追溯性**：每项工作都标注来源（commit 号），可直接追溯到代码变更
- **按人/按项目输出**：
  - 个人报告：`by_person/{姓名}_{日/周}报_{日期}.md`
  - 项目报告：`by_project/{项目名}_{日/周}报_{日期}.md`
- **支持多项目**：platform（数据平台后端）、agent（Agent项目）

## 项目结构

```
.
├── main/                    # Python 代码
│   ├── config.py           # 配置文件（项目、团队成员、LLM参数）
│   ├── daily_report.py     # 日报生成脚本
│   └── weekly_report.py    # 周报生成脚本
├── prompts/                # Prompt 模板
│   ├── personal_daily_prompt.md
│   ├── personal_weekly_prompt.md
│   ├── project_daily_prompt.md
│   └── project_weekly_prompt.md
├── input/                  # 输入文件
│   └── {年月}/
│       ├── platform/       # 平台项目规划文件
│       └── agent/          # Agent项目规划文件
└── output/                 # 生成报告输出目录
    └── {年月}/
        ├── by_person/      # 个人报告
        │   └── daily/
        └── by_project/     # 项目报告
            └── daily/
```

## 快速开始

### 1. 安装依赖

```bash
pip install openai requests openpyxl python-dotenv anthropic
```

### 2. 配置

编辑 `main/config.py`：

```python
# 项目配置
PROJECT1_NAME = "数据平台后端"
PROJECT1_REPO_PATH = r"C:\path\to\cyber-platform"

PROJECT2_NAME = "Agent项目"
PROJECT2_REPO_PATH = r"C:\path\to\cyber-agent"

# 本地规划文件目录
PLAN_DATA_DIR = r"C:\workspace\pywork\work_report\input\202605"

# 团队成员配置
TEAM_MEMBER_SOURCE = "config"  # "config"=手动配置, "git"=从Git提交记录自动获取

# 手动配置的团队成员（TEAM_MEMBER_SOURCE="config" 时使用）
TEAM_MEMBERS = [
    {
        "name": "刘小辉",
        "git_name": "xiaohui",
        "email": "1819800062@qq.com",
        "project_roles": {
            "platform": "developer",
            "agent": "team_leader,architecture"
        }
    },
    # 添加更多成员...
]

# Git自动发现的默认角色（TEAM_MEMBER_SOURCE="git" 时使用）
DEFAULT_ROLE = "developer"

# LLM 配置
MODEL_NAME = "MiniMax-M2.7"
```

### 团队成员来源

`TEAM_MEMBER_SOURCE` 控制成员数据来源：
- `"config"`：使用手动配置的 `TEAM_MEMBERS` 列表
- `"git"`：从 Git 提交记录自动发现本周/今日有提交的所有作者

### 日报统计时间策略

`DAILY_REPORT_MODE` 控制日报的时间范围：

- `"auto"`（默认）：自动判断
  - 早上（6:00-12:00）自动获取前一天的数据
  - 下午/晚上（12:00-24:00）自动获取当天的数据
- `"manual"`：手动指定天数
  - 使用 `DAILY_REPORT_DAYS` 指定获取最近几天数据

```python
# 自动模式（默认）
DAILY_REPORT_MODE = "auto"
MORNING_HOUR = 6    # 早上时段开始
EVENING_HOUR = 12   # 下午时段开始

# 手动模式
DAILY_REPORT_MODE = "manual"
DAILY_REPORT_DAYS = 2  # 获取最近2天数据
```

### 3. 运行

```bash
# 生成日报
python main/daily_report.py

# 生成周报
python main/weekly_report.py
```

## 配置说明

### 团队成员角色

角色类型：`team_leader`（团队负责人）、`developer`（开发人员）、`architecture`（架构师）

一个人在不同项目中可以有不同的角色，使用逗号分隔：

```python
"project_roles": {
    "platform": "developer",
    "agent": "team_leader,architecture"  # 多角色
}
```

### 输入文件目录

```
input/202605/
├── platform/          # 平台项目规划（Excel/Markdown）
└── agent/             # Agent项目规划（Excel/Markdown）
```

## 输出报告示例

### 个人报告

每项工作后标注来源，可追溯到具体 commit：

```markdown
## 1. 本周完成工作

### Agent项目
- 完成JWT鉴权功能开发（来源：commit a1b2c3d）
- 优化API响应速度（来源：commit e4f5g6h）
```

### 项目报告

按团队成员分段落，体现各人贡献：

```markdown
## 1. 本周完成工作

- 张三：完成用户模块开发（来源：commit abc123）
- 李四：修复登录bug（来源：commit def456）
```

## 环境变量

```bash
# .env 文件
MINIMAX_API_KEY=your_api_key
MINIMAX_BASE_URL=https://api.minimaxi.com/anthropic
```