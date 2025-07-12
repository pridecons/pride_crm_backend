# routes/lead_sources.py - Complete Fixed Version

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, DisconnectionError, IntegrityError
from pydantic import BaseModel, constr

from db.connection import get_db
from db.models import LeadSource, LeadResponse, Lead

router = APIRouter(
    prefix="/lead-config",
    tags=["lead-configuration"],
)


# Pydantic Schemas for Lead Source
class LeadSourceBase(BaseModel):
    name: constr(strip_whitespace=True, min_length=1, max_length=100)
    description: Optional[str] = None
    created_by: Optional[str] = None


class LeadSourceCreate(LeadSourceBase):
    pass


class LeadSourceUpdate(BaseModel):
    name: Optional[constr(strip_whitespace=True, min_length=1, max_length=100)] = None
    description: Optional[str] = None


class LeadSourceOut(LeadSourceBase):
    id: int
    
    class Config:
        from_attributes = True


# Pydantic Schemas for Lead Response
class LeadResponseBase(BaseModel):
    name: constr(strip_whitespace=True, min_length=1, max_length=100)
    lead_limit: Optional[int] = 0


class LeadResponseCreate(LeadResponseBase):
    pass


class LeadResponseUpdate(BaseModel):
    name: Optional[constr(strip_whitespace=True, min_length=1, max_length=100)] = None
    lead_limit: Optional[int] = None


class LeadResponseOut(LeadResponseBase):
    id: int
    
    class Config:
        from_attributes = True


# Lead Source Endpoints

@router.post("/sources/", response_model=LeadSourceOut, status_code=status.HTTP_201_CREATED)
def create_lead_source(
    source_in: LeadSourceCreate,
    db: Session = Depends(get_db),
):
    """Create a new lead source"""
    try:
        # Check for duplicate name
        existing = db.query(LeadSource).filter_by(name=source_in.name).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Lead source with name '{source_in.name}' already exists"
            )
        
        # Create lead source
        source = LeadSource(**source_in.dict())
        db.add(source)
        db.commit()
        db.refresh(source)
        
        return source
        
    except HTTPException:
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lead source name must be unique"
        )
    except (OperationalError, DisconnectionError):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating lead source: {str(e)}"
        )


@router.get("/sources/", response_model=List[LeadSourceOut])
def get_all_lead_sources(
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get all lead sources with optional search"""
    try:
        query = db.query(LeadSource)
        
        if search:
            query = query.filter(
                LeadSource.name.ilike(f"%{search}%") |
                LeadSource.description.ilike(f"%{search}%")
            )
        
        sources = query.offset(skip).limit(limit).all()
        return sources
        
    except (OperationalError, DisconnectionError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching lead sources: {str(e)}"
        )


@router.get("/sources/{source_id}", response_model=LeadSourceOut)
def get_lead_source(
    source_id: int,
    db: Session = Depends(get_db),
):
    """Get a specific lead source by ID"""
    try:
        source = db.query(LeadSource).filter_by(id=source_id).first()
        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead source not found"
            )
        return source
        
    except HTTPException:
        raise
    except (OperationalError, DisconnectionError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching lead source: {str(e)}"
        )


@router.put("/sources/{source_id}", response_model=LeadSourceOut)
def update_lead_source(
    source_id: int,
    source_in: LeadSourceUpdate,
    db: Session = Depends(get_db),
):
    """Update a lead source"""
    try:
        source = db.query(LeadSource).filter_by(id=source_id).first()
        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead source not found"
            )
        
        # Check for duplicate name if being updated
        update_data = response_in.dict(exclude_unset=True)
        if "name" in update_data:
            existing = db.query(LeadResponse).filter(
                LeadResponse.name == update_data["name"],
                LeadResponse.id != response_id
            ).first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Another lead response with name '{update_data['name']}' already exists"
                )
        
        # Update fields
        for field, value in update_data.items():
            setattr(response, field, value)
        
        db.commit()
        db.refresh(response)
        return response
        
    except HTTPException:
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lead response name must be unique"
        )
    except (OperationalError, DisconnectionError):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating lead response: {str(e)}"
        )


@router.delete("/responses/{response_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lead_response(
    response_id: int,
    force: bool = False,
    db: Session = Depends(get_db),
):
    """Delete a lead response"""
    try:
        response = db.query(LeadResponse).filter_by(id=response_id).first()
        if not response:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead response not found"
            )
        
        # Check if response is being used by leads
        leads_count = db.query(Lead).filter_by(lead_response_id=response_id).count()
        if leads_count > 0 and not force:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot delete lead response. It is being used by {leads_count} leads. Use force=true to delete anyway."
            )
        
        db.delete(response)
        db.commit()
        return None
        
    except HTTPException:
        raise
    except (OperationalError, DisconnectionError):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting lead response: {str(e)}"
        )


@router.get("/responses/{response_id}/stats")
def get_lead_response_stats(
    response_id: int,
    db: Session = Depends(get_db),
):
    """Get statistics for a lead response"""
    try:
        response = db.query(LeadResponse).filter_by(id=response_id).first()
        if not response:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead response not found"
            )
        
        # Get lead statistics
        total_leads = db.query(Lead).filter_by(lead_response_id=response_id).count()
        
        # Check if limit is exceeded
        limit_exceeded = False
        if response.lead_limit > 0 and total_leads >= response.lead_limit:
            limit_exceeded = True
        
        # Get recent leads
        recent_leads = db.query(Lead).filter_by(
            lead_response_id=response_id
        ).order_by(Lead.created_at.desc()).limit(10).all()
        
        return {
            "response": {
                "id": response.id,
                "name": response.name,
                "lead_limit": response.lead_limit
            },
            "statistics": {
                "total_leads": total_leads,
                "lead_limit": response.lead_limit,
                "limit_exceeded": limit_exceeded,
                "remaining_capacity": max(0, response.lead_limit - total_leads) if response.lead_limit > 0 else "unlimited"
            },
            "recent_leads": [
                {
                    "id": lead.id,
                    "full_name": lead.full_name,
                    "email": lead.email,
                    "mobile": lead.mobile,
                    "created_at": lead.created_at
                }
                for lead in recent_leads
            ]
        }
        
    except HTTPException:
        raise
    except (OperationalError, DisconnectionError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching lead response stats: {str(e)}"
        )


# Bulk operations

@router.post("/sources/bulk", response_model=List[LeadSourceOut])
def create_bulk_lead_sources(
    sources: List[LeadSourceCreate],
    db: Session = Depends(get_db),
):
    """Create multiple lead sources"""
    try:
        created_sources = []
        
        for source_data in sources:
            # Check for duplicate
            existing = db.query(LeadSource).filter_by(name=source_data.name).first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Lead source with name '{source_data.name}' already exists"
                )
            
            source = LeadSource(**source_data.dict())
            db.add(source)
            created_sources.append(source)
        
        db.commit()
        
        # Refresh all objects
        for source in created_sources:
            db.refresh(source)
        
        return created_sources
        
    except HTTPException:
        raise
    except (OperationalError, DisconnectionError):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating bulk lead sources: {str(e)}"
        )


@router.post("/responses/bulk", response_model=List[LeadResponseOut])
def create_bulk_lead_responses(
    responses: List[LeadResponseCreate],
    db: Session = Depends(get_db),
):
    """Create multiple lead responses"""
    try:
        created_responses = []
        
        for response_data in responses:
            # Check for duplicate
            existing = db.query(LeadResponse).filter_by(name=response_data.name).first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Lead response with name '{response_data.name}' already exists"
                )
            
            response = LeadResponse(**response_data.dict())
            db.add(response)
            created_responses.append(response)
        
        db.commit()
        
        # Refresh all objects
        for response in created_responses:
            db.refresh(response)
        
        return created_responses
        
    except HTTPException:
        raise
    except (OperationalError, DisconnectionError):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating bulk lead responses: {str(e)}"
        )


# Combined endpoint for dropdown data

@router.get("/dropdown-data")
def get_dropdown_data(db: Session = Depends(get_db)):
    """Get all sources and responses for dropdown menus"""
    try:
        sources = db.query(LeadSource).all()
        responses = db.query(LeadResponse).all()
        
        return {
            "sources": [
                {"id": s.id, "name": s.name, "description": s.description}
                for s in sources
            ],
            "responses": [
                {"id": r.id, "name": r.name, "lead_limit": r.lead_limit}
                for r in responses
            ]
        }
        
    except (OperationalError, DisconnectionError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching dropdown data: {str(e)}"
        )


# Search endpoints

@router.get("/sources/search")
def search_lead_sources(
    q: str,
    limit: int = 10,
    db: Session = Depends(get_db),
):
    """Search lead sources by name or description"""
    try:
        sources = db.query(LeadSource).filter(
            LeadSource.name.ilike(f"%{q}%") |
            LeadSource.description.ilike(f"%{q}%")
        ).limit(limit).all()
        
        return {
            "query": q,
            "results": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "created_by": s.created_by
                }
                for s in sources
            ]
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error searching lead sources: {str(e)}"
        )


@router.get("/responses/search")
def search_lead_responses(
    q: str,
    limit: int = 10,
    db: Session = Depends(get_db),
):
    """Search lead responses by name"""
    try:
        responses = db.query(LeadResponse).filter(
            LeadResponse.name.ilike(f"%{q}%")
        ).limit(limit).all()
        
        return {
            "query": q,
            "results": [
                {
                    "id": r.id,
                    "name": r.name,
                    "lead_limit": r.lead_limit
                }
                for r in responses
            ]
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error searching lead responses: {str(e)}"
        )


# Analytics endpoints

@router.get("/analytics/overview")
def get_analytics_overview(db: Session = Depends(get_db)):
    """Get overview analytics for sources and responses"""
    try:
        # Source analytics
        total_sources = db.query(LeadSource).count()
        sources_with_leads = db.query(LeadSource).join(Lead).distinct(LeadSource.id).count()
        
        # Response analytics
        total_responses = db.query(LeadResponse).count()
        responses_with_leads = db.query(LeadResponse).join(Lead).distinct(LeadResponse.id).count()
        
        # Top performing sources
        top_sources = db.query(
            LeadSource.name,
            db.func.count(Lead.id).label('lead_count')
        ).join(Lead).group_by(LeadSource.id, LeadSource.name).order_by(
            db.func.count(Lead.id).desc()
        ).limit(5).all()
        
        # Response usage
        response_usage = db.query(
            LeadResponse.name,
            db.func.count(Lead.id).label('lead_count'),
            LeadResponse.lead_limit
        ).join(Lead).group_by(
            LeadResponse.id, LeadResponse.name, LeadResponse.lead_limit
        ).all()
        
        return {
            "sources": {
                "total_sources": total_sources,
                "sources_with_leads": sources_with_leads,
                "sources_without_leads": total_sources - sources_with_leads,
                "top_performing": [
                    {"name": name, "lead_count": count}
                    for name, count in top_sources
                ]
            },
            "responses": {
                "total_responses": total_responses,
                "responses_with_leads": responses_with_leads,
                "responses_without_leads": total_responses - responses_with_leads,
                "usage_stats": [
                    {
                        "name": name,
                        "lead_count": count,
                        "lead_limit": limit_val,
                        "utilization_percentage": round((count / limit_val * 100), 2) if limit_val > 0 else 0
                    }
                    for name, count, limit_val in response_usage
                ]
            }
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching analytics: {str(e)}"
        )


# Export endpoints

@router.get("/export/sources")
def export_lead_sources(
    format: str = "json",  # json, csv
    db: Session = Depends(get_db),
):
    """Export all lead sources"""
    try:
        sources = db.query(LeadSource).all()
        
        if format.lower() == "csv":
            import csv
            import io
            
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(["ID", "Name", "Description", "Created By"])
            
            # Write data
            for source in sources:
                writer.writerow([
                    source.id,
                    source.name,
                    source.description or "",
                    source.created_by or ""
                ])
            
            csv_content = output.getvalue()
            
            from fastapi.responses import Response
            return Response(
                content=csv_content,
                media_type="text/csv",
                headers={
                    "Content-Disposition": "attachment; filename=lead_sources.csv"
                }
            )
        
        else:  # JSON format
            return {
                "sources": [
                    {
                        "id": s.id,
                        "name": s.name,
                        "description": s.description,
                        "created_by": s.created_by
                    }
                    for s in sources
                ],
                "export_date": str(datetime.now()),
                "total_count": len(sources)
            }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error exporting sources: {str(e)}"
        )


@router.get("/export/responses")
def export_lead_responses(
    format: str = "json",  # json, csv
    db: Session = Depends(get_db),
):
    """Export all lead responses"""
    try:
        responses = db.query(LeadResponse).all()
        
        if format.lower() == "csv":
            import csv
            import io
            
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(["ID", "Name", "Lead Limit"])
            
            # Write data
            for response in responses:
                writer.writerow([
                    response.id,
                    response.name,
                    response.lead_limit
                ])
            
            csv_content = output.getvalue()
            
            from fastapi.responses import Response
            return Response(
                content=csv_content,
                media_type="text/csv",
                headers={
                    "Content-Disposition": "attachment; filename=lead_responses.csv"
                }
            )
        
        else:  # JSON format
            return {
                "responses": [
                    {
                        "id": r.id,
                        "name": r.name,
                        "lead_limit": r.lead_limit
                    }
                    for r in responses
                ],
                "export_date": str(datetime.now()),
                "total_count": len(responses)
            }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error exporting responses: {str(e)}"
        )
        update_data = source_in.dict(exclude_unset=True)
        if "name" in update_data:
            existing = db.query(LeadSource).filter(
                LeadSource.name == update_data["name"],
                LeadSource.id != source_id
            ).first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Another lead source with name '{update_data['name']}' already exists"
                )
        
        # Update fields
        for field, value in update_data.items():
            setattr(source, field, value)
        
        db.commit()
        db.refresh(source)
        return source
        
    except HTTPException:
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lead source name must be unique"
        )
    except (OperationalError, DisconnectionError):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating lead source: {str(e)}"
        )


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lead_source(
    source_id: int,
    force: bool = False,
    db: Session = Depends(get_db),
):
    """Delete a lead source"""
    try:
        source = db.query(LeadSource).filter_by(id=source_id).first()
        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead source not found"
            )
        
        # Check if source is being used by leads
        leads_count = db.query(Lead).filter_by(lead_source_id=source_id).count()
        if leads_count > 0 and not force:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot delete lead source. It is being used by {leads_count} leads. Use force=true to delete anyway."
            )
        
        db.delete(source)
        db.commit()
        return None
        
    except HTTPException:
        raise
    except (OperationalError, DisconnectionError):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting lead source: {str(e)}"
        )


@router.get("/sources/{source_id}/stats")
def get_lead_source_stats(
    source_id: int,
    db: Session = Depends(get_db),
):
    """Get statistics for a lead source"""
    try:
        source = db.query(LeadSource).filter_by(id=source_id).first()
        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead source not found"
            )
        
        # Get lead statistics
        total_leads = db.query(Lead).filter_by(lead_source_id=source_id).count()
        kyc_completed = db.query(Lead).filter_by(lead_source_id=source_id, kyc=True).count()
        
        # Get leads by status
        leads_by_status = {}
        status_results = db.query(Lead.lead_status, db.func.count(Lead.id)).filter_by(
            lead_source_id=source_id
        ).group_by(Lead.lead_status).all()
        
        for status_name, count in status_results:
            leads_by_status[status_name or "No Status"] = count
        
        return {
            "source": {
                "id": source.id,
                "name": source.name,
                "description": source.description
            },
            "statistics": {
                "total_leads": total_leads,
                "kyc_completed": kyc_completed,
                "kyc_percentage": round((kyc_completed / total_leads * 100), 2) if total_leads > 0 else 0,
                "leads_by_status": leads_by_status
            }
        }
        
    except HTTPException:
        raise
    except (OperationalError, DisconnectionError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching lead source stats: {str(e)}"
        )


# Lead Response Endpoints

@router.post("/responses/", response_model=LeadResponseOut, status_code=status.HTTP_201_CREATED)
def create_lead_response(
    response_in: LeadResponseCreate,
    db: Session = Depends(get_db),
):
    """Create a new lead response"""
    try:
        # Check for duplicate name
        existing = db.query(LeadResponse).filter_by(name=response_in.name).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Lead response with name '{response_in.name}' already exists"
            )
        
        # Create lead response
        response = LeadResponse(**response_in.dict())
        db.add(response)
        db.commit()
        db.refresh(response)
        
        return response
        
    except HTTPException:
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lead response name must be unique"
        )
    except (OperationalError, DisconnectionError):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating lead response: {str(e)}"
        )


@router.get("/responses/", response_model=List[LeadResponseOut])
def get_all_lead_responses(
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get all lead responses with optional search"""
    try:
        query = db.query(LeadResponse)
        
        if search:
            query = query.filter(LeadResponse.name.ilike(f"%{search}%"))
        
        responses = query.offset(skip).limit(limit).all()
        return responses
        
    except (OperationalError, DisconnectionError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching lead responses: {str(e)}"
        )


@router.get("/responses/{response_id}", response_model=LeadResponseOut)
def get_lead_response(
    response_id: int,
    db: Session = Depends(get_db),
):
    """Get a specific lead response by ID"""
    try:
        response = db.query(LeadResponse).filter_by(id=response_id).first()
        if not response:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead response not found"
            )
        return response
        
    except HTTPException:
        raise
    except (OperationalError, DisconnectionError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching lead response: {str(e)}"
        )


