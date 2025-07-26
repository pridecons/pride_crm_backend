# # routes/narration.py

# from typing import List, Optional
# from datetime import datetime

# from fastapi import APIRouter, Depends, HTTPException, status
# from pydantic import BaseModel
# from sqlalchemy.orm import Session

# from db.connection import get_db
# from db.models import NARRATION

# router = APIRouter(
#     prefix="/narrations",
#     tags=["narrations"],
# )


# # Pydantic schemas
# class NarrationBase(BaseModel):
#     entry_price: Optional[float] = None
#     stop_loss: Optional[float] = None
#     targets: Optional[float] = None
#     rational: Optional[str] = None
#     stock_name: Optional[str] = None
#     recommendation_type: Optional[str] = None


# class NarrationCreate(NarrationBase):
#     pass


# class NarrationUpdate(NarrationBase):
#     pass


# class NarrationOut(NarrationBase):
#     id: int
#     created_at: datetime
#     updated_at: datetime

#     class Config:
#         from_attributes = True


# # CRUD endpoints

# @router.post(
#     "/",
#     response_model=NarrationOut,
#     status_code=status.HTTP_201_CREATED,
#     summary="Create a new narration",
# )
# def create_narration(
#     payload: NarrationCreate,
#     db: Session = Depends(get_db),
# ):
#     new_item = NARRATION(**payload.dict())
#     db.add(new_item)
#     db.commit()
#     db.refresh(new_item)
#     return new_item


# @router.get(
#     "/",
#     response_model=List[NarrationOut],
#     summary="List all narrations",
# )
# def list_narrations(db: Session = Depends(get_db)):
#     return db.query(NARRATION).order_by(NARRATION.created_at.desc()).all()


# @router.get(
#     "/{item_id}",
#     response_model=NarrationOut,
#     summary="Get a narration by ID",
# )
# def get_narration(item_id: int, db: Session = Depends(get_db)):
#     item = db.query(NARRATION).filter_by(id=item_id).first()
#     if not item:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail="Narration not found",
#         )
#     return item


# @router.put(
#     "/{item_id}",
#     response_model=NarrationOut,
#     summary="Replace a narration",
# )
# def update_narration(
#     item_id: int,
#     payload: NarrationUpdate,
#     db: Session = Depends(get_db),
# ):
#     item = db.query(NARRATION).filter_by(id=item_id).first()
#     if not item:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail="Narration not found",
#         )
#     for field, value in payload.dict(exclude_unset=True).items():
#         setattr(item, field, value)
#     db.commit()
#     db.refresh(item)
#     return item


# @router.delete(
#     "/{item_id}",
#     status_code=status.HTTP_204_NO_CONTENT,
#     summary="Delete a narration",
# )
# def delete_narration(item_id: int, db: Session = Depends(get_db)):
#     item = db.query(NARRATION).filter_by(id=item_id).first()
#     if not item:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail="Narration not found",
#         )
#     db.delete(item)
#     db.commit()
#     return None

from fastapi import FastAPI, HTTPException, Depends, Query, APIRouter
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, desc
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from enum import Enum
from db.models import NARRATION
from db.connection import get_db

# Pydantic Models for Request/Response
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
    graph: Optional[str] = None
    rational: Optional[str] = None
    stock_name: Optional[str] = None
    recommendation_type: Optional[str] = None
    user_id: str

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



router = APIRouter(
    prefix="/recommendations",
    tags=["Recommendations"],
)

# Database dependency (aapko apna database session setup karna hoga)
def get_db():
    # Yahan aapka database session setup hoga
    pass

# 1. CREATE - Nai recommendation create karna
@router.post("/", response_model=NarrationResponse)
async def create_recommendation(
    recommendation: NarrationCreate,
    db: Session = Depends(get_db)
):
    """
    Nayi stock recommendation create karta hai
    """
    try:
        db_recommendation = NARRATION(**recommendation.dict())
        db.add(db_recommendation)
        db.commit()
        db.refresh(db_recommendation)
        return db_recommendation
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Error creating recommendation: {str(e)}")

# 2. GET - Single recommendation get karna
@router.get("/{recommendation_id}", response_model=NarrationResponse)
async def get_recommendation(
    recommendation_id: int,
    db: Session = Depends(get_db)
):
    """
    Specific recommendation ID se data get karta hai
    """
    recommendation = db.query(NARRATION).filter(NARRATION.id == recommendation_id).first()
    if not recommendation:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return recommendation

# 3. GET - All recommendations with filters
@router.get("/", response_model=List[NarrationResponse])
async def get_recommendations(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    stock_name: Optional[str] = Query(None, description="Filter by stock name"),
    status: Optional[StatusType] = Query(None, description="Filter by status"),
    recommendation_type: Optional[str] = Query(None, description="Filter by recommendation type"),
    date_from: Optional[date] = Query(None, description="Filter from date"),
    date_to: Optional[date] = Query(None, description="Filter to date"),
    limit: int = Query(100, description="Limit results"),
    offset: int = Query(0, description="Offset for pagination"),
    db: Session = Depends(get_db)
):
    """
    Recommendations list with filters
    """
    query = db.query(NARRATION)
    
    # Filters apply karna
    if user_id:
        query = query.filter(NARRATION.user_id == user_id)
    if stock_name:
        query = query.filter(NARRATION.stock_name.ilike(f"%{stock_name}%"))
    if status:
        query = query.filter(NARRATION.status == status)
    if recommendation_type:
        query = query.filter(NARRATION.recommendation_type == recommendation_type)
    if date_from:
        query = query.filter(NARRATION.created_at >= date_from)
    if date_to:
        query = query.filter(NARRATION.created_at <= date_to)
    
    # Sorting and pagination
    recommendations = query.order_by(desc(NARRATION.created_at)).offset(offset).limit(limit).all()
    return recommendations

# 4. UPDATE - Recommendation update karna (status, targets hit karna)
@router.put("/{recommendation_id}", response_model=NarrationResponse)
async def update_recommendation(
    recommendation_id: int,
    recommendation_update: NarrationUpdate,
    db: Session = Depends(get_db)
):
    """
    Recommendation update karta hai (jaise target hit, stop loss etc.)
    """
    db_recommendation = db.query(NARRATION).filter(NARRATION.id == recommendation_id).first()
    if not db_recommendation:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    
    # Update fields
    update_data = recommendation_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_recommendation, field, value)
    
    try:
        db.commit()
        db.refresh(db_recommendation)
        return db_recommendation
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Error updating recommendation: {str(e)}")

# 5. DELETE - Recommendation delete karna
@router.delete("/{recommendation_id}")
async def delete_recommendation(
    recommendation_id: int,
    db: Session = Depends(get_db)
):
    """
    Recommendation delete karta hai
    """
    db_recommendation = db.query(NARRATION).filter(NARRATION.id == recommendation_id).first()
    if not db_recommendation:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    
    try:
        db.delete(db_recommendation)
        db.commit()
        return {"message": "Recommendation deleted successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Error deleting recommendation: {str(e)}")

# 6. ANALYTICS - User wise analytics
@router.get("/user/{user_id}", response_model=AnalyticsResponse)
async def get_user_analytics(
    user_id: str,
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Specific user ki performance analytics
    """
    query = db.query(NARRATION).filter(NARRATION.user_id == user_id)
    
    if date_from:
        query = query.filter(NARRATION.created_at >= date_from)
    if date_to:
        query = query.filter(NARRATION.created_at <= date_to)
    
    recommendations = query.all()
    
    if not recommendations:
        raise HTTPException(status_code=404, detail="No recommendations found for this user")
    
    # Analytics calculate karna
    total_recommendations = len(recommendations)
    status_counts = {}
    returns = []
    
    for rec in recommendations:
        status = rec.status
        status_counts[status] = status_counts.get(status, 0) + 1
        
        # Return calculate karna (simple example)
        if rec.entry_price and rec.status in ['TARGET1_HIT', 'TARGET2_HIT', 'TARGET3_HIT']:
            if rec.status == 'TARGET1_HIT' and rec.targets:
                return_pct = ((rec.targets - rec.entry_price) / rec.entry_price) * 100
            elif rec.status == 'TARGET2_HIT' and rec.targets2:
                return_pct = ((rec.targets2 - rec.entry_price) / rec.entry_price) * 100
            elif rec.status == 'TARGET3_HIT' and rec.targets3:
                return_pct = ((rec.targets3 - rec.entry_price) / rec.entry_price) * 100
            else:
                return_pct = 0
            returns.append(return_pct)
        elif rec.entry_price and rec.status == 'STOP_LOSS_HIT' and rec.stop_loss:
            return_pct = ((rec.stop_loss - rec.entry_price) / rec.entry_price) * 100
            returns.append(return_pct)
    
    # Success rate calculate karna
    successful = status_counts.get('TARGET1_HIT', 0) + status_counts.get('TARGET2_HIT', 0) + status_counts.get('TARGET3_HIT', 0)
    closed_trades = successful + status_counts.get('STOP_LOSS_HIT', 0)
    success_rate = (successful / closed_trades * 100) if closed_trades > 0 else 0
    
    # Average return
    avg_return = sum(returns) / len(returns) if returns else None
    
    # Best and worst recommendations
    best_rec = None
    worst_rec = None
    if returns:
        best_return = max(returns)
        worst_return = min(returns)
        
        for i, rec in enumerate(recommendations):
            if i < len(returns):
                if returns[i] == best_return and not best_rec:
                    best_rec = {
                        "id": rec.id,
                        "stock_name": rec.stock_name,
                        "return_pct": best_return,
                        "status": rec.status
                    }
                if returns[i] == worst_return and not worst_rec:
                    worst_rec = {
                        "id": rec.id,
                        "stock_name": rec.stock_name,
                        "return_pct": worst_return,
                        "status": rec.status
                    }
    
    return AnalyticsResponse(
        user_id=user_id,
        total_recommendations=total_recommendations,
        open_recommendations=status_counts.get('OPEN', 0),
        target1_hit=status_counts.get('TARGET1_HIT', 0),
        target2_hit=status_counts.get('TARGET2_HIT', 0),
        target3_hit=status_counts.get('TARGET3_HIT', 0),
        stop_loss_hit=status_counts.get('STOP_LOSS_HIT', 0),
        closed_recommendations=status_counts.get('CLOSED', 0),
        success_rate=round(success_rate, 2),
        avg_return=round(avg_return, 2) if avg_return else None,
        best_recommendation=best_rec,
        worst_recommendation=worst_rec
    )

# 7. ANALYTICS - Overall team analytics
@router.get("/analytics/team")
async def get_team_analytics(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Puri team ki analytics
    """
    query = db.query(NARRATION)
    
    if date_from:
        query = query.filter(NARRATION.created_at >= date_from)
    if date_to:
        query = query.filter(NARRATION.created_at <= date_to)
    
    # User wise stats
    user_stats = db.query(
        NARRATION.user_id,
        func.count(NARRATION.id).label('total_recommendations'),
        func.sum(func.case(
            (NARRATION.status.in_(['TARGET1_HIT', 'TARGET2_HIT', 'TARGET3_HIT']), 1),
            else_=0
        )).label('successful_recommendations'),
        func.sum(func.case(
            (NARRATION.status == 'STOP_LOSS_HIT', 1),
            else_=0
        )).label('failed_recommendations')
    ).group_by(NARRATION.user_id)
    
    if date_from:
        user_stats = user_stats.filter(NARRATION.created_at >= date_from)
    if date_to:
        user_stats = user_stats.filter(NARRATION.created_at <= date_to)
    
    user_stats = user_stats.all()
    
    team_analytics = []
    for stat in user_stats:
        closed_trades = stat.successful_recommendations + stat.failed_recommendations
        success_rate = (stat.successful_recommendations / closed_trades * 100) if closed_trades > 0 else 0
        
        team_analytics.append({
            "user_id": stat.user_id,
            "total_recommendations": stat.total_recommendations,
            "successful_recommendations": stat.successful_recommendations,
            "failed_recommendations": stat.failed_recommendations,
            "success_rate": round(success_rate, 2)
        })
    
    # Sort by success rate
    team_analytics.sort(key=lambda x: x['success_rate'], reverse=True)
    
    return {
        "team_analytics": team_analytics,
        "summary": {
            "total_users": len(team_analytics),
            "total_recommendations": sum([x['total_recommendations'] for x in team_analytics]),
            "overall_success_rate": round(
                sum([x['successful_recommendations'] for x in team_analytics]) / 
                sum([x['successful_recommendations'] + x['failed_recommendations'] for x in team_analytics]) * 100
                if sum([x['successful_recommendations'] + x['failed_recommendations'] for x in team_analytics]) > 0 else 0, 2
            )
        }
    }

# 8. Bulk status update (multiple recommendations ka status update karna)
@router.put("/bulk-update")
async def bulk_update_status(
    updates: List[Dict[str, Any]],
    db: Session = Depends(get_db)
):
    """
    Multiple recommendations ka status ek saath update karna
    Expected format: [{"id": 1, "status": "TARGET1_HIT"}, {"id": 2, "status": "STOP_LOSS_HIT"}]
    """
    updated_count = 0
    
    try:
        for update in updates:
            recommendation_id = update.get("id")
            new_status = update.get("status")
            
            if recommendation_id and new_status:
                db_recommendation = db.query(NARRATION).filter(NARRATION.id == recommendation_id).first()
                if db_recommendation:
                    db_recommendation.status = new_status
                    updated_count += 1
        
        db.commit()
        return {"message": f"{updated_count} recommendations updated successfully"}
    
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Error in bulk update: {str(e)}")

# 9. Top performing stocks
@router.get("/analytics/top-stocks")
async def get_top_performing_stocks(
    limit: int = Query(10, description="Number of top stocks to return"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Top performing stocks ki list
    """
    query = db.query(
        NARRATION.stock_name,
        func.count(NARRATION.id).label('total_recommendations'),
        func.sum(func.case(
            (NARRATION.status.in_(['TARGET1_HIT', 'TARGET2_HIT', 'TARGET3_HIT']), 1),
            else_=0
        )).label('successful_recommendations')
    ).filter(NARRATION.stock_name.isnot(None))
    
    if date_from:
        query = query.filter(NARRATION.created_at >= date_from)
    if date_to:
        query = query.filter(NARRATION.created_at <= date_to)
    
    stocks = query.group_by(NARRATION.stock_name).all()
    
    stock_performance = []
    for stock in stocks:
        success_rate = (stock.successful_recommendations / stock.total_recommendations * 100) if stock.total_recommendations > 0 else 0
        stock_performance.append({
            "stock_name": stock.stock_name,
            "total_recommendations": stock.total_recommendations,
            "successful_recommendations": stock.successful_recommendations,
            "success_rate": round(success_rate, 2)
        })
    
    # Sort by success rate and total recommendations
    stock_performance.sort(key=lambda x: (x['success_rate'], x['total_recommendations']), reverse=True)
    
    return stock_performance[:limit]
