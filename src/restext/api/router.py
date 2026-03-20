from fastapi import APIRouter

from restext.api.projects import router as projects_router
from restext.api.sources import router as sources_router
from restext.api.query import router as query_router
from restext.api.feedback import router as feedback_router
from restext.api.keys import router as keys_router
from restext.api.discover import router as discover_router
from restext.api.analytics import router as analytics_router

router = APIRouter()

router.include_router(projects_router, prefix="/projects", tags=["projects"])
router.include_router(sources_router, prefix="/projects/{project_id}/sources", tags=["sources"])
router.include_router(query_router, prefix="/projects/{project_id}", tags=["query"])
router.include_router(feedback_router, prefix="/projects/{project_id}", tags=["feedback"])
router.include_router(analytics_router, prefix="/projects/{project_id}", tags=["analytics"])
router.include_router(keys_router, prefix="/keys", tags=["keys"])
router.include_router(discover_router, tags=["discovery"])
