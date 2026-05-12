"""FastAPI application for TIAS - Team Intelligence Alignment System"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid

from .config import config, TIASConfig, ProjectConfig, PersonConfig
from .storage.models import TimePeriod, Report
from .collectors.git_collector import GitCollector
from .reporters.base import HourlyReporter, DailyReporter, WeeklyReporter, AIBriefingReporter

app = FastAPI(
    title="TIAS - Team Intelligence Alignment System",
    description="团队智能对齐系统 - 团队与代码智能体之间对齐进度的桥梁",
    version="0.1.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/Response models
class GenerateReportRequest(BaseModel):
    report_type: str  # hourly, daily, weekly, ai_briefing
    project_code: Optional[str] = None
    person_id: Optional[str] = None
    mode: str = "auto"
    manual_days: int = 1


class ProjectResponse(BaseModel):
    code: str
    name: str


class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: datetime


# Helper functions
def parse_time_period(mode: str, manual_days: int = 1) -> TimePeriod:
    from datetime import timedelta
    now = datetime.now()
    current_hour = now.hour

    if mode == "manual":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        for _ in range(manual_days - 1):
            start = start - timedelta(days=1)
        return TimePeriod(start=start, end=now, description=f"最近{manual_days}天")
    else:
        if config.report_time.morning_hour <= current_hour < config.report_time.evening_hour:
            yesterday = now - timedelta(days=1)
            return TimePeriod(
                start=yesterday.replace(hour=0, minute=0, second=0, microsecond=0),
                end=now.replace(hour=0, minute=0, second=0, microsecond=0),
                description="昨天"
            )
        else:
            return TimePeriod(
                start=now.replace(hour=0, minute=0, second=0, microsecond=0),
                end=now,
                description="今天"
            )


# Routes
@app.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(status="ok", version="0.1.0", timestamp=datetime.now())


@app.get("/api/v1/projects", response_model=List[ProjectResponse])
async def list_projects():
    """List all projects"""
    return [ProjectResponse(code=p.code, name=p.name) for p in config.projects]


@app.post("/api/v1/reports/generate")
async def generate_report(req: GenerateReportRequest):
    """Generate a report"""
    try:
        period = parse_time_period(req.mode, req.manual_days)

        # Select reporter
        if req.report_type == "hourly":
            reporter = HourlyReporter()
        elif req.report_type == "daily":
            reporter = DailyReporter()
        elif req.report_type == "weekly":
            reporter = WeeklyReporter()
        elif req.report_type == "ai_briefing":
            reporter = AIBriefingReporter()
        else:
            raise HTTPException(status_code=400, detail=f"Unknown report type: {req.report_type}")

        # Gather data
        commits = []
        tasks = []
        project = {}

        # Find project config if project_code provided
        if req.project_code:
            for p in config.projects:
                if p.code == req.project_code:
                    project = {"name": p.name, "code": p.code}
                    # Get commits from git
                    collector = GitCollector(p.git_repo_path)
                    commits = collector.get_commits(req.project_code, period)
                    break

        report = reporter.generate(
            period=period,
            commits=commits,
            tasks=tasks,
            project=project,
            person_id=req.person_id,
            project_id=req.project_code,
            report_id=uuid.uuid4()
        )

        return {
            "id": str(report.id),
            "type": report.report_type,
            "content": report.content,
            "generated_at": report.generated_at.isoformat(),
            "period": {
                "start": report.period_start.isoformat() if report.period_start else None,
                "end": report.period_end.isoformat() if report.period_end else None
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/ai/briefing/{project_code}")
async def get_ai_briefing(project_code: str):
    """Get AI briefing for a project"""
    try:
        reporter = AIBriefingReporter()
        period = parse_time_period("auto")

        project = {}
        commits = []
        for p in config.projects:
            if p.code == project_code:
                project = {"name": p.name, "code": p.code}
                collector = GitCollector(p.git_repo_path)
                commits = collector.get_commits(project_code, period)
                break

        if not project:
            raise HTTPException(status_code=404, detail=f"Project {project_code} not found")

        report = reporter.generate(
            period=period,
            commits=commits,
            tasks=[],
            project=project,
            person_id=None,
            project_id=project_code,
            report_id=uuid.uuid4()
        )

        return {
            "project_code": project_code,
            "briefing": report.content,
            "generated_at": report.generated_at.isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)