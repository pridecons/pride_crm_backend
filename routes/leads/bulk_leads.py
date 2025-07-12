# routes/bulk_leads.py - Complete Fixed Version

import os
import csv
import io
import re
import json
from typing import Optional, List, Dict, Any
from datetime import datetime, date

from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, DisconnectionError
from pydantic import BaseModel, validator

from db.connection import get_db
from db.models import Lead, LeadSource, LeadResponse, BranchDetails, UserDetails

router = APIRouter(
    prefix="/bulk-leads",
    tags=["bulk-lead-upload"],
)


# Pydantic Schemas
class BulkUploadRequest(BaseModel):
    lead_source_id: int
    mobile_column: int
    name_column: int
    email_column: int
    city_column: int
    address_column: int
    segment_column: int
    occupation_column: int
    investment_column: int


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
    if not file.filename.lower().endswith('.csv'):
        return False
    return True


def parse_csv_content(file_content: str) -> List[List[str]]:
    """Parse CSV content and return rows"""
    csv_reader = csv.reader(io.StringIO(file_content))
    rows = list(csv_reader)
    return rows


def get_column_value(row: List[str], column_index: int) -> Optional[str]:
    """Safely get value from row at given column index"""
    if column_index < 0 or column_index >= len(row):
        return None
    
    value = row[column_index].strip() if row[column_index] else None
    return value if value else None


def validate_email(email: str) -> bool:
    """Basic email validation"""
    if not email:
        return True  # Email is optional
    
    email = email.strip()
    # Simple email validation
    if '@' in email and '.' in email:
        parts = email.split('@')
        if len(parts) == 2 and '.' in parts[1]:
            return True
    return False


def validate_mobile(mobile: str) -> bool:
    """Basic mobile validation"""
    if not mobile:
        return False
    
    mobile = mobile.strip()
    # Remove any non-digit characters
    digits = ''.join(filter(str.isdigit, mobile))
    
    # Check for 10 digit Indian mobile numbers
    if len(digits) == 10 and digits[0] in ['6', '7', '8', '9']:
        return True
    
    return False


def process_segment(segment_text: str) -> List[str]:
    """Process segment column - handle comma-separated values"""
    if not segment_text:
        return []
    
    # Split by comma and clean up
    segments = [s.strip() for s in segment_text.split(',')]
    return [s for s in segments if s]


def process_bulk_lead_data(row, mobile_column, name_column, email_column, 
                          city_column, address_column, segment_column, 
                          occupation_column, investment_column, 
                          lead_source_id, employee, default_response_id):
    """Process a single row of bulk lead data"""
    
    # Extract data from row
    mobile = get_column_value(row, mobile_column)
    name = get_column_value(row, name_column)
    email = get_column_value(row, email_column)
    city = get_column_value(row, city_column)
    address = get_column_value(row, address_column)
    segment_text = get_column_value(row, segment_column)
    occupation = get_column_value(row, occupation_column)
    investment = get_column_value(row, investment_column)
    
    # Process segment properly - store as JSON array
    segments = None
    if segment_text:
        segments_list = process_segment(segment_text)
        if segments_list:
            segments = json.dumps(segments_list)  # Store as JSON string
    
    # Create lead data dictionary
    lead_data = {
        "full_name": name,
        "mobile": mobile,
        "email": email,
        "city": city,
        "address": address,
        "occupation": occupation,
        "investment": investment,
        "segment": segments,  # This will be JSON string or None
        "lead_source_id": lead_source_id,
        "lead_response_id": default_response_id,
        "created_by": employee.role.value if hasattr(employee.role, 'value') else str(employee.role),
        "created_by_name": employee.employee_code,
        "branch_id": employee.branch_id,
    }
    
    # Remove None values
    lead_data = {k: v for k, v in lead_data.items() if v is not None}
    
    return lead_data


# Main Upload Endpoint
@router.post("/upload", response_model=BulkUploadResponse)
async def upload_bulk_leads(
    lead_source_id: int = Form(...),
    employee_code: str = Form(...),
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
    """Upload bulk leads from CSV file with proper JSON handling"""
    
    try:
        # Validate CSV file
        if not validate_csv_file(csv_file):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Please upload a valid CSV file"
            )
        
        # Validate lead source
        lead_source = db.query(LeadSource).filter_by(id=lead_source_id).first()
        if not lead_source:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Lead source with ID {lead_source_id} not found"
            )
        
        # Validate employee who is uploading
        employee = db.query(UserDetails).filter_by(employee_code=employee_code).first()
        if not employee:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Employee with code {employee_code} not found"
            )
        
        # Read CSV content
        content = await csv_file.read()
        file_content = content.decode('utf-8')
        
        # Parse CSV
        try:
            rows = parse_csv_content(file_content)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Error parsing CSV file: {str(e)}"
            )
        
        if len(rows) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CSV file is empty"
            )
        
        # Remove header row if exists
        data_rows = rows[1:] if len(rows) > 1 else rows
        
        # Process leads
        successful_uploads = 0
        failed_uploads = 0
        duplicates_skipped = 0
        errors = []
        uploaded_leads = []
        
        # Get default lead response
        default_response = db.query(LeadResponse).first()
        default_response_id = default_response.id if default_response else None
        
        for row_index, row in enumerate(data_rows, start=2):
            try:
                # Extract data from row
                mobile = get_column_value(row, mobile_column)
                name = get_column_value(row, name_column)
                email = get_column_value(row, email_column)
                city = get_column_value(row, city_column)
                address = get_column_value(row, address_column)
                segment_text = get_column_value(row, segment_column)
                occupation = get_column_value(row, occupation_column)
                investment = get_column_value(row, investment_column)
                
                # Basic validation - only check for required fields
                validation_errors = []
                
                # Only check if name exists (since it's the most important field)
                if not name:
                    validation_errors.append("Missing name")
                
                # Skip mobile and email validation - allow any format
                
                if validation_errors:
                    errors.append({
                        "row": row_index,
                        "data": row,
                        "errors": validation_errors
                    })
                    failed_uploads += 1
                    continue
                
                # Check for duplicates only if mobile or email exists
                duplicate_conditions = []
                if mobile:
                    duplicate_conditions.append(Lead.mobile == mobile)
                if email:
                    duplicate_conditions.append(Lead.email == email)
                
                if duplicate_conditions:
                    from sqlalchemy import or_
                    existing_lead = db.query(Lead).filter(or_(*duplicate_conditions)).first()
                    if existing_lead:
                        errors.append({
                            "row": row_index,
                            "data": row,
                            "errors": ["Duplicate lead - mobile or email already exists"],
                            "existing_lead_id": existing_lead.id
                        })
                        duplicates_skipped += 1
                        continue
                
                # Process segment properly for database storage
                segments = None
                if segment_text:
                    segments_list = process_segment(segment_text)
                    if segments_list:
                        # Store as JSON string in database
                        segments = json.dumps(segments_list)
                
                # Create lead with proper data types
                lead_data = {
                    "full_name": name,
                    "mobile": mobile,
                    "email": email,
                    "city": city,
                    "address": address,
                    "occupation": occupation,
                    "investment": investment,
                    "segment": segments,  # JSON string or None
                    "lead_source_id": lead_source_id,
                    "lead_response_id": default_response_id,
                    "created_by": employee.role.value if hasattr(employee.role, 'value') else str(employee.role),
                    "created_by_name": employee.employee_code,
                    "branch_id": employee.branch_id,
                }
                
                # Remove None values
                lead_data = {k: v for k, v in lead_data.items() if v is not None}
                
                lead = Lead(**lead_data)
                db.add(lead)
                db.flush()  # Get the ID
                
                uploaded_leads.append(lead.id)
                successful_uploads += 1
                
            except Exception as e:
                errors.append({
                    "row": row_index,
                    "data": row,
                    "errors": [f"Database error: {str(e)}"]
                })
                failed_uploads += 1
                continue
        
        # Commit all successful leads
        if successful_uploads > 0:
            db.commit()
        
        return BulkUploadResponse(
            total_rows=len(data_rows),
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
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing bulk upload: {str(e)}"
        )


@router.post("/preview", response_model=Dict[str, Any])
async def preview_csv_data(
    csv_file: UploadFile = File(...),
    preview_rows: int = 5,
):
    """Preview CSV data before upload"""
    
    try:
        # Validate CSV file
        if not validate_csv_file(csv_file):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Please upload a valid CSV file"
            )
        
        # Read CSV content
        content = await csv_file.read()
        file_content = content.decode('utf-8')
        
        # Parse CSV
        try:
            rows = parse_csv_content(file_content)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Error parsing CSV file: {str(e)}"
            )
        
        if len(rows) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CSV file is empty"
            )
        
        # Get headers
        headers = rows[0] if rows else []
        
        # Get column mapping suggestions
        column_mappings = {}
        for index, header in enumerate(headers):
            header_lower = header.lower().strip()
            
            if any(keyword in header_lower for keyword in ['mobile', 'phone', 'contact']):
                column_mappings['mobile_column'] = index
            elif any(keyword in header_lower for keyword in ['name', 'full_name', 'customer']):
                column_mappings['name_column'] = index
            elif any(keyword in header_lower for keyword in ['email', 'mail']):
                column_mappings['email_column'] = index
            elif any(keyword in header_lower for keyword in ['city', 'location']):
                column_mappings['city_column'] = index
            elif any(keyword in header_lower for keyword in ['address', 'addr']):
                column_mappings['address_column'] = index
            elif any(keyword in header_lower for keyword in ['segment', 'category']):
                column_mappings['segment_column'] = index
            elif any(keyword in header_lower for keyword in ['occupation', 'job', 'profession']):
                column_mappings['occupation_column'] = index
            elif any(keyword in header_lower for keyword in ['investment', 'invest', 'amount']):
                column_mappings['investment_column'] = index
        
        # Get preview data
        preview_data = rows[1:min(len(rows), preview_rows + 1)]
        
        return {
            "filename": csv_file.filename,
            "total_rows": len(rows) - 1,
            "headers": headers,
            "column_count": len(headers),
            "suggested_mappings": column_mappings,
            "preview_data": preview_data,
            "sample_data": {
                "header_row": headers,
                "data_rows": preview_data
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error previewing CSV: {str(e)}"
        )


@router.post("/debug-upload")
async def debug_bulk_upload(
    lead_source_id: int = Form(...),
    employee_code: str = Form(...),
    mobile_column: int = Form(...),
    name_column: int = Form(...),
    email_column: int = Form(...),
    city_column: int = Form(...),
    address_column: int = Form(...),
    segment_column: int = Form(...),
    occupation_column: int = Form(...),
    investment_column: int = Form(...),
    csv_file: UploadFile = File(...),
):
    """Debug endpoint to see exactly what data is being extracted"""
    
    try:
        # Read CSV content
        content = await csv_file.read()
        file_content = content.decode('utf-8')
        
        # Parse CSV
        rows = parse_csv_content(file_content)
        
        if len(rows) == 0:
            return {"error": "CSV file is empty"}
        
        # Show header and first few data rows with mapping
        headers = rows[0] if rows else []
        data_rows = rows[1:4] if len(rows) > 1 else []
        
        debug_info = {
            "file_info": {
                "filename": csv_file.filename,
                "total_rows": len(rows),
                "headers": headers,
                "column_count": len(headers)
            },
            "column_mapping": {
                "name_column": name_column,
                "mobile_column": mobile_column, 
                "email_column": email_column,
                "city_column": city_column,
                "address_column": address_column,
                "segment_column": segment_column,
                "occupation_column": occupation_column,
                "investment_column": investment_column
            },
            "extracted_data": []
        }
        
        # Extract and validate data for each row
        for row_index, row in enumerate(data_rows):
            extracted = {
                "row_number": row_index + 2,
                "raw_data": row,
                "extracted_values": {
                    "name": get_column_value(row, name_column),
                    "mobile": get_column_value(row, mobile_column),
                    "email": get_column_value(row, email_column),
                    "city": get_column_value(row, city_column),
                    "address": get_column_value(row, address_column),
                    "segment": get_column_value(row, segment_column),
                    "occupation": get_column_value(row, occupation_column),
                    "investment": get_column_value(row, investment_column)
                },
                "validation_results": {}
            }
            
            # Validate each field
            mobile = get_column_value(row, mobile_column)
            email = get_column_value(row, email_column)
            name = get_column_value(row, name_column)
            segment_text = get_column_value(row, segment_column)
            
            extracted["validation_results"] = {
                "mobile_valid": True,  # Accept any mobile format
                "email_valid": True,   # Accept any email format
                "name_valid": bool(name),
                "mobile_digits": ''.join(filter(str.isdigit, mobile)) if mobile else "",
                "mobile_length": len(''.join(filter(str.isdigit, mobile))) if mobile else 0,
                "segment_processed": process_segment(segment_text) if segment_text else []
            }
            
            debug_info["extracted_data"].append(extracted)
        
        return debug_info
        
    except Exception as e:
        return {"error": f"Debug failed: {str(e)}"}


@router.get("/template")
async def download_csv_template():
    """Download CSV template for bulk upload"""
    
    template_data = [
        ["Name", "Mobile", "Email", "City", "Address", "Segment", "Occupation", "Investment"],
        ["John Doe", "9876543210", "john@example.com", "Mumbai", "123 Main St", "Technology,Finance", "Software Engineer", "5-10 lakhs"],
        ["Jane Smith", "9876543211", "jane@example.com", "Delhi", "456 Park Ave", "Healthcare", "Doctor", "10-20 lakhs"],
        ["Bob Johnson", "9876543212", "bob@example.com", "Bangalore", "789 Tech St", "Technology", "Data Scientist", "15-25 lakhs"]
    ]
    
    # Create CSV content
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(template_data)
    csv_content = output.getvalue()
    
    from fastapi.responses import Response
    
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=bulk_leads_template.csv"
        }
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
        
        # Filter by employee if provided
        if employee_code:
            query = query.filter(Lead.created_by_name == employee_code)
        
        # Filter by date range if provided
        if date_from:
            query = query.filter(Lead.created_at >= date_from)
        
        if date_to:
            from datetime import datetime, time
            date_to_end = datetime.combine(date_to, time.max)
            query = query.filter(Lead.created_at <= date_to_end)
        
        total_leads = query.count()
        
        # Get leads by source
        source_stats = db.query(
            LeadSource.name,
            db.func.count(Lead.id).label('count')
        ).join(Lead).group_by(LeadSource.name).all()
        
        # Get leads by employee
        employee_stats = db.query(
            Lead.created_by_name.label('employee_code'),
            Lead.created_by.label('role'),
            db.func.count(Lead.id).label('count')
        ).filter(Lead.created_by_name.isnot(None)).group_by(
            Lead.created_by_name, Lead.created_by
        ).all()
        
        # Get recent uploads
        recent_uploads = query.order_by(Lead.created_at.desc()).limit(10).all()
        
        return {
            "total_leads": total_leads,
            "source_wise_stats": [
                {"source": stat[0], "count": stat[1]}
                for stat in source_stats
            ],
            "employee_wise_stats": [
                {
                    "employee_code": stat[0],
                    "role": stat[1],
                    "count": stat[2]
                }
                for stat in employee_stats
            ],
            "recent_uploads": [
                {
                    "id": lead.id,
                    "name": lead.full_name,
                    "mobile": lead.mobile,
                    "email": lead.email,
                    "created_by_role": lead.created_by,
                    "created_by_employee_code": lead.created_by_name,
                    "created_at": lead.created_at
                }
                for lead in recent_uploads
            ]
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching upload statistics: {str(e)}"
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
        # Read and parse CSV
        content = await csv_file.read()
        file_content = content.decode('utf-8')
        rows = parse_csv_content(file_content)
        
        if len(rows) <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CSV file must have at least one data row"
            )
        
        data_rows = rows[1:]
        validation_results = []
        
        for row_index, row in enumerate(data_rows, start=2):
            mobile = get_column_value(row, mobile_column)
            name = get_column_value(row, name_column)
            email = get_column_value(row, email_column)
            
            errors = []
            warnings = []
            
            # Check required fields
            if not name:
                errors.append("Name is required")
            
            # Check duplicates in database
            if mobile or email:
                conditions = []
                if mobile:
                    conditions.append(Lead.mobile == mobile)
                if email:
                    conditions.append(Lead.email == email)
                
                if conditions:
                    from sqlalchemy import or_
                    existing = db.query(Lead).filter(or_(*conditions)).first()
                    if existing:
                        warnings.append(f"Duplicate found - Lead ID: {existing.id}")
            
            # Email format check
            if email and not validate_email(email):
                warnings.append("Invalid email format")
            
            # Mobile format check
            if mobile and not validate_mobile(mobile):
                warnings.append("Invalid mobile format")
            
            validation_results.append({
                "row": row_index,
                "data": {
                    "name": name,
                    "mobile": mobile,
                    "email": email
                },
                "errors": errors,
                "warnings": warnings,
                "valid": len(errors) == 0
            })
        
        # Summary
        total_rows = len(validation_results)
        valid_rows = sum(1 for r in validation_results if r["valid"])
        invalid_rows = total_rows - valid_rows
        rows_with_warnings = sum(1 for r in validation_results if r["warnings"])
        
        return {
            "filename": csv_file.filename,
            "summary": {
                "total_rows": total_rows,
                "valid_rows": valid_rows,
                "invalid_rows": invalid_rows,
                "rows_with_warnings": rows_with_warnings
            },
            "validation_results": validation_results
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error validating data: {str(e)}"
        )


@router.post("/upload-with-validation", response_model=BulkUploadResponse)
async def upload_bulk_leads_with_validation(
    lead_source_id: int = Form(...),
    employee_code: str = Form(...),
    mobile_column: int = Form(...),
    name_column: int = Form(...),
    email_column: int = Form(...),
    city_column: int = Form(...),
    address_column: int = Form(...),
    segment_column: int = Form(...),
    occupation_column: int = Form(...),
    investment_column: int = Form(...),
    skip_duplicates: bool = Form(True),
    skip_invalid_emails: bool = Form(True),
    skip_invalid_mobiles: bool = Form(True),
    csv_file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload bulk leads with advanced validation options"""
    
    try:
        # Validate inputs
        if not validate_csv_file(csv_file):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Please upload a valid CSV file"
            )
        
        lead_source = db.query(LeadSource).filter_by(id=lead_source_id).first()
        if not lead_source:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Lead source with ID {lead_source_id} not found"
            )
        
        employee = db.query(UserDetails).filter_by(employee_code=employee_code).first()
        if not employee:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Employee with code {employee_code} not found"
            )
        
        # Read and parse CSV
        content = await csv_file.read()
        file_content = content.decode('utf-8')
        rows = parse_csv_content(file_content)
        
        if len(rows) <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CSV file must have at least one data row"
            )
        
        data_rows = rows[1:]
        
        # Process with validation
        successful_uploads = 0
        failed_uploads = 0
        duplicates_skipped = 0
        errors = []
        uploaded_leads = []
        
        default_response = db.query(LeadResponse).first()
        default_response_id = default_response.id if default_response else None
        
        for row_index, row in enumerate(data_rows, start=2):
            try:
                # Extract data
                mobile = get_column_value(row, mobile_column)
                name = get_column_value(row, name_column)
                email = get_column_value(row, email_column)
                city = get_column_value(row, city_column)
                address = get_column_value(row, address_column)
                segment_text = get_column_value(row, segment_column)
                occupation = get_column_value(row, occupation_column)
                investment = get_column_value(row, investment_column)
                
                # Validation
                validation_errors = []
                
                if not name:
                    validation_errors.append("Name is required")
                
                if email and skip_invalid_emails and not validate_email(email):
                    validation_errors.append("Invalid email format")
                
                if mobile and skip_invalid_mobiles and not validate_mobile(mobile):
                    validation_errors.append("Invalid mobile format")
                
                # Check duplicates
                if (mobile or email) and skip_duplicates:
                    conditions = []
                    if mobile:
                        conditions.append(Lead.mobile == mobile)
                    if email:
                        conditions.append(Lead.email == email)
                    
                    if conditions:
                        from sqlalchemy import or_
                        existing = db.query(Lead).filter(or_(*conditions)).first()
                        if existing:
                            duplicates_skipped += 1
                            errors.append({
                                "row": row_index,
                                "data": row,
                                "errors": ["Duplicate lead found"],
                                "existing_lead_id": existing.id
                            })
                            continue
                
                if validation_errors:
                    failed_uploads += 1
                    errors.append({
                        "row": row_index,
                        "data": row,
                        "errors": validation_errors
                    })
                    continue
                
                # Process segment
                segments = None
                if segment_text:
                    segments_list = process_segment(segment_text)
                    if segments_list:
                        segments = json.dumps(segments_list)
                
                # Create lead
                lead_data = {
                    "full_name": name,
                    "mobile": mobile,
                    "email": email,
                    "city": city,
                    "address": address,
                    "occupation": occupation,
                    "investment": investment,
                    "segment": segments,
                    "lead_source_id": lead_source_id,
                    "lead_response_id": default_response_id,
                    "created_by": employee.role.value if hasattr(employee.role, 'value') else str(employee.role),
                    "created_by_name": employee.employee_code,
                    "branch_id": employee.branch_id,
                }
                
                # Remove None values
                lead_data = {k: v for k, v in lead_data.items() if v is not None}
                
                lead = Lead(**lead_data)
                db.add(lead)
                db.flush()
                
                uploaded_leads.append(lead.id)
                successful_uploads += 1
                
            except Exception as e:
                failed_uploads += 1
                errors.append({
                    "row": row_index,
                    "data": row,
                    "errors": [f"Database error: {str(e)}"]
                })
                continue
        
        # Commit successful uploads
        if successful_uploads > 0:
            db.commit()
        
        return BulkUploadResponse(
            total_rows=len(data_rows),
            successful_uploads=successful_uploads,
            failed_uploads=failed_uploads,
            duplicates_skipped=duplicates_skipped,
            errors=errors,
            uploaded_leads=uploaded_leads
        )
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing upload: {str(e)}"
        )


@router.get("/recent-uploads")
def get_recent_uploads(
    limit: int = 20,
    employee_code: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get recent bulk uploads"""
    
    try:
        query = db.query(Lead).filter(Lead.created_by_name.isnot(None))
        
        if employee_code:
            query = query.filter(Lead.created_by_name == employee_code)
        
        recent_leads = query.order_by(Lead.created_at.desc()).limit(limit).all()
        
        return {
            "recent_uploads": [
                {
                    "id": lead.id,
                    "full_name": lead.full_name,
                    "mobile": lead.mobile,
                    "email": lead.email,
                    "city": lead.city,
                    "created_by": lead.created_by,
                    "created_by_name": lead.created_by_name,
                    "created_at": lead.created_at,
                    "lead_source_id": lead.lead_source_id,
                    "kyc": lead.kyc
                }
                for lead in recent_leads
            ]
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching recent uploads: {str(e)}"
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
        # Find leads without essential information that were uploaded today
        query = db.query(Lead).filter(
            Lead.created_by_name == employee_code,
            Lead.created_at >= date_from,
            Lead.full_name.is_(None)  # Leads without names are likely failed uploads
        )
        
        leads_to_cleanup = query.all()
        
        if dry_run:
            return {
                "dry_run": True,
                "leads_found": len(leads_to_cleanup),
                "leads": [
                    {
                        "id": lead.id,
                        "mobile": lead.mobile,
                        "email": lead.email,
                        "created_at": lead.created_at
                    }
                    for lead in leads_to_cleanup
                ]
            }
        else:
            # Actually delete the leads
            deleted_count = query.delete()
            db.commit()
            
            return {
                "dry_run": False,
                "deleted_count": deleted_count,
                "message": f"Successfully deleted {deleted_count} incomplete leads"
            }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error during cleanup: {str(e)}"
        )