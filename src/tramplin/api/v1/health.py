from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["health"], route_class=DishkaRoute)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(session: FromDishka[AsyncSession], redis: FromDishka[Redis]) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    await redis.ping()
    return {"status": "ok"}
