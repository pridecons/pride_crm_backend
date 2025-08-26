# routes/pan_verification.py

import json
import asyncio
from fastapi import APIRouter, HTTPException, Form, Depends, BackgroundTasks
from sqlalchemy.orm import Session
import httpx

from db.connection import get_db, SessionLocal
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
            status = exc.response.status_code
            detail = f"Error calling {url}: {exc.response.text}"
        except httpx.HTTPError as exc:
            status = 500
            detail = f"Error calling {url}: {str(exc)}"

        attempt += 1
        if attempt > max_retries:
            raise HTTPException(status_code=status, detail=detail)

        await asyncio.sleep(delay)
        delay = min(delay * backoff_factor, max_delay)


def save_pan_verification_to_db(pannumber: str, data: dict):
    """
    Sync function for BackgroundTasks: upsert PanVerification entry.
    """
    db = SessionLocal()
    try:
        entry = (
            db.query(PanVerification)
              .filter(PanVerification.PANnumber == pannumber)
              .first()
        )
        text = json.dumps(data)
        if entry:
            entry.response = text
            entry.APICount += 1
        else:
            entry = PanVerification(
                PANnumber=pannumber,
                response=text,
                APICount=1
            )
            db.add(entry)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def increment_pan_count(pannumber: str):
    """
    Sync function for BackgroundTasks: increment APICount on cached hits.
    """
    db = SessionLocal()
    try:
        entry = (
            db.query(PanVerification)
              .filter(PanVerification.PANnumber == pannumber)
              .first()
        )
        if entry:
            entry.APICount += 1
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


@router.post("/micro-pan-verification")
async def micro_pan_verification(
    background_tasks: BackgroundTasks,
    pannumber: str = Form(...),
    panType: str = Form(None),
    db: Session = Depends(get_db),
):
    """
    Micro PAN verification with:
      - cache lookup
      - API fetch + conditional DB save in background
    """
    # 1) Validate PAN format
    if not pannumber or len(pannumber.strip()) != 10:
        raise HTTPException(
            status_code=400,
            detail="Invalid PAN format. Must be 10 characters."
        )
    pannumber = pannumber.upper().strip()

    # 2) Determine endpoint URL
    if panType == "company":
        url = "https://live.zoop.one/api/v1/in/identity/pan/pro"
    else:
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
        "task_id": PAN_TASK_ID_1
    }

    # 3) Check cache
    entry = (
        db.query(PanVerification)
          .filter(PanVerification.PANnumber == pannumber)
          .first()
    )
    if entry and entry.response:
        try:
            cached = json.loads(entry.response)
        except json.JSONDecodeError:
            cached = None

        if cached:
            result = {"cached": True, "api_call_count": entry.APICount, **cached}
            # increment count asynchronously
            background_tasks.add_task(increment_pan_count, pannumber)
            return {
                "success": True,
                "pan_number": pannumber,
                "verification_type": "micro",
                "data": result
            }

    # 4) Fetch from external API
    try:
        api_data = await post_with_retries(url, headers, payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # 5) Conditional save: if not company AND no user_father_name, skip DB
    if panType != "company":
        result_obj = api_data.get("result") or {}
        if not result_obj.get("user_father_name"):
            return {
                "success": True,
                "pan_number": pannumber,
                "verification_type": "micro",
                "data": {"cached": False, **api_data}
            }

    # 6) Schedule background save
    background_tasks.add_task(save_pan_verification_to_db, pannumber, api_data)

    return {
        "success": True,
        "pan_number": pannumber,
        "verification_type": "micro",
        "data": {"cached": False, **api_data}
    }
