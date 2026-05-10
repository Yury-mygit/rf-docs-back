from fastapi import APIRouter

from app.api import docs, site, workspaces

api_router = APIRouter()
api_router.include_router(docs.router)
api_router.include_router(workspaces.router)
api_router.include_router(site.router)
