from fastapi import HTTPException
import httpx
import asyncio

async def post_with_retries(
    url: str,
    headers: dict,
    payload: dict,
    *,
    max_retries: int | None = None,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    max_delay: float = 30.0,
) -> dict:
    """
    POST to `url` with httpx until success.

    Args:
      url: request URL
      headers: headers dict
      payload: JSON body
      max_retries: maximum number of attempts (None = infinite)
      initial_delay: seconds to wait before first retry
      backoff_factor: multiplier for delay on each failure
      max_delay: cap for delay

    Returns:
      Parsed JSON response on HTTP 2xx

    Raises:
      HTTPException once max_retries is exceeded.
    """
    attempt = 0
    delay = initial_delay

    while True:
        try:
            async with httpx.AsyncClient() as client:
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
        if max_retries is not None and attempt > max_retries:
            raise HTTPException(status_code=status, detail=detail)

        # wait, then retry
        await asyncio.sleep(delay)
        delay = min(delay * backoff_factor, max_delay)

