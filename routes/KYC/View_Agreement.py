import logging
from datetime import datetime

import httpx
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session

from db.connection import get_db
from db.models import Lead
from config import PAN_API_ID, PAN_API_KEY

# Basic logging setup (you can configure handlers/format elsewhere in app)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(tags=["Agreement KYC"])


@router.post("/agreement/view/{lead_id}")
async def update_kyc_details(
    lead_id: int,
    prefer_complete: bool = Query(False, description="If true, fail when complete_signed_url is missing instead of falling back"),
    db: Session = Depends(get_db),
):
    """
    Fetch the signed agreement URL for a lead from Zoop.
    - Prefers `complete_signed_url`; if it's missing and `prefer_complete` is False, falls back to `latest_signed_url`.
    """
    # 0) load lead & ensure kyc_id exists
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead or not lead.kyc_id:
        logger.warning("Lead or KYC group missing for lead_id=%s", lead_id)
        raise HTTPException(404, detail="Lead or KYC group not found")

    # 1) fetch group info from Zoop
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://live.zoop.one/contract/esign/v5/fetch/group",
                params={"group_id": lead.kyc_id},
                headers={
                    "app-id": PAN_API_ID,
                    "api-key": PAN_API_KEY,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.error("Zoop API returned error status=%s body=%s", e.response.status_code, e.response.text)
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Zoop API error: {e.response.text}"
        )
    except httpx.TimeoutException:
        logger.error("Zoop API request timed out for group_id=%s", lead.kyc_id)
        raise HTTPException(504, detail="Zoop API request timed out")
    except httpx.RequestError as e:
        logger.error("Network error contacting Zoop API: %s", e)
        raise HTTPException(502, detail=f"Error connecting to Zoop API: {e}")
    except ValueError:
        logger.error("Invalid JSON from Zoop API for group_id=%s", lead.kyc_id)
        raise HTTPException(502, detail="Invalid JSON in Zoop API response")

    # 2) Extract URLs
    complete_url = (data.get("complete_signed_url") or "").strip()
    latest_url = (data.get("latest_signed_url") or "").strip()

    chosen_url = None
    used = None
    if complete_url:
        chosen_url = complete_url
        used = "complete_signed_url"
    elif latest_url and not prefer_complete:
        chosen_url = latest_url
        used = "latest_signed_url"
    else:
        logger.warning(
            "No signed URL available for lead_id=%s (prefer_complete=%s); complete='%s', latest='%s'",
            lead_id,
            prefer_complete,
            complete_url,
            latest_url,
        )
        msg = "Zoop response missing signed URL"
        if prefer_complete:
            msg = "complete_signed_url is missing and prefer_complete=true"
        raise HTTPException(502, detail=msg)

    # 3) Return result (raw_response is included for debugging; strip in prod if needed)
    return {
        "message": "Signed URL fetched successfully",
        "used": used,
        "signed_url": chosen_url,
        "transaction_status": data.get("transaction_status"),
        "expires_at": None,  # optional: could extract from requests if needed
        "raw_response": data,  # remove this in production if too verbose
    }
