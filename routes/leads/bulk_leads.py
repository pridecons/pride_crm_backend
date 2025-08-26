import csv
import io
import json
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form
from sqlalchemy.orm import Session
from pydantic import BaseModel
from routes.auth.auth_dependency import get_current_user
from db.connection import get_db
from db.models import Lead, LeadSource, UserDetails
from utils.validation_utils import UniquenessValidator, FormatValidator

router = APIRouter(
    prefix="/bulk-leads",
    tags=["bulk-lead-upload"],
)

# -------------------- Schemas --------------------
class BulkUploadResponse(BaseModel):
    total_rows: int
    successful_uploads: int
    failed_uploads: int
    duplicates_skipped: int
    errors: List[Dict[str, Any]]
    uploaded_leads: List[int]
    validation_summary: Dict[str, int]

# -------------------- Helpers --------------------
def validate_csv_file(file: Optional[UploadFile]) -> bool:
    """Validate if uploaded file is a CSV and provided."""
    if not file or not file.filename:
        return False
    return file.filename.lower().endswith(".csv")

def parse_csv_content(file_content: str) -> List[List[str]]:
    """Parse CSV content and return rows."""
    reader = csv.reader(io.StringIO(file_content))
    return list(reader)

def get_column_value(row: List[str], idx: Optional[int]) -> Optional[str]:
    """Safely get and strip value from row at given index (0-based)."""
    if idx is None:
        return None
    if idx < 0 or idx >= len(row):
        return None
    val = (row[idx] or "").strip()
    return val or None

def process_segment(text: Optional[str]) -> List[str]:
    """Split comma-separated segment values."""
    if not text:
        return []
    parts = [s.strip() for s in text.split(",")]
    return [p for p in parts if p]

def validate_single_lead_data(row_data: dict, db: Session, row_num: int) -> List[str]:
    """
    Validate a single lead's data for format and uniqueness.
    Returns list of validation errors.
    """
    errors: List[str] = []
    validator = UniquenessValidator(db)
    format_validator = FormatValidator()

    # Format validation
    try:
        # Email
        if row_data.get("email"):
            if not format_validator.validate_email_format(row_data["email"]):
                errors.append("Invalid email format")
        # Mobile
        if row_data.get("mobile"):
            if not format_validator.validate_mobile_format(row_data["mobile"]):
                errors.append("Mobile number must be exactly 10 digits")
        # PAN
        if row_data.get("pan"):
            if not format_validator.validate_pan_format(row_data["pan"]):
                errors.append("Invalid PAN format. PAN must be in format ABCDE1234F")
    except Exception as e:
        errors.append(f"Format validation error: {str(e)}")

    # Uniqueness validation
    try:
        if row_data.get("email"):
            email_conflict = validator.check_email_uniqueness(row_data["email"])
            if email_conflict:
                errors.append(f"Email duplicate: {email_conflict['message']}")
        if row_data.get("mobile"):
            mobile_conflict = validator.check_mobile_uniqueness(row_data["mobile"])
            if mobile_conflict:
                errors.append(f"Mobile duplicate: {mobile_conflict['message']}")
        if row_data.get("pan"):
            pan_conflict = validator.check_pan_uniqueness(row_data["pan"])
            if pan_conflict:
                errors.append(f"PAN duplicate: {pan_conflict['message']}")
    except Exception as e:
        errors.append(f"Uniqueness validation error: {str(e)}")

    return errors

# -------------------- Endpoint --------------------
@router.post("/upload", response_model=BulkUploadResponse)
async def upload_bulk_leads(
    # Only mobile_column required
    mobile_column: int = Form(...),

    # Everything else optional
    lead_source_id: Optional[int] = Form(None),
    branch_id: Optional[int] = Form(None),
    name_column: Optional[int] = Form(None),
    email_column: Optional[int] = Form(None),
    city_column: Optional[int] = Form(None),
    address_column: Optional[int] = Form(None),
    segment_column: Optional[int] = Form(None),
    occupation_column: Optional[int] = Form(None),
    investment_column: Optional[int] = Form(None),
    pan_column: Optional[int] = Form(None),

    csv_file: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Upload bulk leads from CSV with comprehensive validation.
    ONLY 'mobile_column' is required. Other columns are optional.
    """
    employee_code = current_user.employee_code

    # Validate CSV file
    if not validate_csv_file(csv_file):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only CSV files are allowed and file must be provided.",
        )

    # lead_source_id is optional, but if provided, validate it exists
    if lead_source_id is not None:
        lead_source = db.query(LeadSource).filter_by(id=lead_source_id).first()
        if not lead_source:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Lead source with ID {lead_source_id} not found",
            )

    # Validate employee exists
    employee = db.query(UserDetails).filter_by(employee_code=employee_code).first()
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Employee with code {employee_code} not found",
        )

    try:
        # Read and parse CSV
        file_bytes = await csv_file.read()
        try:
            file_content = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            # Fallback for different encodings
            file_content = file_bytes.decode("utf-8", errors="ignore")

        rows = parse_csv_content(file_content)
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CSV file is empty",
            )

        # Skip header
        data_rows = rows[1:] if len(rows) > 1 else []
        total_rows = len(data_rows)

        # Counters and collectors
        successful_uploads = 0
        failed_uploads = 0
        duplicates_skipped = 0
        errors_list: List[Dict[str, Any]] = []
        uploaded_leads: List[int] = []
        validation_summary = {
            "format_errors": 0,
            "duplicate_errors": 0,
            "missing_mobile_errors": 0,
            "database_errors": 0,
        }

        # Process each row
        for idx, row in enumerate(data_rows, start=2):  # 2 = header at row 1
            # Initialize ALL per-row variables to avoid UnboundLocalError
            mobile = name = email = city = address = segment_text = occupation = investment = pan = None
            try:
                # Extract columns (only mobile is guaranteed to be configured)
                mobile = get_column_value(row, mobile_column)
                name = get_column_value(row, name_column)
                email = get_column_value(row, email_column)
                city = get_column_value(row, city_column)
                address = get_column_value(row, address_column)
                segment_text = get_column_value(row, segment_column)
                occupation = get_column_value(row, occupation_column)
                investment = get_column_value(row, investment_column)
                raw_pan = get_column_value(row, pan_column)
                pan = raw_pan.upper() if raw_pan else None

                # Mobile is required per row
                if not mobile:
                    errors_list.append(
                        {
                            "row": idx,
                            "errors": ["Missing mobile number"],
                            "data": {"mobile": mobile, "name": name, "email": email},
                        }
                    )
                    failed_uploads += 1
                    validation_summary["missing_mobile_errors"] += 1
                    continue

                # Prepare validation data
                row_data = {"mobile": mobile, "email": email, "pan": pan}

                # Validate
                validation_errors = validate_single_lead_data(row_data, db, idx)

                if validation_errors:
                    # Categorize errors
                    has_format_error = any("format" in err.lower() for err in validation_errors)
                    has_duplicate_error = any("duplicate" in err.lower() for err in validation_errors)

                    if has_format_error:
                        validation_summary["format_errors"] += 1
                        failed_uploads += 1
                    elif has_duplicate_error:
                        validation_summary["duplicate_errors"] += 1
                        duplicates_skipped += 1
                    else:
                        failed_uploads += 1

                    errors_list.append(
                        {
                            "row": idx,
                            "errors": validation_errors,
                            "data": {
                                "mobile": mobile,
                                "name": name,
                                "email": email,
                                "pan": pan,
                            },
                        }
                    )
                    continue

                # Segment array -> JSON
                segments_json = None
                segs = process_segment(segment_text)
                if segs:
                    segments_json = json.dumps(segs)

                # Build lead payload
                lead_data = {
                    "mobile": mobile,
                    "full_name": name,
                    "email": email,
                    "city": city,
                    "address": address,
                    "segment": segments_json,
                    "occupation": occupation,
                    "investment": investment,
                    "pan": pan,
                    "lead_source_id": lead_source_id,
                    "created_by": employee_code,
                    "created_by_name": employee.name,
                    "branch_id": branch_id,
                }
                # Drop None values
                lead_data = {k: v for k, v in lead_data.items() if v is not None}

                lead = Lead(**lead_data)
                db.add(lead)
                db.flush()  # get ID

                uploaded_leads.append(lead.id)
                successful_uploads += 1

            except Exception as db_error:
                db.rollback()
                validation_summary["database_errors"] += 1
                # Use the safely-initialized locals for logging
                errors_list.append(
                    {
                        "row": idx,
                        "errors": [f"Database error: {str(db_error)}"],
                        "data": {
                            "mobile": mobile,
                            "name": name,
                            "email": email,
                            "pan": pan,
                        },
                    }
                )
                failed_uploads += 1
                continue

        # Commit all successful inserts
        try:
            db.commit()
        except Exception as commit_error:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to commit bulk upload: {str(commit_error)}",
            )

        return BulkUploadResponse(
            total_rows=total_rows,
            successful_uploads=successful_uploads,
            failed_uploads=failed_uploads,
            duplicates_skipped=duplicates_skipped,
            errors=errors_list,
            uploaded_leads=uploaded_leads,
            validation_summary=validation_summary,
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Bulk upload failed: {str(e)}",
        )
