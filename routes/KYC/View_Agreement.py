import httpx
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from db.connection import get_db
from db.models import Lead
from routes.mail_service.send_mail import send_mail
from routes.auth.auth_dependency import get_current_user
from config import PAN_API_ID, PAN_API_KEY

router = APIRouter(tags=["Agreement KYC"])

@router.post("/agreement/view/{LeadId}")
async def update_kyc_details(
    LeadId: str,
    db: Session = Depends(get_db),
):
    lead = db.query(Lead).filter(Lead.id == LeadId).first()
    if not lead or not lead.kyc_id:
        raise HTTPException(404, "Lead or KYC group not found")

    # 1) fetch group info from Zoop
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://live.zoop.one/contract/esign/v5/fetch/group",
            params={"group_id": lead.kyc_id},
            headers={
                "app-id": PAN_API_ID,
                "api-key": PAN_API_KEY
            },
        )
    if resp.status_code != 200:
        raise HTTPException(502, "Failed to fetch eSign details")

    data = resp.json()
    complete_url = data.get("complete_signed_url")
    if not complete_url:
        raise HTTPException(500, "No signed URL returned")

    return {"message": "Signed URL", "complete_signed_url": complete_url}
