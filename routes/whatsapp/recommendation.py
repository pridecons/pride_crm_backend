import requests
import json
from config import WHATSAPP_ACCESS_TOKEN, PHONE_NUMBER_ID

def _sd_get(sd, key, default=None):
    """Read from dict or object."""
    if sd is None:
        return default
    if isinstance(sd, dict):
        return sd.get(key, default)
    return getattr(sd, key, default)

def _fmt_num(v):
    """Format numbers nicely, preserve 0, but show '-' for None/''."""
    if v is None or v == "":
        return "-"
    try:
        s = ("%.6f" % float(v)).rstrip("0").rstrip(".")
        return s if s else "0"
    except Exception:
        return str(v)

def _fmt_rec_type(v):
    """Join list to comma string; pass through string; '-' if empty."""
    if v is None or v == "":
        return "-"
    if isinstance(v, (list, tuple, set)):
        return ", ".join(str(x) for x in v if str(x).strip()) or "-"
    return str(v)

def whatsapp_recommendation(number: str, data: dict):
    """
    Send WhatsApp template message using Cloud API.
    Your template 'recommendation' must have exactly 5 body variables in this order:
      {{1}} rec_type_display
      {{2}} stock_name
      {{3}} entry_price_disp
      {{4}} targets (t1-t2-t3)
      {{5}} stop_loss_disp
    """
    stock_name        = _sd_get(data, "stock_name")
    rec_type_display  = _fmt_rec_type(_sd_get(data, "recommendation_type"))
    entry_price_disp  = _fmt_num(_sd_get(data, "entry_price"))
    stop_loss_disp    = _fmt_num(_sd_get(data, "stop_loss"))
    t1_disp           = _fmt_num(_sd_get(data, "targets"))
    t2_disp           = _fmt_num(_sd_get(data, "targets2"))
    t3_disp           = _fmt_num(_sd_get(data, "targets3"))

    # Build targets text (e.g., "100-110-120"); collapse repeated '-' nicely
    targets_disp = "-".join(x for x in [t1_disp, t2_disp, t3_disp] if x)

    url = f"https://graph.facebook.com/v17.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    # IMPORTANT:
    # - use "type": "text" for body parameters
    # - no "parameter_name" field
    # - language code must match your template (often "en_US")
    payload = {
    "messaging_product": "whatsapp",
    "recipient_type": "individual",
    "to": f"91{str(number).lstrip('+').lstrip('0')}",
    "type": "template",
    "template": {
        "name": "recommendation",      # must match exactly
        "language": {"code": "en"}, # or "en" depending on what you set
        "components": [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": rec_type_display},
                    {"type": "text", "text": str(stock_name or "-")},
                    {"type": "text", "text": entry_price_disp},
                    {"type": "text", "text": targets_disp},
                    {"type": "text", "text": stop_loss_disp},
                ],
            }
        ],
    },
}


    resp = requests.post(url, headers=headers, json=payload)
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}

    print("Status Code:", resp.status_code)
    print("Response:", json.dumps(data, indent=2))
    return data
