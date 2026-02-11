from fastapi import APIRouter

from voice_agent.core.api.v1.dashboard import dashboard_router

api_router = APIRouter()
api_router.include_router(dashboard_router.router)