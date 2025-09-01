# routes/recommendations.py
import time
import logging
import aiofiles
from pathlib import Path

from fastapi import (
    APIRouter, Depends, HTTPException,
    Query, UploadFile, File, Form, status, BackgroundTasks
)
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, case
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from db.models import NARRATION
from db.connection import get_db
from routes.auth.auth_dependency import get_current_user
from routes.Rational.rational_pdf_gen import generate_signed_pdf
import io
import pandas as pd
from fastapi.responses import StreamingResponse, FileResponse
import zipfile
from fastapi import BackgroundTasks
import asyncio
from db.connection import SessionLocal
from typing import Literal
from typing import Union
from db.Schema.Rational import RecommendationNotFoundError, FileUploadError, PDFGenerationError,DatabaseOperationError,  StatusType, NarrationCreate, NarrationUpdate, NarrationResponse, AnalyticsResponse, ErrorResponse
from services.service_manager import distribution_rational

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/recommendations", tags=["Recommendations"])


# ── Helpers ─────────────────────────────────────────────────────────────────────
UPLOAD_DIR = "static/graphs"
ALLOWED_FILE_TYPES = {".jpg", ".jpeg", ".png", ".gif", ".pdf", ".svg"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

def _pdf_background_task(recommendation_id: int):
    """
    Fetch the freshly‐created recommendation, run generate_signed_pdf,
    write back the URL and commit, all outside the request.
    """
    db = SessionLocal()
    try:
        rec = db.query(NARRATION).filter(NARRATION.id == recommendation_id).first()
        if not rec or not rec.rational or not rec.rational.strip():
            return

        # run our async PDF gen in a sync context
        _, url_path, _ = asyncio.run(generate_signed_pdf(rec))

        rec.pdf = url_path
        db.commit()
        logger.info(f"Background PDF generated for recommendation {recommendation_id}: {url_path}")
    except Exception as e:
        logger.error(f"Background PDF generation failed for recommendation {recommendation_id}: {e}", exc_info=True)
    finally:
        db.close()


def ensure_upload_directory():
    """Ensure upload directory exists with proper permissions."""
    try:
        Path(UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
        return True
    except PermissionError:
        logger.error(f"Permission denied creating upload directory: {UPLOAD_DIR}")
        return False
    except Exception as e:
        logger.error(f"Failed to create upload directory: {e}")
        return False

def validate_file_upload(file: UploadFile) -> bool:
    """Validate uploaded file type and size."""
    if not file.filename:
        raise FileUploadError("No filename provided")
    
    # Check file extension
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in ALLOWED_FILE_TYPES:
        raise FileUploadError(f"File type {file_ext} not allowed. Allowed types: {', '.join(ALLOWED_FILE_TYPES)}")
    
    # Check file size (if available)
    if hasattr(file, 'size') and file.size and file.size > MAX_FILE_SIZE:
        raise FileUploadError(f"File size exceeds maximum allowed size of {MAX_FILE_SIZE / 1024 / 1024}MB")
    
    return True

def get_recommendation_or_404(db: Session, recommendation_id: int) -> NARRATION:
    """Get recommendation by ID or raise 404."""
    try:
        recommendation = db.query(NARRATION).filter(NARRATION.id == recommendation_id).first()
        if not recommendation:
            raise RecommendationNotFoundError(f"Recommendation with ID {recommendation_id} not found")
        return recommendation
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching recommendation {recommendation_id}: {e}")
        raise DatabaseOperationError("Database error occurred while fetching recommendation")

# ── 1. CREATE ───────────────────────────────────────────────────────────────────
@router.post("/", response_model=NarrationResponse, status_code=status.HTTP_201_CREATED)
async def create_recommendation(
    background_tasks: BackgroundTasks,
    entry_price: float                   = Form(...),
    stop_loss: Optional[float]           = Form(None),
    targets: float                       = Form(0),
    targets2: Optional[float]            = Form(None),
    targets3: Optional[float]            = Form(None),
    rational: Optional[str]              = Form(None),
    stock_name: Optional[str]            = Form(None),
    recommendation_type: Optional[Union[List[str], str]] = Form(None),
    graph: UploadFile                    = File(None),
    templateId: Optional[int]            = Form(None),
    message: Optional[str]            = Form(None),
    db: Session                          = Depends(get_db),
    current_user                        = Depends(get_current_user),
):
    try:
        # Validate input data
        if entry_price <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Entry price must be greater than 0"
            )
        
        if stop_loss is not None and stop_loss <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Stop loss must be greater than 0"
            )
    

        # Ensure upload directory exists
        if not ensure_upload_directory():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to initialize file upload system"
            )

        # Handle file upload
        graph_path: Optional[str] = None
        if graph and graph.filename:
            try:
                validate_file_upload(graph)
                
                # Generate safe filename
                timestamp = int(time.time())
                safe_filename = f"{current_user.employee_code}_{timestamp}_{graph.filename}"
                # safe_filename = f"Admin001_{timestamp}_{graph.filename}"
                file_path = Path(UPLOAD_DIR) / safe_filename
                
                # Save file
                content = await graph.read()
                if len(content) > MAX_FILE_SIZE:
                    raise FileUploadError(f"File size exceeds maximum allowed size of {MAX_FILE_SIZE / 1024 / 1024}MB")
                
                async with aiofiles.open(file_path, "wb") as out:
                    await out.write(content)
                
                graph_path = f"/static/graphs/{safe_filename}"
                logger.info(f"File uploaded successfully: {graph_path}")
                
            except FileUploadError as e:
                 raise HTTPException(
                     status_code=status.HTTP_400_BAD_REQUEST,
                     detail=str(e)
                 )
            except Exception as e:
                logger.error(f"Unexpected error during file upload: {e}", exc_info=True)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to save uploaded file"
                )
            
        if isinstance(recommendation_type, str):
         # accept comma-separated single field too
           recommendation_type = [s.strip() for s in recommendation_type.split(",") if s.strip()]


        # Create database record
        try:
            recommendation = NARRATION(
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
            
            db.add(recommendation)
            db.commit()
            db.refresh(recommendation)
            logger.info(f"Recommendation created successfully with ID: {recommendation.id}")

            
            
        except IntegrityError as e:
            db.rollback()
            logger.error(f"Database integrity error: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Data integrity constraint violation"
            )
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error during creation: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database error occurred while creating recommendation"
            )
        
        stock_details={
            'entry_price':entry_price,
            'stop_loss':stop_loss,
            'targets':targets,
            'targets2':targets2,
            'targets3':targets3,
            'stock_name':stock_name,
            'recommendation_type':recommendation_type
        }
        
        background_tasks.add_task(
            distribution_rational,
            recommendation.id,
            templateId,
            message,
            stock_details
        )

        # Generate PDF if rationale provided
        if rational and rational.strip():
            background_tasks.add_task(_pdf_background_task, recommendation.id)

        return recommendation

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in create_recommendation: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the recommendation"
        )

# ── 3. READ (list + filters) ───────────────────────────────────────────────────
@router.get("/", response_model=List[NarrationResponse])
def get_recommendations(
    user_id: Optional[str]               = Query(None),
    stock_name: Optional[str]            = Query(None),
    recommendation_status: Optional[StatusType] = Query(
         None, alias="status", description="Filter by status"
     ),
    recommendation_type: Optional[List[str]]   = Query(None),
    date_from: Optional[date]            = Query(None),
    date_to: Optional[date]              = Query(None),
    limit: int                           = Query(100, ge=1, le=1000),
    offset: int                          = Query(0, ge=0),
    db: Session                          = Depends(get_db),
):
    try:
        # Validate date range
        if date_from and date_to and date_from > date_to:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="date_from cannot be later than date_to"
            )
    

        # Build query with filters
        query = db.query(NARRATION)
        
        if user_id:
            query = query.filter(NARRATION.user_id == user_id)
        if stock_name:
            query = query.filter(NARRATION.stock_name.ilike(f"%{stock_name.strip()}%"))
        if recommendation_status:
            query = query.filter(NARRATION.status == recommendation_status)
        if recommendation_type:
            query = query.filter(NARRATION.recommendation_type.overlap(recommendation_type))
        if date_from:
            query = query.filter(NARRATION.created_at >= date_from)
        if date_to:
            # Include the entire day
            query = query.filter(NARRATION.created_at <= datetime.combine(date_to, datetime.max.time()))

        recommendations = (
            query.order_by(desc(NARRATION.created_at))
                 .offset(offset)
                 .limit(limit)
                 .all()
        )
        
        return recommendations

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching recommendations: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while fetching recommendations"
        )
    except Exception as e:
        logger.error(f"Unexpected error fetching recommendations: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while fetching recommendations"
        )


# ── 4. UPDATE ───────────────────────────────────────────────────────────────────
@router.put("/{recommendation_id}", response_model=NarrationResponse)
async def update_recommendation(
    background_tasks: BackgroundTasks,
    recommendation_id: int,
    payload: NarrationUpdate,
    db: Session = Depends(get_db),
):
    try:
        if recommendation_id <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Recommendation ID must be a positive integer"
            )

        # Validate payload data
        if payload.entry_price is not None and payload.entry_price <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Entry price must be greater than 0"
            )
        
        if payload.stop_loss is not None and payload.stop_loss <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Stop loss must be greater than 0"
            )

        recommendation = get_recommendation_or_404(db, recommendation_id)
        
        # Update fields
        update_data = payload.dict(exclude_unset=True)
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields provided for update"
            )

        for field, value in update_data.items():
            if hasattr(recommendation, field):
                setattr(recommendation, field, value)

        try:
            db.commit()
            db.refresh(recommendation)
            logger.info(f"Recommendation {recommendation_id} updated successfully")
            
        except IntegrityError as e:
            db.rollback()
            logger.error(f"Database integrity error during update: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Data integrity constraint violation"
            )
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error during update: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database error occurred while updating recommendation"
            )

        # Regenerate PDF if rationale exists
        if recommendation.rational and recommendation.rational.strip():
           background_tasks.add_task(_pdf_background_task, recommendation_id)

        return recommendation

    except HTTPException:
        raise
    except RecommendationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recommendation with ID {recommendation_id} not found"
        )
    except DatabaseOperationError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error updating recommendation {recommendation_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating the recommendation"
        )


# ── 4b. STATUS-ONLY UPDATE ──────────────────────────────────────────────────────
@router.put("/status/{recommendation_id}", response_model=NarrationResponse)
def update_recommendation_status(
    recommendation_id: int,
    status_update: StatusType,
    db: Session = Depends(get_db),
):
    try:
        if recommendation_id <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Recommendation ID must be a positive integer"
            )

        recommendation = get_recommendation_or_404(db, recommendation_id)
        
        # Validate status transition (optional business logic)
        old_status = recommendation.status
        recommendation.status = status_update

        try:
            db.commit()
            db.refresh(recommendation)
            logger.info(f"Recommendation {recommendation_id} status updated from {old_status} to {status_update}")
            
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error during status update: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database error occurred while updating status"
            )

        return recommendation

    except HTTPException:
        raise
    except RecommendationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recommendation with ID {recommendation_id} not found"
        )
    except DatabaseOperationError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error updating status for recommendation {recommendation_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating the status"
        )


# ── 5. DELETE ───────────────────────────────────────────────────────────────────
@router.delete("/{recommendation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recommendation(
    recommendation_id: int,
    db: Session = Depends(get_db),
):
    try:
        if recommendation_id <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Recommendation ID must be a positive integer"
            )

        recommendation = get_recommendation_or_404(db, recommendation_id)
        
        # Clean up associated files before deletion
        if recommendation.graph:
            try:
                graph_file_path = Path(recommendation.graph.lstrip('/'))
                if graph_file_path.exists():
                    graph_file_path.unlink()
                    logger.info(f"Deleted graph file: {graph_file_path}")
            except Exception as e:
                logger.warning(f"Failed to delete graph file {recommendation.graph}: {e}")

        if recommendation.pdf:
            try:
                pdf_file_path = Path(recommendation.pdf.lstrip('/'))
                if pdf_file_path.exists():
                    pdf_file_path.unlink()
                    logger.info(f"Deleted PDF file: {pdf_file_path}")
            except Exception as e:
                logger.warning(f"Failed to delete PDF file {recommendation.pdf}: {e}")

        try:
            db.delete(recommendation)
            db.commit()
            logger.info(f"Recommendation {recommendation_id} deleted successfully")
            
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error during deletion: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database error occurred while deleting recommendation"
            )

    except HTTPException:
        raise
    except RecommendationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recommendation with ID {recommendation_id} not found"
        )
    except DatabaseOperationError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error deleting recommendation {recommendation_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting the recommendation"
        )

# ── ADDITIONAL HELPER ENDPOINTS ─────────────────────────────────────────────────
@router.get("/analytics/summary")
def get_analytics_summary(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date]   = Query(None),
    db: Session               = Depends(get_db),
):
    """Get overall system analytics summary."""
    try:
        # Validate date range
        if date_from and date_to and date_from > date_to:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="date_from cannot be later than date_to"
            )

        base_query = db.query(NARRATION)
        if date_from:
            base_query = base_query.filter(NARRATION.created_at >= date_from)
        if date_to:
            base_query = base_query.filter(
                NARRATION.created_at <= datetime.combine(date_to, datetime.max.time())
            )

        # Get overall counts
        total_recommendations = base_query.count()
        if total_recommendations == 0:
            return {
                "total_recommendations": 0,
                "active_users": 0,
                "success_rate": 0.0,
                "status_distribution": {},
                "recommendation_types": {},
                "date_range": {"from": None, "to": None}
            }

        # Status distribution
        status_stats = (
            base_query
            .with_entities(NARRATION.status, func.count(NARRATION.id).label("count"))
            .group_by(NARRATION.status)
            .all()
        )
        status_distribution = {status: count for status, count in status_stats}

        # Recommendation types distribution
        type_stats = (
            base_query
            .filter(NARRATION.recommendation_type.isnot(None))
            .with_entities(
                func.unnest(NARRATION.recommendation_type).label("rec_type"),
                func.count(NARRATION.id).label("count")
            )
            .group_by("rec_type")
            .all()
        )
        recommendation_types = {rec_type: count for rec_type, count in type_stats}

        # Active users count
        active_users = (
            base_query
            .with_entities(NARRATION.user_id)
            .distinct()
            .count()
        )

        # Overall success rate
        successful_count = sum(
            status_distribution.get(s, 0)
            for s in ["TARGET1_HIT", "TARGET2_HIT", "TARGET3_HIT"]
        )
        closed_count = successful_count + status_distribution.get("STOP_LOSS_HIT", 0)
        success_rate = round(successful_count / closed_count * 100, 2) if closed_count else 0.0

        # If no filters, fetch the actual min/max dates from the entire table
        if not date_from and not date_to:
            min_dt, max_dt = db.query(
                func.min(NARRATION.created_at),
                func.max(NARRATION.created_at)
            ).one()
            dr_from = min_dt.date().isoformat() if min_dt else None
            dr_to   = max_dt.date().isoformat() if max_dt else None
        else:
            dr_from = date_from.isoformat() if date_from else None
            dr_to   = date_to.isoformat()   if date_to   else None

        return {
            "total_recommendations": total_recommendations,
            "active_users": active_users,
            "success_rate": success_rate,
            "status_distribution": status_distribution,
            "recommendation_types": recommendation_types,
            "date_range": {"from": dr_from, "to": dr_to}
        }

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching analytics summary: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error occurred while fetching analytics summary"
        )
    except Exception as e:
        logger.error(f"Unexpected error fetching analytics summary: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while fetching analytics summary"
        )


@router.get(
    "/xlsx/export",
    summary="Export recommendations (including rational) to XLSX",
    response_class=StreamingResponse
)
def export_recommendations_xlsx(
    user_id: Optional[str]               = Query(None, description="Filter by user_id"),
    stock_name: Optional[str]            = Query(None, description="Filter by stock_name (ILIKE)"),
    status: Optional[StatusType]         = Query(None, description="Filter by status"),
    recommendation_type: Optional[List[str]]   = Query(None, description="Filter by recommendation_type"),
    date_from: Optional[date]            = Query(None, description="Filter created_at >= date_from"),
    date_to: Optional[date]              = Query(None, description="Filter created_at <= date_to"),
    columns: Optional[List[str]]         = Query(
        None,
        description="List of columns to include in the XLSX, e.g. columns=ID&columns=Rational"
    ),
    sort_order: Literal["asc", "desc"]   = Query(
        "desc",
        description="Sort by creation date: `asc` or `desc`"
    ),
    db: Session                          = Depends(get_db),
):
    """
    Apply filters, then stream back an XLSX file containing only the requested columns.
    """
    # 1) Build query with filters
    q = db.query(NARRATION)
    if user_id:
        q = q.filter(NARRATION.user_id == user_id)
    if stock_name:
        q = q.filter(NARRATION.stock_name.ilike(f"%{stock_name}%"))
    if status:
        q = q.filter(NARRATION.status == status)
    if recommendation_type:
        q = q.filter(NARRATION.recommendation_type.overlap(recommendation_type))
    if date_from:
        q = q.filter(NARRATION.created_at >= date_from)
    if date_to:
        q = q.filter(NARRATION.created_at <= date_to)

    # 2) Apply ordering
    if sort_order == "asc":
        recs = q.order_by(NARRATION.created_at.asc()).all()
    else:
        recs = q.order_by(NARRATION.created_at.desc()).all()
    
    if not recs:
        raise HTTPException(
            status_code=404,
            detail="No recommendations found for the given filters."
        )

    # 3) Transform to list of dicts
    data = []
    for r in recs:
        data.append({
            "ID": r.id,
            "User ID": r.user_id,
            "Stock Name": r.stock_name or "",
            "Entry Price": r.entry_price or "",
            "Stop Loss": r.stop_loss or "",
            "Target 1": r.targets or "",
            "Target 2": r.targets2 or "",
            "Target 3": r.targets3 or "",
            "Status": r.status,
            "Rational": r.rational or "",
            "Recommendation Type": ",".join(r.recommendation_type) if r.recommendation_type else "",
            "Created At": r.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "Updated At": r.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
        })

    # 4) Build DataFrame and filter columns if requested
    df = pd.DataFrame(data)
    if columns:
        invalid = set(columns) - set(df.columns)
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid column names: {', '.join(invalid)}"
            )
        df = df[columns]

    # 5) Write to Excel in-memory
    output = io.BytesIO()
    try:
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Recommendations")
        output.seek(0)
    except Exception as e:
        logger.error("Failed to generate XLSX: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Could not generate Excel file"
        )

    # 6) Stream it back
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"recommendations_{timestamp}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get(
    "/{recommendation_id}/pdf",
    summary="Download the signed PDF for a recommendation",
    responses={
        200: {"content": {"application/pdf": {}}},
        404: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def download_recommendation_pdf(
    recommendation_id: int,
    db: Session = Depends(get_db),
):
    # 1) fetch or 404
    recommendation = get_recommendation_or_404(db, recommendation_id)

    # 2) ensure PDF was generated
    if not recommendation.pdf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No PDF available for recommendation {recommendation_id}"
        )

    # 3) resolve file path and check existence
    pdf_path = Path(recommendation.pdf.lstrip("/"))
    if not pdf_path.exists() or not pdf_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PDF file not found on server for recommendation {recommendation_id}"
        )

    # 4) return FileResponse
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=pdf_path.name,
        headers={"Content-Disposition": f"inline; filename={pdf_path.name}"}
    )

@router.get(
    "/pdfs/export",
    summary="Export matching recommendation PDFs as a ZIP",
    response_class=StreamingResponse,
)
def export_pdfs_zip(
    user_id: Optional[str]               = Query(None, description="Filter by user_id"),
    stock_name: Optional[str]            = Query(None, description="Filter by stock_name (ILIKE)"),
    status: Optional[StatusType]         = Query(None, description="Filter by status"),
    recommendation_type: Optional[str]   = Query(None, description="Filter by recommendation_type"),
    date_from: Optional[date]            = Query(None, description="Created at >= date_from"),
    date_to: Optional[date]              = Query(None, description="Created at <= date_to"),
    db: Session                          = Depends(get_db),
):
    """
    Apply filters on recommendations, collect their signed PDFs,
    and stream them back as a ZIP file. Only includes records
    where `pdf` is set and the file actually exists.
    """
    # 1) Build query with the same filters
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
        q = q.filter(NARRATION.created_at <= datetime.combine(date_to, datetime.max.time()))

    recs = q.all()

    if not recs:
        raise HTTPException(
            status_code=404,
            detail="No recommendations found for the given filters."
        )

    # 2) Collect valid PDF paths
    pdf_items: List[Path] = []
    for r in recs:
        if not r.pdf:
            continue
        pdf_path = Path(r.pdf.lstrip("/"))
        print("pdf_path : ",pdf_path)
        if pdf_path.exists() and pdf_path.is_file():
            pdf_items.append(pdf_path)

    # 3) Create in‑memory ZIP
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for path in pdf_items:
            # preserve the original filename on disk
            zipf.write(path, arcname=path.name)
    zip_buffer.seek(0)

    # 4) Stream back to client
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"recommendation_pdfs_{timestamp}.zip"
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

