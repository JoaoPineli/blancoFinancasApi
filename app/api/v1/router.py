"""API v1 router - Aggregates all endpoint routers."""

from fastapi import APIRouter

from app.api.v1.endpoints import admin, auth, finances, users

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(finances.router, prefix="/finances", tags=["Finances"])
api_router.include_router(admin.router, prefix="/admin", tags=["Admin"])
