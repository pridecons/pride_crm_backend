from fastapi.responses import RedirectResponse
from fastapi import APIRouter, Request, HTTPException, Depends, Response
import json
from sqlalchemy.orm import Session
from db.connection import get_db
import httpx
from db.models import Lead
from routes.mail_service.kyc_agreement_mail import send_agreement
import base64

router = APIRouter(tags=["Agreement KYC Redirect"])
S3_BUCKET_NAME = "pride-user-data"

# Middleware-like functionality for each endpoint
def set_cors_allow_all(response: Response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"

@router.post("/redirect/{platform}/{mobile}")
async def redirect_route(response: Response,platform: str, mobile: str):
    set_cors_allow_all(response)
    if platform == "pridecons":
        redirect_url = f"https://pridecons.com/web/download_agreement/{mobile}"
    elif platform == "service":
        redirect_url = f"https://service.pridecons.sbs/kyc/agreement/{mobile}"
    else:
        redirect_url = f"https://pridebuzz.in/kyc/agreement/{mobile}"

    return RedirectResponse(
        url=redirect_url,
        status_code=302
    )

@router.post("/response_url/{mobile}")
async def response_url_endpoint(request: Request,response: Response,mobile: str,db: Session = Depends(get_db)):
    set_cors_allow_all(response)
    payload = await request.json()
    result = payload.get("result")
    document = result.get("document")
    signed_url = document.get("signed_url")
    try:
        async with httpx.AsyncClient() as client:
            pdf_response = await client.get(signed_url)
        pdf_response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"HTTP error fetching PDF: {exc}"
        )
    

    kyc_user = db.query(Lead).filter(Lead.mobile == mobile).first()

    await send_agreement(kyc_user.email,kyc_user.full_name,pdf_response.content)

    kyc_user.kyc = True

    db.commit()

    print("✅ Zoop callback received:")
    print(payload)
    return {"status": "received"}



