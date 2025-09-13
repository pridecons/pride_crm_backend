# NO SmartApi SDK — direct REST + WSS
import os, time, json, socket, uuid, asyncio, logging
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query
from dotenv import load_dotenv
import pyotp
import httpx
from websocket import create_connection  # websocket-client

router = APIRouter(prefix="/stock", tags=["Stocks"])
log = logging.getLogger("stock.raw"); log.setLevel(logging.INFO)

# ------------------ Config ------------------
load_dotenv()
API_KEY     = os.getenv("ANGELONE_API_KEY") or ""
CLIENT_CODE = os.getenv("ANGELONE_CLIENT_CODE") or ""
MPIN        = os.getenv("ANGELONE_MPIN") or os.getenv("ANGELONE_PASSWORD") or ""
TOTP_SECRET = os.getenv("ANGELONE_TOTP_SECRET") or ""

if not all([API_KEY, CLIENT_CODE, MPIN, TOTP_SECRET]):
    raise RuntimeError("Set ANGELONE_API_KEY, ANGELONE_CLIENT_CODE, ANGELONE_MPIN/PASSWORD, ANGELONE_TOTP_SECRET")

ROOT = "https://apiconnect.angelbroking.com"  # a.k.a. apiconnect.angelone.in
LOGIN_EP = "/rest/auth/angelbroking/user/v1/loginByPassword"
QUOTE_EP = "/rest/secure/angelbroking/market/v1/quote"
LTP_EP   = "/rest/secure/angelbroking/order/v1/getLtpData"

WSS_URL  = "wss://smartapisocket.angelone.in/smart-stream"  # WebSocket 2.0
# Docs/forum confirm WSS + headers. :contentReference[oaicite:3]{index=3}

# Exchange type codes for WS subscribe payloads
EX_TYPE = {"NSE": 1, "BSE": 3}

# ---- Add/extend here ----
INDEX_TOKEN_MAP: Dict[str, Dict[str, str]] = {
    "NIFTY":        {"exchange": "NSE", "symboltoken": "99926000", "tradingsymbol": "Nifty 50"},
    "BANKNIFTY":    {"exchange": "NSE", "symboltoken": "99926009", "tradingsymbol": "Nifty Bank"},
    "FINNIFTY":     {"exchange": "NSE", "symboltoken": "99926037", "tradingsymbol": "Nifty Fin Service"},
    "MIDCAP NIFTY": {"exchange": "NSE", "symboltoken": "99926074", "tradingsymbol": "NIFTY MID SELECT"},
    "SENSEX":       {"exchange": "BSE", "symboltoken": "99919000", "tradingsymbol": "SENSEX"},
}

# ------------------ Helpers ------------------
def _totp_now() -> str:
    return pyotp.TOTP(TOTP_SECRET).now()

def _angel_headers(jwt: Optional[str] = None) -> Dict[str, str]:
    # SDK se headers ka contract mirror kiya hai. :contentReference[oaicite:4]{index=4}
    host = socket.gethostname()
    local_ip = socket.gethostbyname(host) if host else "127.0.0.1"
    pub_ip = "106.193.147.98"  # SDK bhi yahi fallback use karta hai
    mac = ":".join([f"{(uuid.getnode() >> ele) & 0xff:02x}" for ele in range(0,8*6,8)][::-1])
    h = {
        "Content-type": "application/json",
        "Accept": "application/json",
        "X-ClientLocalIP": local_ip,
        "X-ClientPublicIP": pub_ip,
        "X-MACAddress": mac,
        "X-PrivateKey": API_KEY,
        "X-UserType": "USER",
        "X-SourceID": "WEB",
    }
    if jwt:
        h["Authorization"] = f"Bearer {jwt}"
    return h

async def _login(http: httpx.AsyncClient):
    # POST loginByPassword → { jwtToken, refreshToken, feedToken }  :contentReference[oaicite:5]{index=5}
    payload = {"clientcode": CLIENT_CODE, "password": MPIN, "totp": _totp_now()}
    r = await http.post(f"{ROOT}{LOGIN_EP}", headers=_angel_headers(), json=payload, timeout=15)
    data = r.json()
    if not data.get("status"):
        raise HTTPException(401, f"Login failed: {data.get('message')}")
    d = data["data"]
    return d["jwtToken"], d["refreshToken"], d.get("feedToken")

def _group_exchange_tokens(names: List[str]):
    groups: Dict[str, List[str]] = {}
    for n in names:
        cfg = INDEX_TOKEN_MAP[n]
        groups.setdefault(cfg["exchange"], []).append(cfg["symboltoken"])
    return groups

# ------------------ REST: Quotes ------------------
@router.get("/quotes")
async def quotes(symbols: str = Query(..., description="Comma-separated e.g. NIFTY,BANKNIFTY,SENSEX")):
    """
    Returns:
    { "NIFTY": {"ltp": 25114.0, "close": 25070.5}, ... }
    """
    names = [s.strip() for s in symbols.split(",") if s.strip()]
    miss = [n for n in names if n not in INDEX_TOKEN_MAP]
    if miss:
        raise HTTPException(400, f"Unknown: {', '.join(miss)} — add in INDEX_TOKEN_MAP")

    def _norm_price(v):
        if isinstance(v, (int, float)):
            return float(v / 100.0) if v > 100000 else float(v)
        return None

    async with httpx.AsyncClient() as http:
        jwt, _rt, _feed = await _login(http)

        # Build request body: {"mode":"FULL","exchangeTokens":{"NSE":[...],"BSE":[...]}}
        ex_tokens: Dict[str, list] = {}
        for n in names:
            cfg = INDEX_TOKEN_MAP[n]
            ex_tokens.setdefault(cfg["exchange"], []).append(cfg["symboltoken"])

        body = {"mode": "FULL", "exchangeTokens": ex_tokens}
        r = await http.post(f"{ROOT}{QUOTE_EP}", headers=_angel_headers(jwt), json=body, timeout=15)

        try:
            resp = r.json()
        except Exception:
            raise HTTPException(502, "Quote API returned non-JSON")

        if not resp.get("status", False):
            # Angel sends {status:false, message:"..."} on errors
            raise HTTPException(502, f"Quote API error: {resp.get('message') or 'unknown'}")

        raw = resp.get("data")
        # ---- normalize `raw` to a list of dict items ----
        items: List[dict] = []

        if isinstance(raw, list):
            # Sometimes it's already a list, but can contain strings like "NA"
            items = [x for x in raw if isinstance(x, dict)]
            # Log once if we dropped anything unexpected
            if any(not isinstance(x, dict) for x in raw):
                log.warning("Quote data contained non-dict items; ignoring those.")
        elif isinstance(raw, dict):
            # Common pattern: a dict containing one or more lists (e.g., "fetched", "quotes", or exchange keys)
            for v in raw.values():
                if isinstance(v, list):
                    items.extend([x for x in v if isinstance(x, dict)])
        else:
            # Unexpected shape (string / null, etc.)
            log.warning("Unexpected quote data shape: %r", type(raw))
            items = []

        # Prepare output with defaults
        out: Dict[str, Dict[str, Optional[float]]] = {n: {"ltp": None, "close": None} for n in names}
        tok_to_name = {INDEX_TOKEN_MAP[n]["symboltoken"]: n for n in names}

        # Extract ltp & close robustly
        for item in items:
            print("item : ",item)
            if not isinstance(item, dict):
                continue
            token = str(item.get("symboltoken") or item.get("symbolToken") or "")
            name = tok_to_name.get(token)
            if not name:
                continue

            out[name] = item

        return out


# ------------------ WS: Live stream (proxy) ------------------
@router.websocket("/ws/stream")
async def stream(ws: WebSocket, symbols: str = Query(..., description="Comma-separated")):
    """
    Sends messages like: {"symbol":"NIFTY","ltp":25114.0}
    """
    await ws.accept()

    names = [s.strip() for s in symbols.split(",") if s.strip()]
    miss = [n for n in names if n not in INDEX_TOKEN_MAP]
    if miss:
        await ws.send_json({"event": "error", "message": f"Unknown: {', '.join(miss)}"})
        await ws.close(); return

    # login first to get jwt & feed_token
    try:
        async with httpx.AsyncClient() as http:
            jwt, _rt, feed = await _login(http)
    except Exception as e:
        await ws.send_json({"event":"error","message":f"login failed: {e}"}); await ws.close(); return

    # Build WS headers per docs/forum example. :contentReference[oaicite:7]{index=7}
    headers = {
        "Authorization": f"Bearer {jwt}",
        "x-api-key": API_KEY,
        "x-client-code": CLIENT_CODE,
        "x-feed-token": feed or "",
    }

    # Prepare subscribe payload (mode=3 => LTP)
    groups: Dict[int, List[str]] = {}
    for n in names:
        cfg = INDEX_TOKEN_MAP[n]
        et = EX_TYPE[cfg["exchange"]]
        groups.setdefault(et, []).append(cfg["symboltoken"])
    token_list = [{"exchangeType": et, "tokens": toks} for et, toks in groups.items()]
    subscribe_msg = json.dumps({"correlationID": "sub-1", "action": "subscribe", "params": {"mode": 3, "tokenList": token_list}})

    # Map token→name for fast lookup
    tok2name = {INDEX_TOKEN_MAP[n]["symboltoken"]: n for n in names}

    # Run WS client in a thread (websocket-client is blocking)
    loop = asyncio.get_event_loop()

    def _ws_worker():
        try:
            w = create_connection(WSS_URL, header=[f"{k}: {v}" for k,v in headers.items()])
            # Subscribe
            w.send(subscribe_msg)
            # Some builds also need setmode; harmless to send:
            setmode_msg = json.dumps({"action": "setmode", "params": [{"mode":"LTP", **blk} for blk in token_list]})
            try: w.send(setmode_msg)
            except Exception: pass

            # Relay loop
            while True:
                msg = w.recv()
                try:
                    obj = json.loads(msg) if isinstance(msg, str) else msg
                except Exception:
                    continue

                # Normalize possible shapes → list of ticks
                items = []
                if isinstance(obj, dict) and "data" in obj:
                    d = obj["data"]; items = d if isinstance(d, list) else [d]
                elif isinstance(obj, list): items = obj
                elif isinstance(obj, dict): items = [obj]

                # Forward simplified ticks
                for it in items:
                    token = str(it.get("symbolToken") or it.get("symboltoken") or it.get("token") or "")
                    ltp = it.get("ltp") or it.get("lastTradedPrice") or it.get("lp")
                    if isinstance(ltp, (int, float)) and ltp > 100000:
                        ltp = ltp / 100.0
                    name = tok2name.get(token)
                    if name and isinstance(ltp, (int, float)):
                        asyncio.run_coroutine_threadsafe(ws.send_json({"symbol": name, "ltp": float(ltp)}), loop)
        except Exception as e:
            asyncio.run_coroutine_threadsafe(ws.send_json({"event":"error","message":str(e)}), loop)
        finally:
            try:
                asyncio.run_coroutine_threadsafe(ws.close(), loop)
            except Exception:
                pass

    import threading
    t = threading.Thread(target=_ws_worker, daemon=True)
    t.start()

    # keep alive while worker runs
    try:
        while t.is_alive():
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass

