# ===================== 后端配置文件 =====================
# 此文件包含需要经常修改的变量信息

import os

# --- 数据库配置 ---
DATABASE_URI = "sqlite:///work_report.db"

# --- 项目信息（默认示例） ---
PROJECT1_NAME = "数据平台后端（cyber-platform）"
PROJECT1_REPO_PATH = r"C:\workspace\datacyber\cyber-platform"

PROJECT2_NAME = "Agent项目（cyber-agent）"
PROJECT2_REPO_PATH = r"C:\workspace2\cyber-agent"

# --- 本地规划文件目录 ---
PLAN_DATA_DIR = r"C:\workspace\pywork\work_report\input"

# --- 规划文件子目录名称 ---
PLATFORM_DIR = "platform"
AGENT_DIR = "agent"

# --- 日报时间策略配置 ---
DAILY_REPORT_MODE = "manual"
DAILY_REPORT_DAYS = 2

# --- 待办任务配置 ---
PENDING_STATUSES = ["待办", "开发中", "待联调", "进行中"]
COMPLETED_STATUS = "已完成"
MAX_PENDING_TASKS = 10

# --- 大模型参数 ---
MAX_DIFF_LINES = 10000
MODEL_NAME = "MiniMax-M3"
MAX_TOKENS = 100000
TEMPERATURE = 0.6

# --- 团队成员配置 ---
TEAM_MEMBER_SOURCE = "config"
DEFAULT_ROLE = "developer"

# --- 邮件发送配置 ---
EMAIL_ENABLED = True
EMAIL_SMTP_HOST = "smtp.qq.com"
EMAIL_SMTP_PORT = 587
EMAIL_SMTP_USER = "lxh1221@qq.com"
EMAIL_SMTP_PASSWORD = "hpptebjghluzifej"
EMAIL_FROM_NAME = "工作汇报"
EMAIL_RATE_LIMIT = 5
EMAIL_RATE_PERIOD = 60

# --- 报告输出目录 ---
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output")

# --- Prompt 目录 ---
PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "prompts")