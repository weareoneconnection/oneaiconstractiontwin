from sqlalchemy.orm import Session
from app.domain.models import OutboxEvent


def emit(db: Session, topic: str, aggregate_type: str, aggregate_id: str, payload: dict) -> OutboxEvent:
    event = OutboxEvent(topic=topic, aggregate_type=aggregate_type, aggregate_id=aggregate_id, payload=payload)
    db.add(event)
    db.flush()
    return event
