# backend/app/models/analytics.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()

class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"

    id = Column(Integer, primary_key=True, index=True)
    # Связь с пользователем WordPress по его customer_id
    customer_id = Column(Integer, nullable=False, index=True) 
    event_type = Column(String, nullable=False, index=True) # Тип события: 'view_product', 'add_to_cart'
    event_data = Column(JSON, nullable=True) # Доп. данные: {'product_id': 123}
    created_at = Column(DateTime(timezone=True), server_default=func.now())