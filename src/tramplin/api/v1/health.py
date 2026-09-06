from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tramplin.api.schemas.health import HealthOut

router = APIRouter(tags=["health"], route_class=DishkaRoute)


@router.get("/health")
async def health() -> HealthOut:
    return HealthOut(status="ok")


@router.get("/health/ready")
async def readiness(session: FromDishka[AsyncSession], redis: FromDishka[Redis]) -> HealthOut:
    await session.execute(text("SELECT 1"))
    await redis.ping()
    return HealthOut(status="ok")
