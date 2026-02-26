from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from config import DATABASE_TYPE
from database import get_db
from models import Agent, Team, Workflow, Session as SessionModel
from schemas import DashboardSummary
from auth import get_current_user, TokenData

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import AgentCollection, TeamCollection, WorkflowCollection, SessionCollection

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        agents = await AgentCollection.find_by_user(mongo_db, current_user.user_id)
        teams = await TeamCollection.find_by_user(mongo_db, current_user.user_id)
        workflows = await WorkflowCollection.find_by_user(mongo_db, current_user.user_id)
        sessions = await SessionCollection.find_by_user(mongo_db, current_user.user_id)
        return DashboardSummary(
            agents_count=len(agents),
            teams_count=len(teams),
            workflows_count=len(workflows),
            sessions_count=len(sessions),
        )

    uid = int(current_user.user_id)
    return DashboardSummary(
        agents_count=db.query(Agent).filter(Agent.user_id == uid, Agent.is_active == True).count(),
        teams_count=db.query(Team).filter(Team.user_id == uid, Team.is_active == True).count(),
        workflows_count=db.query(Workflow).filter(Workflow.user_id == uid, Workflow.is_active == True).count(),
        sessions_count=db.query(SessionModel).filter(SessionModel.user_id == uid, SessionModel.is_active == True).count(),
    )
