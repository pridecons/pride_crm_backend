# routes/bulk_leads.py - Complete Fixed Version

import os
import csv
import io
import json
from typing import Optional, List, Dict, Any
from datetime import datetime, date

from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, DisconnectionError
from pydantic import BaseModel

from db.connection import get_db
from db.models import Lead, LeadSource, UserDetails

router = APIRouter(
    prefix="/bulk-leads",
    tags=["bulk-lead-upload"],
)


# Pydantic Schemas
class BulkUploadResponse(BaseModel):
    total_rows: int
    successful_uploads: int
    failed_uploads: int
    duplicates_skipped: int
    errors: List[Dict[str, Any]]
    uploaded_leads: List[int]


# Helper Functions
def validate_csv_file(file: UploadFile) -> bool:
    """Validate if uploaded file is a CSV"""
    return file.filename.lower().endswith('.csv')


def parse_csv_content(file_content: str) -> List[List[str]]:
    """Parse CSV content and return rows"""
    reader = csv.reader(io.StringIO(file_content))
    return list(reader)


def get_column_value(row: List[str], idx: int) -> Optional[str]:
    """Safely get and strip value from row at given index"""
    if idx < 0 or idx >= len(row):
        return None
    val = row[idx].strip()
    return val or None


def process_segment(text: str) -> List[str]:
    """Split comma‑separated segment values"""
    parts = [s.strip() for s in text.split(',')]
    return [p for p in parts if p]


# Main Upload Endpoint
@router.post("/upload", response_model=BulkUploadResponse)
async def upload_bulk_leads(
    lead_source_id: int = Form(...),
    employee_code: str = Form(...),
    branch_id: int = Form(...),
    mobile_column: int = Form(...),
    name_column: int = Form(...),
    email_column: int = Form(...),
    city_column: int = Form(...),
    address_column: int = Form(...),
    segment_column: int = Form(...),
    occupation_column: int = Form(...),
    investment_column: int = Form(...),
    csv_file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Upload bulk leads from CSV.
    Only 'mobile' is required; empty table rows will succeed if mobile is present.
    Duplicate mobiles are skipped.
    """
    try:
        # 1) Validate CSV
        if not validate_csv_file(csv_file):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Please upload a valid CSV file"
            )

        # 2) Lookup lead source
        lead_source = db.query(LeadSource).filter_by(id=lead_source_id).first()
        if not lead_source:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Lead source {lead_source_id} not found"
            )

        # 3) Lookup employee
        employee = db.query(UserDetails).filter_by(employee_code=employee_code).first()
        if not employee:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Employee {employee_code} not found"
            )

        # 4) Read & parse CSV
        content = await csv_file.read()
        rows = parse_csv_content(content.decode('utf-8'))
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CSV file is empty"
            )
        data_rows = rows[1:] if len(rows) > 1 else rows

        # 5) Initialize counters
        total_rows = len(data_rows)
        successful_uploads = 0
        failed_uploads = 0
        duplicates_skipped = 0
        errors: List[Dict[str, Any]] = []
        uploaded_leads: List[int] = []

        # 6) Process each row
        for idx, row in enumerate(data_rows, start=2):
            try:
                # Extract all fields
                mobile       = get_column_value(row, mobile_column)
                name         = get_column_value(row, name_column)
                email        = get_column_value(row, email_column)
                city         = get_column_value(row, city_column)
                address      = get_column_value(row, address_column)
                segment_text = get_column_value(row, segment_column)
                occupation   = get_column_value(row, occupation_column)
                investment   = get_column_value(row, investment_column)

                # --- VALIDATION: only mobile is required ---
                if not mobile:
                    errors.append({
                        "row": idx,
                        "errors": ["Missing mobile number"],
                        "data": row
                    })
                    failed_uploads += 1
                    continue

                # --- DUPLICATE CHECK: skip if same mobile exists ---
                existing = db.query(Lead).filter(Lead.mobile == mobile).first()
                if existing:
                    errors.append({
                        "row": idx,
                        "errors": ["Duplicate mobile number"],
                        "existing_lead_id": existing.id,
                        "data": row
                    })
                    duplicates_skipped += 1
                    continue

                # --- PROCESS SEGMENT ---
                segments_json = None
                if segment_text:
                    segs = process_segment(segment_text)
                    if segs:
                        segments_json = json.dumps(segs)

                # --- BUILD LEAD DATA ---
                lead_data = {
                    "mobile": mobile,
                    "full_name": name,
                    "email": email,
                    "city": city,
                    "address": address,
                    "occupation": occupation,
                    "investment": investment,
                    "segment": segments_json,
                    "lead_source_id": lead_source_id,
                    "created_by": getattr(employee.role, "value", str(employee.role)),
                    "created_by_name": employee.employee_code,
                    "branch_id": branch_id,
                }
                # remove None fields
                lead_data = {k: v for k, v in lead_data.items() if v is not None}

                # --- INSERT LEAD ---
                lead = Lead(**lead_data)
                db.add(lead)
                db.flush()  # to get ID

                uploaded_leads.append(lead.id)
                successful_uploads += 1

            except Exception as ex:
                errors.append({
                    "row": idx,
                    "errors": [f"DB error: {str(ex)}"],
                    "data": row
                })
                failed_uploads += 1
                continue

        # 7) Commit successful inserts
        if successful_uploads:
            db.commit()

        # 8) Return summary
        return BulkUploadResponse(
            total_rows=total_rows,
            successful_uploads=successful_uploads,
            failed_uploads=failed_uploads,
            duplicates_skipped=duplicates_skipped,
            errors=errors,
            uploaded_leads=uploaded_leads
        )

    except HTTPException:
        raise
    except (OperationalError, DisconnectionError):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection lost. Please try again."
        )
    except Exception as ex:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {str(ex)}"
        )


@router.get("/template")
async def download_csv_template():
    """Download CSV template for bulk upload"""
    template = [
        ["Name", "Mobile", "Email", "City", "Address", "Segment", "Occupation", "Investment"],
        ["John Doe", "9876543210", "john@example.com", "Mumbai", "123 Main St", "Tech,Finance", "Engineer", "5-10 lakhs"],
    ]
    output = io.StringIO()
    csv.writer(output).writerows(template)
    from fastapi.responses import Response
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=bulk_leads_template.csv"}
    )


@router.get("/upload-stats")
def get_upload_statistics(
    employee_code: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
):
    """Get bulk upload statistics"""
    try:
        query = db.query(Lead)
        if employee_code:
            query = query.filter(Lead.created_by_name == employee_code)
        if date_from:
            query = query.filter(Lead.created_at >= date_from)
        if date_to:
            from datetime import time
            end_dt = datetime.combine(date_to, time.max)
            query = query.filter(Lead.created_at <= end_dt)

        total = query.count()
        source_stats = (
            db.query(LeadSource.name, db.func.count(Lead.id))
            .join(Lead)
            .group_by(LeadSource.name)
            .all()
        )
        employee_stats = (
            db.query(
                Lead.created_by_name.label("employee_code"),
                Lead.created_by.label("role"),
                db.func.count(Lead.id).label("count")
            )
            .filter(Lead.created_by_name.isnot(None))
            .group_by(Lead.created_by_name, Lead.created_by)
            .all()
        )
        recent = query.order_by(Lead.created_at.desc()).limit(10).all()

        return {
            "total_leads": total,
            "source_wise_stats": [
                {"source": name, "count": cnt} for name, cnt in source_stats
            ],
            "employee_wise_stats": [
                {"employee_code": emp, "role": role, "count": cnt}
                for emp, role, cnt in employee_stats
            ],
            "recent_uploads": [
                {
                    "id": ld.id,
                    "name": ld.full_name,
                    "mobile": ld.mobile,
                    "email": ld.email,
                    "created_by_role": ld.created_by,
                    "created_by_employee_code": ld.created_by_name,
                    "created_at": ld.created_at,
                }
                for ld in recent
            ],
        }
    except Exception as ex:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching stats: {str(ex)}"
        )


@router.post("/validate-data")
async def validate_bulk_data(
    csv_file: UploadFile = File(...),
    mobile_column: int = Form(...),
    name_column: int = Form(...),
    email_column: int = Form(...),
    db: Session = Depends(get_db),
):
    """Validate bulk data without uploading"""
    try:
        content = await csv_file.read()
        rows = parse_csv_content(content.decode('utf-8'))
        if len(rows) <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CSV must have at least one data row"
            )
        data_rows = rows[1:]
        results = []
        for idx, row in enumerate(data_rows, start=2):
            mobile = get_column_value(row, mobile_column)
            name = get_column_value(row, name_column)
            email = get_column_value(row, email_column)
            errs, warns = [], []
            if not mobile:
                errs.append("Mobile is required")
            else:
                # duplicate mobile?
                dup = db.query(Lead).filter(Lead.mobile == mobile).first()
                if dup:
                    warns.append(f"Duplicate mobile – Lead ID {dup.id}")
            results.append({
                "row": idx,
                "data": {"mobile": mobile, "name": name, "email": email},
                "errors": errs,
                "warnings": warns,
                "valid": not errs
            })
        total = len(results)
        valid = sum(1 for r in results if r["valid"])
        return {
            "filename": csv_file.filename,
            "summary": {
                "total_rows": total,
                "valid_rows": valid,
                "invalid_rows": total - valid,
                "rows_with_warnings": sum(1 for r in results if r["warnings"])
            },
            "validation_results": results
        }
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Validation error: {str(ex)}"
        )


@router.get("/recent-uploads")
def get_recent_uploads(
    limit: int = 20,
    employee_code: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get recent bulk uploads"""
    try:
        q = db.query(Lead).filter(Lead.created_by_name.isnot(None))
        if employee_code:
            q = q.filter(Lead.created_by_name == employee_code)
        recents = q.order_by(Lead.created_at.desc()).limit(limit).all()
        return {
            "recent_uploads": [
                {
                    "id": ld.id,
                    "full_name": ld.full_name,
                    "mobile": ld.mobile,
                    "email": ld.email,
                    "city": ld.city,
                    "created_by": ld.created_by,
                    "created_by_name": ld.created_by_name,
                    "created_at": ld.created_at,
                    "lead_source_id": ld.lead_source_id,
                }
                for ld in recents
            ]
        }
    except Exception as ex:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching recent uploads: {str(ex)}"
        )


@router.delete("/cleanup-failed")
def cleanup_failed_uploads(
    employee_code: str,
    date_from: date,
    dry_run: bool = True,
    db: Session = Depends(get_db),
):
    """Cleanup failed or incomplete uploads"""
    try:
        q = db.query(Lead).filter(
            Lead.created_by_name == employee_code,
            Lead.created_at >= date_from,
            Lead.full_name.is_(None)
        )
        leads = q.all()
        if dry_run:
            return {
                "dry_run": True,
                "leads_found": len(leads),
                "leads": [
                    {"id": ld.id, "mobile": ld.mobile, "email": ld.email, "created_at": ld.created_at}
                    for ld in leads
                ]
            }
        deleted = q.delete()
        db.commit()
        return {
            "dry_run": False,
            "deleted_count": deleted,
            "message": f"Deleted {deleted} incomplete leads"
        }
    except Exception as ex:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Cleanup error: {str(ex)}"
        )

