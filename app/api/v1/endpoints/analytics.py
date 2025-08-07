# backend/app/api/v1/endpoints/analytics.py
from fastapi import APIRouter, Depends, BackgroundTasks
from typing import Dict, Annotated, Any
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import validate_telegram_data
from app.services.woocommerce import WooCommerceService
from app.dependencies import get_woocommerce_service
from app.core.db import get_db
from app.models.analytics import AnalyticsEvent

router = APIRouter()

class EventPayload(BaseModel):
    event_type: str
    event_data: Dict[str, Any]

@router.post("/events", status_code=202)
async def track_event(
    payload: EventPayload,
    background_tasks: BackgroundTasks,
    telegram_data: Annotated[Dict, Depends(validate_telegram_data)],
    wc_service: WooCommerceService = Depends(get_woocommerce_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Принимает событие от фронтенда и сохраняет его в БД в фоновом режиме.
    """
    async def save_event_task():
        customer_id = await wc_service.find_or_create_customer_by_telegram_data(telegram_data.get('user', {}))
        if customer_id:
            event = AnalyticsEvent(
                customer_id=customer_id,
                event_type=payload.event_type,
                event_data=payload.event_data
            )
            db.add(event)
            await db.commit()

    background_tasks.add_task(save_event_task)
    return {"message": "Event accepted"}