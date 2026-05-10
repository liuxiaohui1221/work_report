# ===================== 配置文件 =====================
# 此文件包含需要经常修改的变量信息

# --- 项目信息 ---
PROJECT1_NAME = "数据平台后端（cyber-platform）"
PROJECT1_REPO_PATH = r"C:\workspace\datacyber\cyber-platform"
PROJECT1_PHASE = "全阶段"

PROJECT2_NAME = "Agent项目（cyber-agent）"
PROJECT2_REPO_PATH = r"C:\workspace2\cyber-agent"
PROJECT2_PHASE = "一阶段: 代码评审, 二阶段: API服务批量生成, 三阶段: 智能问数"
CURRENT_PHASE = "当前开发阶段：一阶段"

# --- 本地规划文件目录 ---
PLAN_DATA_DIR = r"C:\workspace\pywork\work_report\input\202605"

# --- 规划文件子目录名称（与input目录下的子目录名对应） ---
PLATFORM_DIR = "platform"
AGENT_DIR = "agent"

# --- 大模型参数 ---
MAX_DIFF_LINES = 1000  # git diff 输出最大行数，避免超出模型上下文
MODEL_NAME = "MiniMax-M2.7"
MAX_TOKENS = 4096
TEMPERATURE = 0.5

# --- 团队成员配置 ---
# 角色说明：team_leader=团队负责人, developer=开发人员, architecture=架构师
# 注意：一个人在不同的项目中可以有不同的角色，多个角色用英文逗号分隔
# 注意：一个人在一个项目中只会输出一份综合报告，不会按角色输出多份
TEAM_MEMBERS = [
    {
        "name": "刘小辉",
        "git_name": "xiaohui",
        "email": "1819800062@qq.com",
        "project_roles": {
            "platform": "developer",
            "agent": "team_leader,architecture"
        }
    }
]