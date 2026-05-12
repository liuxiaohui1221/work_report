"""Configuration management for TIAS"""
import os
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from dotenv import load_dotenv

load_dotenv()


@dataclass
class ProjectConfig:
    """Project configuration"""
    code: str  # platform, agent
    name: str
    git_repo_path: str
    zentao_project_id: str = ""


@dataclass
class PersonConfig:
    """Person configuration"""
    name: str
    git_name: str
    email: str
    project_roles: Dict[str, str]  # project_code -> role


@dataclass
class LLMConfig:
    """LLM provider configuration"""
    provider: str = "anthropic"  # anthropic, openai, minimax
    api_key: str = ""
    base_url: str = "https://api.anthropic.com"
    model: str = "claude-3-5-sonnet-20241022"
    max_tokens: int = 4096
    temperature: float = 0.5


@dataclass
class ReportTimeConfig:
    """Report time range configuration"""
    mode: str = "auto"  # auto, manual
    manual_days: int = 1
    morning_hour: int = 6
    evening_hour: int = 12


@dataclass
class TeamMemberSourceConfig:
    """Team member source configuration"""
    source: str = "git"  # config, git
    default_role: str = "developer"


@dataclass
class TIASConfig:
    """Main TIAS configuration"""
    # Projects
    projects: List[ProjectConfig] = field(default_factory=list)

    # Persons
    persons: List[PersonConfig] = field(default_factory=list)
    team_member_source: TeamMemberSourceConfig = field(default_factory=TeamMemberSourceConfig)

    # LLM
    llm: LLMConfig = field(default_factory=LLMConfig)

    # Report time
    report_time: ReportTimeConfig = field(default_factory=ReportTimeConfig)

    # Paths
    prompts_dir: str = "prompts"
    output_dir: str = "output"


def load_config() -> TIASConfig:
    """Load configuration from environment and defaults"""
    # Projects from environment (comma-separated)
    project_codes = os.getenv("PROJECT_CODES", "platform,agent").split(",")
    projects = []

    for code in project_codes:
        code = code.strip()
        if code == "platform":
            projects.append(ProjectConfig(
                code="platform",
                name=os.getenv("PROJECT1_NAME", "数据平台后端"),
                git_repo_path=os.getenv("PROJECT1_REPO_PATH", ""),
            ))
        elif code == "agent":
            projects.append(ProjectConfig(
                code="agent",
                name=os.getenv("PROJECT2_NAME", "Agent项目"),
                git_repo_path=os.getenv("PROJECT2_REPO_PATH", ""),
            ))

    # LLM Config
    llm_config = LLMConfig(
        provider=os.getenv("LLM_PROVIDER", "anthropic"),
        api_key=os.getenv("LLM_API_KEY", ""),
        base_url=os.getenv("LLM_BASE_URL", "https://api.anthropic.com"),
        model=os.getenv("LLM_MODEL", "claude-3-5-sonnet-20241022"),
        max_tokens=int(os.getenv("MAX_TOKENS", "4096")),
        temperature=float(os.getenv("TEMPERATURE", "0.5")),
    )

    # Report Time Config
    report_time_config = ReportTimeConfig(
        mode=os.getenv("REPORT_TIME_MODE", "auto"),
        manual_days=int(os.getenv("REPORT_MANUAL_DAYS", "1")),
        morning_hour=int(os.getenv("MORNING_HOUR", "6")),
        evening_hour=int(os.getenv("EVENING_HOUR", "12")),
    )

    # Team Member Source Config
    team_member_source = TeamMemberSourceConfig(
        source=os.getenv("TEAM_MEMBER_SOURCE", "git"),
        default_role=os.getenv("DEFAULT_ROLE", "developer"),
    )

    return TIASConfig(
        projects=projects,
        llm=llm_config,
        report_time=report_time_config,
        team_member_source=team_member_source,
    )


# Global config instance
config = load_config()