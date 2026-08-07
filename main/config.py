# ===================== 配置文件 =====================
# 此文件包含需要经常修改的变量信息

import os
from dotenv import load_dotenv

load_dotenv()

# --- SMTP 密码从 .env 文件获取（不在此处硬编码） ---

# --- 项目信息 ---
# 格式: 项目键 = { "name": 显示名, "local": 本地仓库路径, "remote": 远程仓库URL }
# 2026-08-07 取消 cyber-agent 项目：该项目已被 dataagent 替代
# 2026-08-07 改为扫描 dataagent 这一个 GitLab 项目（deer-flow 是 dataagent 的 vendor 子目录）
# 2026-08-07 新增配置：只有成员有代码变更的项目才会在周报中显示
PROJECTS = {
    "dataagent": {
        "name": "DataAgent项目",
        "local": r"C:\workspace\datacyber\dataagent",
        "remote": "http://172.18.1.181/cyberagent/cyber-agent-loop.git"
    }
}

# --- 个人周报过滤配置 ---
# 只有成员有代码变更的项目才会在个人周报中显示
# 默认为 True（开启过滤）；设置为 False 可关闭此功能
FILTER_PROJECTS_WITHOUT_CHANGES = True
# 过滤时使用的 Git 作者邮箱（用于判断成员是否有代码变更）
FILTER_AUTHOR_EMAIL = "liuxiaohui@datacyber.com"

# --- 本地规划文件目录 ---
PLAN_DATA_DIR = r"C:\workspace\pywork\work_report\input\plan"

# --- 日报时间策略配置 ---
# DAILY_REPORT_MODE: "auto"=自动判断, "manual"=手动指定天数
# DAILY_REPORT_MODE = "auto" 时：
#   - 早上（6:00-12:00）自动获取前一天的数据
#   - 下午/晚上（12:00-24:00）自动获取当天的数据
# DAILY_REPORT_MODE = "manual" 时：
#   - 使用 DAILY_REPORT_DAYS 指定获取最近几天数据
DAILY_REPORT_MODE = "manual"
#DAILY_REPORT_MODE = "auto"
DAILY_REPORT_DAYS = 2  # manual模式时有效，获取最近几天数据

# 早上时段开始时间（用于判断是否获取前一天数据）
MORNING_HOUR = 6
EVENING_HOUR = 12  # 12:00之后算下午/晚上

# --- 待办任务配置 ---
PENDING_STATUSES = ["待办", "开发中", "待联调", "进行中"]  # 视为待办的状态
COMPLETED_STATUS = "已完成"
MAX_PENDING_TASKS = 10  # 每人最多显示待办任务数

# --- 大模型参数 ---
MAX_DIFF_LINES = 10000  # git diff 输出最大行数，避免超出模型上下文
MODEL_NAME = os.getenv("MODEL_NAME", "MiniMax-M2.7")
MAX_TOKENS = 100000
TEMPERATURE = 0.5

# --- 团队成员配置 ---
# 角色说明：team_leader=团队负责人, developer=开发人员, architecture=架构师
# 注意：一个人在不同的项目中可以有不同的角色，多个角色用英文逗号分隔
# 注意：一个人在一个项目中只会输出一份综合报告，不会按角色输出多份
# 注意：TEAM_MEMBER_SOURCE 控制成员数据来源："config"=手动配置, "git"=从Git提交记录自动获取
TEAM_MEMBER_SOURCE = "git"  # "config" 或 "git"

# 手动配置的团队成员（TEAM_MEMBER_SOURCE="config" 时使用）
TEAM_MEMBERS = [
      {
          "name": "刘小辉",
          "email": "liuxiaohui@datacyber.com",  # 改这里
          "project_roles": {
              "dataagent": "architecture",
              "deer-flow": "architecture"
          }
      }
  ]

# Git自动发现的默认角色（TEAM_MEMBER_SOURCE="git" 时使用）
DEFAULT_ROLE = "developer"  # 从Git自动发现的成员默认角色

# --- GitLab 配置 ---
# GitLab 服务器地址
GITLAB_URL = "http://172.18.1.181"
# GitLab 私有 Token（从 .env 文件读取）
GITLAB_PRIVATE_TOKEN = os.getenv("GITLAB_PRIVATE_TOKEN", "")
# GitLab API 模式开关
# True = 不依赖 PROJECTS 配置，从 GitLab 动态获取用户有权限的所有项目
# False = 使用本地 PROJECTS 配置（传统模式）
GITLAB_API_MODE = False
# GitLab API 调用间隔（秒），避免限流
GITLAB_API_RATE_LIMIT = 1

# --- 邮件发送配置 ---
# 全局开关：是否启用邮件发送功能
EMAIL_ENABLED = True

# SMTP 配置（EMAIL_ENABLED=True 时需要配置）
EMAIL_SMTP_HOST = "smtp.qq.com"
EMAIL_SMTP_PORT = 587
EMAIL_SMTP_USER = "lxh1221@qq.com"
EMAIL_SMTP_PASSWORD = os.getenv("EMAIL_SMTP_PASSWORD", "")

# 邮件发送频率限制
EMAIL_RATE_LIMIT = 5  # 最多发送数量
EMAIL_RATE_PERIOD = 60  # 时间周期（秒）

# 发件人显示名称
EMAIL_FROM_NAME = "工作汇报"

# 是否给团队成员发送个人报告（True=发送，False=不发送）
TEAM_MEMBER_SEND_EMAIL = True

# 是否生成并发送项目周报（2026-08-08 重启：用户要求恢复项目周报）
SEND_PROJECT_REPORT = True

# 个人周报收件人邮箱（上级/负责人邮箱），为空则只发送给成员自己
PERSONAL_REPORT_RECIPIENT = ["zl@datacyber.com","liuxiaohui@datacyber.com","ypf@datacyber.com","songhongxin@datacyber.com"]

# 发送个人报告时的成员范围模式
# "all" = 发送给所有团队成员
# "select" = 让用户选择要发送给哪些成员
TEAM_MEMBER_EMAIL_MODE = "select"

# 项目报告邮件收件人配置
# 可以指定多个项目的收件人，格式：项目名=[收件人邮箱列表]
# 如果项目不在配置中，则不发送项目报告邮件
# 2026-08-07 取消 cyber-agent 项目：该项目已被 dataagent 替代
PROJECT_REPORT_RECIPIENTS = {
    "dataagent": ["liuxiaohui@datacyber.com"],
    "deer-flow": ["liuxiaohui@datacyber.com"]
}

# 也可以设置一个全局默认收件人列表，用于所有项目
# 如果项目不在 PROJECT_REPORT_RECIPIENTS 中，则使用此配置
DEFAULT_PROJECT_RECIPIENTS = ["zl@datacyber.com","liuxiaohui@datacyber.com"]