# generateResearchPdf.py
import os
from io import BytesIO
from datetime import datetime
from fastapi import HTTPException
from weasyprint import HTML
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.colors import HexColor
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import signers, PdfSignatureMetadata
from pyhanko.sign.fields import SigFieldSpec
import tempfile
import asyncio

from routes.Research_Report.report_html import returnHtmlContent

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
ASSETS_DIR = os.path.join(PROJECT_ROOT, "logo")
WATERMARK_LOGO = os.path.join(ASSETS_DIR, "pride-logo1.png")  # used for watermark

async def sign_pdf(pdf_bytes: bytes) -> bytes:
    """Sign the PDF bytes using certificate and return the signed bytes."""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name
        signed_pdf_path = tmp_path + "_signed.pdf"

        def sign_pdf_sync():
            signer = signers.SimpleSigner.load_pkcs12(
                pfx_file='./certificate.pfx',
                passphrase=b'123456'  # update if needed
            )
            with open(tmp_path, 'rb') as doc:
                writer = IncrementalPdfFileWriter(doc, strict=False)
                sig_field_spec = SigFieldSpec(
                    'Signature1',
                    on_page=-1,
                    box=(400, 50, 550, 110)
                )
                signed_pdf_io = signers.sign_pdf(
                    writer,
                    signature_meta=PdfSignatureMetadata(field_name='Signature1'),
                    signer=signer,
                    existing_fields_only=False,
                    new_field_spec=sig_field_spec
                )
            with open(signed_pdf_path, 'wb') as outf:
                outf.write(signed_pdf_io.getvalue())
            return signed_pdf_path

        result = await asyncio.to_thread(sign_pdf_sync)
        os.remove(tmp_path)
        with open(result, "rb") as f:
            signed_pdf_bytes = f.read()
        os.remove(result)
        return signed_pdf_bytes

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Signing failed: {e}")

def create_watermark_overlay(page_width: float, page_height: float):
    """Create a watermark overlay with the logo."""
    from reportlab.pdfgen import canvas as rl_canvas
    from io import BytesIO
    buf = BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(page_width, page_height))
    # Centered rotated logo
    c.saveState()
    c.translate(page_width / 2, page_height / 2)
    c.rotate(45)
    c.setFillAlpha(0.08)
    c.drawImage(
        WATERMARK_LOGO,
        -375, -125,  # (-width/2, -height/2)
        width=750, height=250,
        mask='auto'
    )
    c.restoreState()
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]

def create_footer_overlay(page_width: float, page_height: float, page_number=None, total_pages=None):
    """Create an overlay page with footer and page numbers."""
    packet = BytesIO()
    c = canvas.Canvas(packet, pagesize=(page_width, page_height))

    if page_number is not None and total_pages is not None and page_number > 1:
        c.setFillColor(HexColor('#000080'))
        c.setFont("Helvetica-Bold", 9)
        c.drawRightString(page_width - 30, 35, f"Page {page_number} of {total_pages}")

    c.setFillColor(HexColor('#000080'))
    c.setFont("Helvetica-Bold", 8)
    t1 = "Our past performance does not guarantee the future performance. Investment in market is subject to market risk. Not with standing all the efforts to do"
    t2 = "best research, clients should understand that investing in market involves a risk of loss of both income and principal. Please ensure that you"
    t3 = "understand fully the risks involved in investment in market."
    c.drawCentredString(page_width / 2, 25, t1)
    c.drawCentredString(page_width / 2, 15, t2)
    c.drawCentredString(page_width / 2, 5,  t3)

    c.save()
    packet.seek(0)
    return PdfReader(packet).pages[0]

def _adapt_research_report_to_html_payload(rr) -> dict:
    """
    Adapt an ORM object or dict into the payload shape returnHtmlContent() expects.
    This is schema-agnostic and resilient to missing attributes/keys.
    """

    def get_any(src, *names, default=None):
        # Try attrs first, then dict keys
        for n in names:
            if hasattr(src, n):
                return getattr(src, n)
            if isinstance(src, dict) and n in src:
                return src[n]
        # last chance: __dict__
        if hasattr(src, "__dict__"):
            d = vars(src)
            for n in names:
                if n in d:
                    return d[n]
        return default

    def as_iter(x):
        if not x:
            return []
        return x if isinstance(x, (list, tuple)) else []

    # ----- header -----
    report_date = get_any(rr, "report_date", "date", default=datetime.utcnow().date())
    if hasattr(report_date, "strftime"):
        hdr_date = report_date.strftime("%Y-%m-%d")
    else:
        hdr_date = str(report_date) or datetime.utcnow().strftime("%Y-%m-%d")

    title = get_any(rr, "title", "report_title", "name", default="Technical Market Outlook")

    payload = {
        "header": {
            "date": hdr_date,
            "time": datetime.utcnow().strftime("%H:%M"),
            "title": title,
        },
        "gainers": [],
        "losers": [],
        "events": [],
        "ipos": [],
        "commentary": [],
        "stockPicks": [],
        "fiiActivity": [],
        "commentary_images": {},
        "stockpick_images": {},
    }

    # ----- market movers -----
    top_gainers = get_any(rr, "top_gainers", "gainers", default=[])
    top_losers  = get_any(rr, "top_losers",  "losers",  default=[])

    for g in as_iter(top_gainers):
        # support dict rows or objects with attrs
        payload["gainers"].append({
            "symbol": get_any(g, "symbol", default=""),
            "cmp": get_any(g, "cmp", "price", "ltp", default=""),
            "change": get_any(g, "price_change", "change", default=""),
            "changePct": get_any(g, "change_pct", "changePct", default=""),
        })

    for l in as_iter(top_losers):
        payload["losers"].append({
            "symbol": get_any(l, "symbol", default=""),
            "cmp": get_any(l, "cmp", "price", "ltp", default=""),
            "change": get_any(l, "price_change", "change", default=""),
            "changePct": get_any(l, "change_pct", "changePct", default=""),
        })

    # ----- IPOs -----
    ipos = get_any(rr, "ipo", "ipos", "ipo_list", default=[])
    for i in as_iter(ipos):
        open_dt  = get_any(i, "open_date", "openDate", default="")
        close_dt = get_any(i, "close_date", "closeDate", default="")
        def _fmt(d):
            if not d: return ""
            if hasattr(d, "strftime"): return d.strftime("%Y-%m-%d")
            return str(d)
        payload["ipos"].append({
            "company":    get_any(i, "company", "name", default=""),
            "category":   get_any(i, "category", default=""),
            "lotSize":    get_any(i, "lot_size", "lotSize", default=""),
            "priceRange": get_any(i, "price_range", "priceRange", default=""),
            "openDate":   _fmt(open_dt),
            "closeDate":  _fmt(close_dt),
        })

    # ----- Events (board meetings / corporate actions / results) -----
    for e in as_iter(get_any(rr, "board_meeting", "board_meetings", default=[])):
        dt = get_any(e, "date", default="")
        dt = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else (dt or "")
        payload["events"].append({
            "company": get_any(e, "company", "name", default=""),
            "date": dt,
            "type": "Board Meeting",
            "ltp": "",
            "change": "",
        })
    for e in as_iter(get_any(rr, "corporate_action", "corporate_actions", default=[])):
        dt = get_any(e, "ex_date", "date", default="")
        dt = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else (dt or "")
        payload["events"].append({
            "company": get_any(e, "company", "name", default=""),
            "date": dt,
            "type": get_any(e, "action", "type", default="Corporate Action"),
            "ltp": "",
            "change": "",
        })
    for e in as_iter(get_any(rr, "result_calendar", "results", default=[])):
        dt = get_any(e, "date", default="")
        dt = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else (dt or "")
        payload["events"].append({
            "company": get_any(e, "company", "name", default=""),
            "date": dt,
            "type": get_any(e, "type", default="Result"),
            "ltp": get_any(e, "ltp", default=""),
            "change": get_any(e, "change", default=""),
        })

    # ----- Commentary (index calls) -----
    for c in as_iter(get_any(rr, "calls_index", "index_calls", default=[])):
        payload["commentary"].append({
            "indexName": get_any(c, "symbol", "index", default=""),
            "text":      get_any(c, "view", "comment", default=""),
            "level1":    f"Entry: {get_any(c,'entry_at','entry','',default='')} / Buy Above: {get_any(c,'buy_above','buyAbove',default='')}",
            "level2":    f"T1: {get_any(c,'t1',default='')}  T2: {get_any(c,'t2',default='')}",
            "level3":    f"SL: {get_any(c,'sl','stoploss',default='')}",
        })

    # ----- Stock picks (stock calls) -----
    for s in as_iter(get_any(rr, "calls_stock", "stock_calls", default=[])):
        payload["stockPicks"].append({
            "name":       get_any(s, "symbol", "name", default=""),
            "cmp":        get_any(s, "entry_at", "cmp", default=""),
            "commentary": get_any(s, "view", "comment", default=""),
            "buyLevel":   get_any(s, "buy_above", "buyAbove", default=""),
            "target1":    get_any(s, "t1", default=""),
            "target2":    get_any(s, "t2", default=""),
            "stopLoss":   get_any(s, "sl", "stoploss", default=""),
        })

    # ----- FII / DII -----
    fii_dii = get_any(rr, "fii_dii", "fiiActivity", default=None)
    if isinstance(fii_dii, dict):
        d_date = fii_dii.get("date")
        if hasattr(d_date, "strftime"):
            d_date_str = d_date.strftime("%Y-%m-%d")
        else:
            d_date_str = d_date or datetime.utcnow().strftime("%Y-%m-%d")
        if fii_dii.get("fii_fpi"):
            f = fii_dii["fii_fpi"]
            payload["fiiActivity"].append({
                "item": "FII/FPI",
                "date": d_date_str,
                "buy":  f.get("buy"),
                "sell": f.get("sell"),
                "netPosition": ( (f.get("buy") or 0) - (f.get("sell") or 0) ),
            })
        if fii_dii.get("dii"):
            f = fii_dii["dii"]
            payload["fiiActivity"].append({
                "item": "DII",
                "date": d_date_str,
                "buy":  f.get("buy"),
                "sell": f.get("sell"),
                "netPosition": ( (f.get("buy") or 0) - (f.get("sell") or 0) ),
            })

    return payload


async def generate_outlook_pdf(rr_or_payload):
    """
    Accepts either:
      - ORM object ResearchReport (we adapt it), or
      - a dict in DB/schema shape (we still adapt it),
      - a dict already in template shape (detected & passed through).
    Returns signed PDF bytes.
    """

    def _looks_template_shaped(d: dict) -> bool:
        # If it already has keys used by the template, don't re-map.
        must_have_any = {"header", "gainers", "losers", "events", "ipos", "commentary", "stockPicks", "fiiActivity"}
        return isinstance(d, dict) and any(k in d for k in must_have_any)

    # ✅ Always adapt unless it's clearly already template-shaped
    if isinstance(rr_or_payload, dict):
        if _looks_template_shaped(rr_or_payload):
            payload = rr_or_payload
        else:
            payload = _adapt_research_report_to_html_payload(rr_or_payload)
    else:
        payload = _adapt_research_report_to_html_payload(rr_or_payload)

    # (Optional) ensure a title in header
    payload.setdefault("header", {})
    payload["header"].setdefault("title", "Technical Market Outlook")

    print("payload (template-shaped): ", payload)

    # 1) Build HTML
    try:
        html_content = returnHtmlContent(payload)
    except Exception as e:
        raise HTTPException(400, f"Error building HTML: {e}")

    # 2) Render to PDF
    try:
        pdf_bytes = HTML(string=html_content, base_url=os.getcwd()).write_pdf()
    except Exception as e:
        raise HTTPException(500, f"PDF rendering failed: {e}")

    # 3) Add watermark/footer then sign
    try:
        pdf_writer = PdfWriter()
        pdf_reader = PdfReader(BytesIO(pdf_bytes))
        total_pages = len(pdf_reader.pages)
        for i, page in enumerate(pdf_reader.pages):
            mediabox = page.mediabox
            page_width  = float(mediabox.width)
            page_height = float(mediabox.height)

            wm = create_watermark_overlay(page_width, page_height)
            page.merge_page(wm)

            footer = create_footer_overlay(page_width, page_height, i+1, total_pages)
            page.merge_page(footer)

            pdf_writer.add_page(page)

        out_io = BytesIO()
        pdf_writer.write(out_io)
        out_io.seek(0)
        processed = out_io.getvalue()

        signed_pdf_bytes = await sign_pdf(processed)
        return signed_pdf_bytes
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"PDF processing/signing failed: {e}")

