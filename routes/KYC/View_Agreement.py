import httpx
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from db.connection import get_db
from db.models import Lead
from config import PAN_API_ID, PAN_API_KEY

router = APIRouter(tags=["Agreement KYC"])

@router.post("/agreement/view/{lead_id}")
async def update_kyc_details(
    lead_id: int,
    db: Session = Depends(get_db),
):
    # 0) load lead & ensure kyc_id exists
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead or not lead.kyc_id:
        raise HTTPException(404, detail="Lead or KYC group not found")

    # 1) fetch group info from Zoop, with robust error handling
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://live.zoop.one/contract/esign/v5/fetch/group",
                params={"group_id": lead.kyc_id},
                headers={
                    "app-id": PAN_API_ID,
                    "api-key": PAN_API_KEY,
                },
            )
    except httpx.TimeoutException:
        # Zoop didn’t reply in time
        raise HTTPException(504, detail="Zoop API request timed out")
    except httpx.RequestError as e:
        # Network problem, DNS failure, etc.
        raise HTTPException(502, detail=f"Error connecting to Zoop API: {e}")

    # 2) propagate Zoop’s own error code & message
    if resp.status_code != 200:
        # you can choose to parse resp.json() here if Zoop returns structured errors
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"Zoop API error ({resp.status_code}): {resp.text}"
        )

    # 3) parse JSON safely
    try:
        data = resp.json()
    except ValueError:
        raise HTTPException(502, detail="Invalid JSON in Zoop API response")

    # 4) validate payload
    complete_url = data.get("complete_signed_url")
    if not complete_url:
        raise HTTPException(502, detail="Zoop response missing 'complete_signed_url'")

    # 5) success
    return {
        "message": "Signed URL fetched successfully",
        "complete_signed_url": complete_url
    }
