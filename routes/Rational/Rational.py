# routes/recommendations.py
import os
import time
import aiofiles

from fastapi import (
    APIRouter, Depends, HTTPException,
    Query, UploadFile, File, Form
)
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, case
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from enum import Enum

from db.models import NARRATION
from db.connection import get_db
from routes.auth.auth_dependency import get_current_user

router = APIRouter(
    prefix="/recommendations",
    tags=["Recommendations"],
)

# ── Pydantic Schemas ────────────────────────────────────────────────────────────
class RecommendationType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"

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

class NarrationResponse(BaseModel):
    id: int
    entry_price: Optional[float]
    stop_loss: Optional[float]
    targets: Optional[float]
    targets2: Optional[float]
    targets3: Optional[float]
    status: str
    graph: Optional[str]
    rational: Optional[str]
    stock_name: Optional[str]
    recommendation_type: Optional[str]
    user_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

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

# ── Helpers ─────────────────────────────────────────────────────────────────────
# Ensure the upload folder exists
UPLOAD_DIR = "static/graphs"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ── 1. CREATE ───────────────────────────────────────────────────────────────────
@router.post("/", response_model=NarrationResponse)
async def create_recommendation(
    entry_price: float                   = Form(...),
    stop_loss: float                     = Form(None),
    targets: float                       = Form(0),
    targets2: float                      = Form(None),
    targets3: float                      = Form(None),
    rational: str                        = Form(None),
    stock_name: str                      = Form(None),
    recommendation_type: str             = Form(None),
    graph: UploadFile                    = File(None),
    db: Session                          = Depends(get_db),
    current_user                        = Depends(get_current_user),
):
    """
    Create a new stock recommendation with optional graph upload.
    """
    graph_path: Optional[str] = None
    if graph:
        filename    = f"{current_user.employee_code}_{int(time.time())}_{graph.filename}"
        file_path   = os.path.join(UPLOAD_DIR, filename)
        async with aiofiles.open(file_path, "wb") as out:
            await out.write(await graph.read())
        graph_path = f"/static/graphs/{filename}"

    try:
        rec = NARRATION(
            entry_price=entry_price,
            stop_loss=stop_loss,
            targets=targets,
            targets2=targets2,
            targets3=targets3,
            rational=rational,
            stock_name=stock_name,
            recommendation_type=recommendation_type,
            graph=graph_path,
            user_id=current_user.employee_code,
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)
        return rec

    except Exception as e:
        try:
            db.rollback()
        except:
            pass
        raise HTTPException(status_code=400, detail=f"Error creating recommendation: {e}")

# ── 2. READ (single) ────────────────────────────────────────────────────────────
@router.get("/{recommendation_id}", response_model=NarrationResponse)
def get_recommendation(
    recommendation_id: int,
    db: Session = Depends(get_db)
):
    rec = db.query(NARRATION).get(recommendation_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return rec

# ── 3. READ (list + filters) ───────────────────────────────────────────────────
@router.get("/", response_model=List[NarrationResponse])
def get_recommendations(
    user_id: Optional[str]               = Query(None),
    stock_name: Optional[str]            = Query(None),
    status: Optional[StatusType]         = Query(None),
    recommendation_type: Optional[str]   = Query(None),
    date_from: Optional[date]            = Query(None),
    date_to: Optional[date]              = Query(None),
    limit: int                           = Query(100),
    offset: int                          = Query(0),
    db: Session                          = Depends(get_db),
):
    q = db.query(NARRATION)
    if user_id:
        q = q.filter(NARRATION.user_id == user_id)
    if stock_name:
        q = q.filter(NARRATION.stock_name.ilike(f"%{stock_name}%"))
    if status:
        q = q.filter(NARRATION.status == status)
    if recommendation_type:
        q = q.filter(NARRATION.recommendation_type == recommendation_type)
    if date_from:
        q = q.filter(NARRATION.created_at >= date_from)
    if date_to:
        q = q.filter(NARRATION.created_at <= date_to)

    return q.order_by(desc(NARRATION.created_at)).offset(offset).limit(limit).all()

# ── 4. UPDATE ───────────────────────────────────────────────────────────────────
@router.put("/{recommendation_id}", response_model=NarrationResponse)
def update_recommendation(
    recommendation_id: int,
    payload: NarrationUpdate,
    db: Session = Depends(get_db),
):
    rec = db.query(NARRATION).filter(NARRATION.id == recommendation_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")

    for field, val in payload.dict(exclude_unset=True).items():
        setattr(rec, field, val)

    try:
        db.commit()
        db.refresh(rec)
        return rec
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Error updating recommendation: {e}")

# ── 5. DELETE ───────────────────────────────────────────────────────────────────
@router.delete("/{recommendation_id}")
def delete_recommendation(
    recommendation_id: int,
    db: Session = Depends(get_db),
):
    rec = db.query(NARRATION).filter(NARRATION.id == recommendation_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    try:
        db.delete(rec)
        db.commit()
        return {"message": "Recommendation deleted successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Error deleting recommendation: {e}")

# ── 6. USER ANALYTICS ───────────────────────────────────────────────────────────
@router.get("/user/{user_id}", response_model=AnalyticsResponse)
def get_user_analytics(
    user_id: str,
    date_from: Optional[date] = Query(None),
    date_to: Optional[date]   = Query(None),
    db: Session               = Depends(get_db),
):
    recs = db.query(NARRATION).filter(NARRATION.user_id == user_id)
    if date_from:
        recs = recs.filter(NARRATION.created_at >= date_from)
    if date_to:
        recs = recs.filter(NARRATION.created_at <= date_to)

    all_recs = recs.all()
    if not all_recs:
        raise HTTPException(status_code=404, detail="No recommendations found")

    # compute metrics…
    total       = len(all_recs)
    counts      = {s.value: 0 for s in StatusType}
    returns     = []
    for r in all_recs:
        counts[r.status] = counts.get(r.status, 0) + 1
        # calculate return %
        if r.entry_price and r.status in {"TARGET1_HIT","TARGET2_HIT","TARGET3_HIT"}:
            target = getattr(r, {"TARGET1_HIT":"targets",
                                 "TARGET2_HIT":"targets2",
                                 "TARGET3_HIT":"targets3"}[r.status])
            returns.append(((target - r.entry_price)/r.entry_price)*100)
        elif r.entry_price and r.status=="STOP_LOSS_HIT" and r.stop_loss:
            returns.append(((r.stop_loss - r.entry_price)/r.entry_price)*100)

    successful = sum(counts[s] for s in ["TARGET1_HIT","TARGET2_HIT","TARGET3_HIT"])
    closed     = successful + counts["STOP_LOSS_HIT"]
    success_rate = round((successful/closed*100) if closed else 0, 2)
    avg_return  = round(sum(returns)/len(returns),2) if returns else None

    best_idx = returns.index(max(returns)) if returns else None
    worst_idx= returns.index(min(returns)) if returns else None

    best = {"id":all_recs[best_idx].id,"stock_name":all_recs[best_idx].stock_name,"return_pct":round(returns[best_idx],2)} if best_idx is not None else None
    worst={"id":all_recs[worst_idx].id,"stock_name":all_recs[worst_idx].stock_name,"return_pct":round(returns[worst_idx],2)} if worst_idx is not None else None

    return AnalyticsResponse(
        user_id=user_id,
        total_recommendations=total,
        open_recommendations=counts["OPEN"],
        target1_hit=counts["TARGET1_HIT"],
        target2_hit=counts["TARGET2_HIT"],
        target3_hit=counts["TARGET3_HIT"],
        stop_loss_hit=counts["STOP_LOSS_HIT"],
        closed_recommendations=counts["CLOSED"],
        success_rate=success_rate,
        avg_return=avg_return,
        best_recommendation=best,
        worst_recommendation=worst,
    )

# ── 7. TEAM ANALYTICS ──────────────────────────────────────────────────────────
@router.get("/analytics/team")
def get_team_analytics(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date]   = Query(None),
    db: Session               = Depends(get_db),
):
    base = db.query(NARRATION)
    if date_from:
        base = base.filter(NARRATION.created_at >= date_from)
    if date_to:
        base = base.filter(NARRATION.created_at <= date_to)

    stats = (
        base
        .with_entities(
            NARRATION.user_id,
            func.count(NARRATION.id).label("total_recs"),
            func.sum(case([(NARRATION.status.in_(["TARGET1_HIT","TARGET2_HIT","TARGET3_HIT"]),1)], else_=0)).label("succ"),
            func.sum(case([(NARRATION.status=="STOP_LOSS_HIT",1)], else_=0)).label("fail"),
        )
        .group_by(NARRATION.user_id)
        .all()
    )

    team = []
    for u, total, succ, fail in stats:
        closed = succ + fail
        rate   = round((succ/closed*100) if closed else 0, 2)
        team.append({
            "user_id": u,
            "total_recommendations": total,
            "successful_recommendations": succ,
            "failed_recommendations": fail,
            "success_rate": rate,
        })

    team.sort(key=lambda x: x["success_rate"], reverse=True)
    overall_closed = sum(u["successful_recommendations"]+u["failed_recommendations"] for u in team)
    overall_succ   = sum(u["successful_recommendations"] for u in team)
    overall_rate   = round((overall_succ/overall_closed*100) if overall_closed else 0, 2)

    return {
        "team_analytics": team,
        "summary": {
            "total_users": len(team),
            "total_recommendations": sum(u["total_recommendations"] for u in team),
            "overall_success_rate": overall_rate,
        }
    }

# ── 8. TOP STOCKS ──────────────────────────────────────────────────────────────
@router.get("/analytics/top-stocks")
def get_top_performing_stocks(
    limit: int               = Query(10),
    date_from: Optional[date]= Query(None),
    date_to: Optional[date]  = Query(None),
    db: Session              = Depends(get_db),
):
    q = db.query(
        NARRATION.stock_name,
        func.count(NARRATION.id).label("total"),
        func.sum(case([(NARRATION.status.in_(["TARGET1_HIT","TARGET2_HIT","TARGET3_HIT"]),1)], else_=0)).label("succ"),
    ).filter(NARRATION.stock_name.isnot(None))

    if date_from:
        q = q.filter(NARRATION.created_at >= date_from)
    if date_to:
        q = q.filter(NARRATION.created_at <= date_to)

    stats = q.group_by(NARRATION.stock_name).all()

    results = []
    for stock, tot, succ in stats:
        rate = round((succ/tot*100) if tot else 0, 2)
        results.append({
            "stock_name": stock,
            "total_recommendations": tot,
            "successful_recommendations": succ,
            "success_rate": rate,
        })

    results.sort(key=lambda x: (x["success_rate"], x["total_recommendations"]), reverse=True)
    return results[:limit]
