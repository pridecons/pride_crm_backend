from pydantic import BaseModel, ValidationError
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from enum import Enum


# ── Custom Exceptions ──────────────────────────────────────────────────────────
class RecommendationNotFoundError(Exception):
    pass

class FileUploadError(Exception):
    pass

class PDFGenerationError(Exception):
    pass

class DatabaseOperationError(Exception):
    pass

# ── Schemas ─────────────────────────────────────────────────────────────────────

class StatusType(str, Enum):
    OPEN = "OPEN"
    TARGET1_HIT = "TARGET1_HIT"
    TARGET2_HIT = "TARGET2_HIT"
    TARGET3_HIT = "TARGET3_HIT"
    STOP_LOSS_HIT = "STOP_LOSS_HIT"
    CLOSED = "CLOSED"

class NarrationCreate(BaseModel):
    entry_price: float
    stop_loss: Optional[float] = None
    targets: Optional[float] = 0
    targets2: Optional[float] = None
    targets3: Optional[float] = None
    rational: Optional[str] = None
    stock_name: Optional[str] = None
    recommendation_type: Optional[str] = None

    class Config:
        validate_assignment = True

class NarrationUpdate(BaseModel):
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    targets: Optional[float] = None
    targets2: Optional[float] = None
    targets3: Optional[float] = None
    status: Optional[StatusType] = None
    graph: Optional[str] = None
    rational: Optional[str] = None
    stock_name: Optional[str] = None
    recommendation_type: Optional[str] = None

    class Config:
        validate_assignment = True

class NarrationResponse(BaseModel):
    id: int
    entry_price: Optional[float]
    stop_loss: Optional[float]
    targets: Optional[float]
    targets2: Optional[float]
    targets3: Optional[float]
    status: str
    graph: Optional[str]
    pdf: Optional[str]
    rational: Optional[str]
    stock_name: Optional[str]
    recommendation_type: Optional[str]
    user_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

class AnalyticsResponse(BaseModel):
    user_id: str
    total_recommendations: int
    open_recommendations: int
    target1_hit: int
    target2_hit: int
    target3_hit: int
    stop_loss_hit: int
    closed_recommendations: int
    success_rate: float
    avg_return: Optional[float]
    best_recommendation: Optional[Dict]
    worst_recommendation: Optional[Dict]

class ErrorResponse(BaseModel):
    error: str
    detail: str
    timestamp: datetime = datetime.now()