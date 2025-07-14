from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Form
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

    kyc_user = db.query(Lead).filter(Lead.mobile == mobile).first()
    if not kyc_user:
        raise HTTPException(status_code=404, detail="KYC record not found")


    india_timezone = pytz.timezone('Asia/Kolkata')
    now_in_india = datetime.now(india_timezone)
    data = {
        "full_name": kyc_user.full_name,
        "father_name": kyc_user.father_name,
        "address": kyc_user.address,
        "date": now_in_india,      # automatically current date and time
        "email": kyc_user.email,         # email from the database
        "city": kyc_user.city,
        "mobile":mobile,
        "platform": "crm"
    }
    
    signer_details = await generate_kyc_pdf(data,mobile,db)

    kyc_user.kyc_id=signer_details.get("group_id")

    db.commit()
    db.refresh(kyc_user)
    return {
        "message": "KYC details updated successfully",
        "mobile": kyc_user.mobile,
        "signer_details": signer_details
    }

