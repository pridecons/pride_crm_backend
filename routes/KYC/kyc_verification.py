# routes/KYC/kyc_verification.py - FIXED VERSION

from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Form, status
from sqlalchemy.orm import Session
from db.models import Lead
from db.connection import get_db
from routes.KYC.agreement_kyc_pdf import generate_kyc_pdf
import pytz
from routes.mail_service.send_mail import send_mail
from routes.auth.auth_dependency import get_current_user

router = APIRouter(tags=["Agreement KYC"])

@router.post("/kyc_user_details")
async def update_kyc_details(
    mobile: str = Form(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
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
        employee_code = current_user.employee_code
        try:
            signer_details = await generate_kyc_pdf(data, mobile,employee_code, db)
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
        
        # Extract signing URL and send email - FIXED
        try:
            # Fix the data extraction syntax error
            signing_url = signer_details.get("requests", [{}])[0].get("signing_url")
            
            if signing_url:
                # Create proper email content with HTML formatting
                email_content = f"""
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
    <h2 style="color: #2c3e50;">KYC Document Signing</h2>
    
    <p>Dear {kyc_user.full_name},</p>
    
    <p>Your KYC document is ready for digital signature. Please click the link below to review and sign your agreement:</p>
    
    <div style="text-align: center; margin: 30px 0;">
        <a href="{signing_url}" 
           style="background-color: #3498db; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; font-weight: bold;">
            Click Here to Sign KYC Document
        </a>
    </div>
    
    <p><strong>Important Instructions:</strong></p>
    <ul style="color: #555;">
        <li>Click the above link to access your KYC document</li>
        <li>Review all the details carefully</li>
        <li>Use your Aadhaar-linked mobile number for OTP verification</li>
        <li>Complete the digital signature process</li>
        <li>This link will expire in 7 days</li>
    </ul>
    
    <p><strong>Document Details:</strong></p>
    <ul style="color: #555;">
        <li>Mobile: {mobile}</li>
        <li>Email: {kyc_user.email}</li>
        <li>KYC ID: {kyc_user.kyc_id}</li>
        <li>Generated Date: {now_in_india.strftime('%d-%m-%Y %H:%M:%S')}</li>
    </ul>
    
    <div style="background-color: #f8f9fa; padding: 15px; border-left: 4px solid #17a2b8; margin: 20px 0;">
        <p style="margin: 0; color: #555;">
            <strong>Note:</strong> If you face any issues with the signing process, please contact our support team at compliance@pridecons.com or call +91-9981919424
        </p>
    </div>
    
    <p>If the button above doesn't work, copy and paste this link in your browser:</p>
    <p style="word-break: break-all; color: #007bff;">{signing_url}</p>
</div>
                """
                
                # Send email with proper HTML content
                await send_mail(
                    email=kyc_user.email,
                    name=kyc_user.full_name,
                    subject="KYC Document Ready for Digital Signature - Pride Trading Consultancy",
                    content=email_content,
                    is_html=True
                )
            else:
                print("Warning: No signing URL found in signer details")
                
        except Exception as email_error:
            print(f"Email sending failed: {email_error}")
            # Don't fail the whole process if email fails
            
        return {
            "message": "KYC process initiated successfully",
            "mobile": mobile,
            "user_name": kyc_user.full_name,
            "kyc_id": kyc_user.kyc_id,
            "email_sent": kyc_user.email,
            "signing_url": signing_url if 'signing_url' in locals() else None,
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
            "user_name": kyc_user.full_name,
            "email": kyc_user.email
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get KYC status: {str(e)}"
        )
    



    