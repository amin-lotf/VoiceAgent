from fastapi import APIRouter

from voice_agent.core.api.v1.dashboard import router as dashboard_router
from voice_agent.core.api.v1.calendly import router as calendly_router
from voice_agent.core.api.v1.calls import router as calls_router
from voice_agent.core.api.v1.hubspot import router as hubspot_router
from voice_agent.core.api.v1.retell import router as retell_router

api_router = APIRouter()
api_router.include_router(dashboard_router.router)
api_router.include_router(calendly_router.router)
api_router.include_router(calls_router.router)
api_router.include_router(hubspot_router.router)
api_router.include_router(retell_router.router)