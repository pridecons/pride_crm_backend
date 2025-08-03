# routes/pan_verification.py - FIXED VERSION

import json
from fastapi import APIRouter, HTTPException, Form, Depends
from sqlalchemy.orm import Session
import httpx
import asyncio

from db.connection import get_db
from db.models import PanVerification
from config import PAN_API_ID, PAN_API_KEY, PAN_TASK_ID_1

router = APIRouter(tags=["Pan Verification"])


async def post_with_retries(
    url: str,
    headers: dict,
    payload: dict,
    *,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    max_delay: float = 30.0,
) -> dict:
    """
    POST to `url` with httpx until success.
    """
    attempt = 0
    delay = initial_delay

    while True:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()

        except httpx.HTTPStatusError as exc:
            # server returned 4xx/5xx
            status = exc.response.status_code
            detail = f"Error calling {url}: {exc.response.text}"
        except httpx.HTTPError as exc:
            # network error, timeouts, etc.
            status = 500
            detail = f"Error calling {url}: {str(exc)}"
        
        # if we reach here, it failed
        attempt += 1
        if attempt > max_retries:
            raise HTTPException(status_code=status, detail=detail)

        # wait, then retry
        await asyncio.sleep(delay)
        delay = min(delay * backoff_factor, max_delay)


async def get_or_fetch_pan(
    pannumber: str,
    url: str,
    headers: dict,
    payload: dict,
    db: Session
) -> dict:
    """
    Get PAN data from cache or fetch from API - FIXED ASYNC VERSION
    """
    try:
        # 1) look up existing entry
        entry = db.query(PanVerification).filter(
            PanVerification.PANnumber == pannumber
        ).first()

        if entry and entry.response:
            # Return cached response
            try:
                cached_data = json.loads(entry.response)
                entry.APICount += 1
                db.commit()
                return {
                    "cached": True,
                    "api_call_count": entry.APICount,
                    **cached_data
                }
            except json.JSONDecodeError:
                # If cached data is corrupted, fetch fresh
                pass

        # 2) otherwise, call external API
        data = await post_with_retries(url, headers, payload)

        # 3) store JSON text and increment count
        response_text = json.dumps(data)
        if entry:
            entry.response = response_text
            entry.APICount += 1
        else:
            entry = PanVerification(
                PANnumber=pannumber,
                response=response_text,
                APICount=1
            )
            db.add(entry)

        db.commit()
        
        return {
            "cached": False,
            "api_call_count": entry.APICount,
            **data
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Error processing PAN verification: {str(e)}"
        )


# @router.post("/pro-pan-verification")
# async def pro_pan_verification(
#     pannumber: str = Form(...),
#     db: Session = Depends(get_db)
# ):
#     """
#     Professional PAN verification with caching
#     """
#     try:
#         # Validate PAN format
#         if not pannumber or len(pannumber) != 10:
#             raise HTTPException(
#                 status_code=400,
#                 detail="Invalid PAN format. PAN should be 10 characters long."
#             )
        
#         pannumber = pannumber.upper().strip()
        
#         url = "https://live.zoop.one/api/v1/in/identity/pan/pro"
#         headers = {
#             "app-id": PAN_API_ID,
#             "api-key": PAN_API_KEY,
#             "Content-Type": "application/json",
#         }
#         payload = {
#             "mode": "sync",
#             "data": {
#                 "customer_pan_number": pannumber,
#                 "consent": "Y",
#                 "consent_text": "I hereby declare my consent agreement for fetching my information via ZOOP API"
#             },
#             "task_id": PAN_TASK_ID_1
#         }

#         # Get data (from cache or API)
#         result = await get_or_fetch_pan(pannumber, url, headers, payload, db)
        
#         return {
#             "success": True,
#             "pan_number": pannumber,
#             "verification_type": "professional",
#             "data": result
#         }
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(
#             status_code=500,
#             detail=f"PAN verification failed: {str(e)}"
#         )


@router.post("/micro-pan-verification")
async def micro_pan_verification(
    pannumber: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    Micro PAN verification with caching
    """
    try:
        # Validate PAN format
        if not pannumber or len(pannumber) != 10:
            raise HTTPException(
                status_code=400,
                detail="Invalid PAN format. PAN should be 10 characters long."
            )
        
        pannumber = pannumber.upper().strip()
        
        url = "https://live.zoop.one/api/v1/in/identity/pan/micro"
        headers = {
            "app-id": PAN_API_ID,
            "api-key": PAN_API_KEY,
            "Content-Type": "application/json",
        }
        payload = {
            "mode": "sync",
            "data": {
                "customer_pan_number": pannumber,
                "pan_details": True,
                "consent": "Y",
                "consent_text": "I hereby declare my consent agreement for fetching my information via ZOOP API"
            },
            "task_id": "f26eb21e-4c35-4491-b2d5-41fa0e545a34"
        }

        # Get data (from cache or API)
        result = await get_or_fetch_pan(pannumber, url, headers, payload, db)
        
        return {
            "success": True,
            "pan_number": pannumber,
            "verification_type": "micro",
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"PAN verification failed: {str(e)}"
        )

