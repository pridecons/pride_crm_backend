# NO SmartApi SDK — direct REST + WSS
import os, time, json, socket, uuid, asyncio, logging
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
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

ROOT = "https://apiconnect.angelbroking.com"  # a.k.a. apiconnect.angelone.in
LOGIN_EP = "/rest/auth/angelbroking/user/v1/loginByPassword"
QUOTE_EP = "/rest/secure/angelbroking/market/v1/quote"

WSS_URL  = "wss://smartapisocket.angelone.in/smart-stream"  # WebSocket 2.0
EX_TYPE = {"NSE": 1, "BSE": 3}

# ---- Use/extend here ----
INDEX_TOKEN_MAP: Dict[str, Dict[str, str]] = {
    "NIFTY":        {"exchange": "NSE", "symboltoken": "99926000", "tradingsymbol": "Nifty 50"},
    "BANKNIFTY":    {"exchange": "NSE", "symboltoken": "99926009", "tradingsymbol": "Nifty Bank"},
    "FINNIFTY":     {"exchange": "NSE", "symboltoken": "99926037", "tradingsymbol": "Nifty Fin Service"},
    "MIDCAP NIFTY": {"exchange": "NSE", "symboltoken": "99926074", "tradingsymbol": "NIFTY MID SELECT"},
    "SENSEX":       {"exchange": "BSE", "symboltoken": "99919000", "tradingsymbol": "SENSEX"},
}

def _config_missing() -> List[str]:
    miss = []
    if not API_KEY: miss.append("ANGELONE_API_KEY")
    if not CLIENT_CODE: miss.append("ANGELONE_CLIENT_CODE")
    if not MPIN: miss.append("ANGELONE_MPIN/ANGELONE_PASSWORD")
    if not TOTP_SECRET: miss.append("ANGELONE_TOTP_SECRET")
    return miss

# ------------------ Helpers ------------------
def _totp_now() -> str:
    return pyotp.TOTP(TOTP_SECRET).now()

def _angel_headers(jwt: Optional[str] = None) -> Dict[str, str]:
    host = socket.gethostname()
    local_ip = socket.gethostbyname(host) if host else "127.0.0.1"
    pub_ip = "106.193.147.98"  # SDK fallback
    mac = ":".join([f"{(uuid.getnode() >> ele) & 0xff:02x}" for ele in range(0, 8*6, 8)][::-1])
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
    if miss := _config_missing():
        raise HTTPException(503, f"AngelOne not configured. Missing: {', '.join(miss)}")
    payload = {"clientcode": CLIENT_CODE, "password": MPIN, "totp": _totp_now()}
    r = await http.post(f"{ROOT}{LOGIN_EP}", headers=_angel_headers(), json=payload, timeout=15)
    try:
        data = r.json()
    except Exception:
        raise HTTPException(502, "Login returned non-JSON")
    if not data.get("status"):
        raise HTTPException(401, f"Login failed: {data.get('message')}")
    d = data["data"]
    return d["jwtToken"], d["refreshToken"], d.get("feedToken")

def _norm_price(v: Optional[float]) -> Optional[float]:
    if isinstance(v, (int, float)):
        return float(v / 100.0) if v > 100000 else float(v)
    return None

# ------------------ REST: Quotes (ALL from INDEX_TOKEN_MAP) ------------------
@router.get("/quotes")
async def quotes_all():
    """
    Returns quotes for all symbols defined in INDEX_TOKEN_MAP.
    Response:
      { "NIFTY": {"ltp": 25114.0, "close": 25070.5}, ... }
    """
    if miss := _config_missing():
        raise HTTPException(503, f"AngelOne not configured. Missing: {', '.join(miss)}")

    names: List[str] = list(INDEX_TOKEN_MAP.keys())
    if not names:
        return {}

    async with httpx.AsyncClient() as http:
        jwt, _rt, _feed = await _login(http)

        # Build request body: {"mode":"FULL","exchangeTokens":{"NSE":[...],"BSE":[...]}}
        ex_tokens: Dict[str, List[str]] = {}
        tok_to_name: Dict[str, str] = {}
        for n in names:
            cfg = INDEX_TOKEN_MAP[n]
            ex = cfg["exchange"]; tok = cfg["symboltoken"]
            ex_tokens.setdefault(ex, []).append(tok)
            tok_to_name[tok] = n

        body = {"mode": "FULL", "exchangeTokens": ex_tokens}
        r = await http.post(f"{ROOT}{QUOTE_EP}", headers=_angel_headers(jwt), json=body, timeout=15)

        try:
            resp = r.json()
        except Exception:
            raise HTTPException(502, "Quote API returned non-JSON")

        if not resp.get("status", False):
            raise HTTPException(502, f"Quote API error: {resp.get('message') or 'unknown'}")

        raw = resp.get("data")
        items: List[dict] = []
        if isinstance(raw, list):
            items = [x for x in raw if isinstance(x, dict)]
        elif isinstance(raw, dict):
            for v in raw.values():
                if isinstance(v, list):
                    items.extend([x for x in v if isinstance(x, dict)])

        out: Dict[str, Dict[str, Optional[float]]] = {n: {"ltp": None, "close": None} for n in names}

        # Extract ltp & close robustly
        for item in items:
            token = str(item.get("symboltoken") or item.get("symbolToken") or item.get("token") or "")
            name = tok_to_name.get(token)
            if not name:
                continue
            out[name] = item

        return out

# ------------------ WS: Live stream (ALL from INDEX_TOKEN_MAP) ------------------
@router.websocket("/ws/stream")
async def stream_all(ws: WebSocket):
    """
    Streams LTP for all INDEX_TOKEN_MAP symbols.
    Messages like: {"symbol":"NIFTY","ltp":25114.0}
    """
    await ws.accept()

    if miss := _config_missing():
        await ws.send_json({"event": "error", "message": f"AngelOne not configured. Missing: {', '.join(miss)}"})
        await ws.close()
        return

    names: List[str] = list(INDEX_TOKEN_MAP.keys())
    if not names:
        await ws.send_json({"event": "error", "message": "No symbols configured server-side."})
        await ws.close()
        return

    # login first to get jwt & feed_token
    try:
        async with httpx.AsyncClient() as http:
            jwt, _rt, feed = await _login(http)
    except Exception as e:
        await ws.send_json({"event":"error","message":f"login failed: {e}"}); await ws.close(); return

    headers = {
        "Authorization": f"Bearer {jwt}",
        "x-api-key": API_KEY,
        "x-client-code": CLIENT_CODE,
        "x-feed-token": feed or "",
    }

    # Prepare subscribe payload (mode=3 => LTP)
    groups: Dict[int, List[str]] = {}
    tok2name: Dict[str, str] = {}
    for n in names:
        cfg = INDEX_TOKEN_MAP[n]
        et = EX_TYPE[cfg["exchange"]]
        tok = cfg["symboltoken"]
        groups.setdefault(et, []).append(tok)
        tok2name[tok] = n
    token_list = [{"exchangeType": et, "tokens": toks} for et, toks in groups.items()]
    subscribe_msg = json.dumps({"correlationID": "sub-1", "action": "subscribe", "params": {"mode": 3, "tokenList": token_list}})
    setmode_msg   = json.dumps({"action": "setmode", "params": [{"mode":"LTP", **blk} for blk in token_list]})

    # Run blocking WS client in background thread
    loop = asyncio.get_event_loop()

    def _ws_worker():
        try:
            w = create_connection(WSS_URL, header=[f"{k}: {v}" for k, v in headers.items()])
            w.send(subscribe_msg)
            try: w.send(setmode_msg)
            except Exception: pass

            while True:
                msg = w.recv()
                try:
                    obj = json.loads(msg) if isinstance(msg, str) else msg
                except Exception:
                    continue

                items = []
                if isinstance(obj, dict) and "data" in obj:
                    d = obj["data"]; items = d if isinstance(d, list) else [d]
                elif isinstance(obj, list):
                    items = obj
                elif isinstance(obj, dict):
                    items = [obj]

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
