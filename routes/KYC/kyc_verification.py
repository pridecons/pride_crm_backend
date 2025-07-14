# routes/KYC/kyc_verification.py - FIXED VERSION

from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Form, status
from sqlalchemy.orm import Session
from db.models import Lead
from db.connection import get_db
from routes.KYC.agreement_kyc_pdf import generate_kyc_pdf
import pytz

router = APIRouter(tags=["Agreement KYC"])

@router.post("/kyc_user_details")
async def update_kyc_details(
    mobile: str = Form(...),
    db: Session = Depends(get_db)
):
    """Initialize KYC process for a user"""
    try:
        # Validate mobile number
        if not mobile or len(mobile) < 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Valid mobile number is required"
            )
        
        # Find user by mobile
        kyc_user = db.query(Lead).filter(Lead.mobile == mobile).first()
        if not kyc_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="User not found with this mobile number"
            )

        # Validate required fields
        missing_fields = []
        required_fields = {
            "full_name": kyc_user.full_name,
            "email": kyc_user.email,
            "city": kyc_user.city,
            "address": kyc_user.address,
            "dob": kyc_user.dob,
            "pan": kyc_user.pan
        }
        
        for field, value in required_fields.items():
            if not value:
                missing_fields.append(field)
        
        if missing_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing required fields: {', '.join(missing_fields)}"
            )

        # Get current time in India timezone
        india_timezone = pytz.timezone('Asia/Kolkata')
        now_in_india = datetime.now(india_timezone)
        
        # Prepare data for PDF generation
        data = {
            "full_name": kyc_user.full_name,
            "father_name": kyc_user.father_name or "N/A",
            "address": kyc_user.address,
            "date": now_in_india.strftime("%d-%m-%Y"),
            "email": kyc_user.email,
            "city": kyc_user.city,
            "mobile": mobile,
            "platform": "crm"
        }
        
        # Generate KYC PDF and get signer details
        try:
            signer_details = await generate_kyc_pdf(data, mobile, db)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to generate KYC document: {str(e)}"
            )
        
        # Update KYC ID in database
        if signer_details and "group_id" in signer_details:
            kyc_user.kyc_id = signer_details.get("group_id")
            db.commit()
            db.refresh(kyc_user)
        
        return {
            "message": "KYC process initiated successfully",
            "mobile": mobile,
            "user_name": kyc_user.full_name,
            "kyc_id": kyc_user.kyc_id,
            "signer_details": signer_details
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"KYC process failed: {str(e)}"
        )

@router.get("/kyc_status/{mobile}")
async def get_kyc_status(
    mobile: str,
    db: Session = Depends(get_db)
):
    """Get KYC status for a user"""
    try:
        kyc_user = db.query(Lead).filter(Lead.mobile == mobile).first()
        if not kyc_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        return {
            "mobile": mobile,
            "kyc_completed": kyc_user.kyc or False,
            "kyc_id": kyc_user.kyc_id,
            "user_name": kyc_user.full_name
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get KYC status: {str(e)}"
        )
    
    