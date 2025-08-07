# backend/app/api/v1/endpoints/admin_analytics.py
from fastapi import APIRouter, Depends
from sqlalchemy import select, func, distinct
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta

from app.dependencies import verify_admin_api_key
from app.core.db import get_db
from app.models.analytics import AnalyticsEvent

router = APIRouter(prefix="/admin/analytics", tags=["Admin Analytics"], dependencies=[Depends(verify_admin_api_key)])

@router.get("/dau")
async def get_daily_active_users(db: AsyncSession = Depends(get_db)):
    """Возвращает количество уникальных активных пользователей за сегодня."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Считаем уникальные customer_id за сегодня
    query = select(func.count(distinct(AnalyticsEvent.customer_id))).\
        where(AnalyticsEvent.created_at >= today_start)
        
    result = await db.execute(query)
    count = result.scalar_one()
    return {"date": today_start.date(), "dau": count}

@router.get("/top_viewed_products")
async def get_top_viewed_products(limit: int = 10, db: AsyncSession = Depends(get_db)):
    """Возвращает самые просматриваемые товары."""
    query = select(
        AnalyticsEvent.event_data['product_id'].as_string().label('product_id'), 
        func.count(AnalyticsEvent.id).label('views')
    ).\
    where(AnalyticsEvent.event_type == 'view_product').\
    group_by('product_id').\
    order_by(func.count(AnalyticsEvent.id).desc()).\
    limit(limit)
    
    result = await db.execute(query)
    # Нужно будет еще сделать запрос к WC, чтобы получить названия товаров по их ID
    top_products = [{"product_id": row.product_id, "views": row.views} for row in result.all()]
    return top_products