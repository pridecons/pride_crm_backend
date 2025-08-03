import csv
import io
import json
from typing import Optional, List, Dict, Any
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
