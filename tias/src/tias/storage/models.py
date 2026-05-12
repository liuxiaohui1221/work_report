"""Data models for TIAS"""
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4
import json


@dataclass
class Person:
    id: UUID
    name: str
    email: str
    git_name: str
    role: str  # developer, team_leader, architecture
    status: str = "active"
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Project:
    id: UUID
    name: str
    code: str  # platform, agent
    git_repo_path: str
    zentao_project_id: str = ""
    status: str = "active"
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


@dataclass
class Commit:
    commit_hash: str
    short_hash: str
    message: str
    author_name: str
    author_email: str
    author_id: Optional[UUID] = None
    project_id: Optional[UUID] = None
    committed_at: datetime = None
    files_changed: List[str] = None
    lines_added: int = 0
    lines_deleted: int = 0
    diff: str = ""

    def __post_init__(self):
        if self.committed_at is None:
            self.committed_at = datetime.now()
        if self.files_changed is None:
            self.files_changed = []


@dataclass
class Task:
    id: UUID
    external_id: str
    source: str  # zentao, dingtalk, feishu
    title: str
    description: str = ""
    status: str = "wait"  # wait, doing, done
    assignee_id: Optional[UUID] = None
    project_id: Optional[UUID] = None
    estimate_hours: float = 0
    consumed_hours: float = 0
    deadline: Optional[datetime] = None
    created_at: datetime = None
    finished_at: Optional[datetime] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


@dataclass
class ActivityLog:
    time: datetime
    person_id: UUID
    project_id: UUID
    activity_type: str  # commit, task_update, document_edit, chat
    content: Dict[str, Any]
    ingested_at: datetime = None

    def __post_init__(self):
        if self.ingested_at is None:
            self.ingested_at = datetime.now()


@dataclass
class Report:
    id: UUID
    report_type: str  # hourly, daily, weekly, ai_briefing
    person_id: Optional[UUID] = None  # None means project report
    project_id: Optional[UUID] = None
    content: str  # Markdown or JSON for AI
    generated_at: datetime = None
    period_start: datetime = None
    period_end: datetime = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.generated_at is None:
            self.generated_at = datetime.now()
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> dict:
        data = asdict(self)
        data['content'] = json.loads(data['content']) if isinstance(data['content'], str) else data['content']
        return data


@dataclass
class Risk:
    id: UUID
    project_id: UUID
    person_id: Optional[UUID] = None
    severity: str = "medium"  # high, medium, low
    description: str = ""
    status: str = "open"  # open, acknowledged, resolved
    detected_at: datetime = None
    resolved_at: Optional[datetime] = None

    def __post_init__(self):
        if self.detected_at is None:
            self.detected_at = datetime.now()


@dataclass
class TimePeriod:
    start: datetime
    end: datetime
    description: str = ""  # "今天", "昨天", "最近3天"

    @property
    def days(self) -> int:
        return (self.end - self.start).days

    @property
    def hours(self) -> int:
        return (self.end - self.start).total_seconds() / 3600