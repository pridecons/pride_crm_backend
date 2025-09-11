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
WATERMARK_LOGO = os.path.join(ASSETS_DIR, "pride.png")  # used for watermark

def _read_bytes(path: str) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return b""

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
    Convert your ResearchReport ORM object into the dict
    that returnHtmlContent() expects.
    """
    # Header
    hdr_date = (rr.report_date or datetime.utcnow().date()).strftime("%Y-%m-%d")
    payload = {
        "header": {
            "date": hdr_date,
            "time": datetime.utcnow().strftime("%H:%M"),
            "title": rr.title or "Technical Market Outlook",
        },
        # Top gainers/losers mapping
        "gainers": [],
        "losers": [],
        # Events: combine board meetings / corporate actions / results as a simple table
        "events": [],
        # IPOs
        "ipos": [],
        # Commentary (we’ll map index & stock calls concisely)
        "commentary": [],
        # Stock picks
        "stockPicks": [],
        # FII activity (flatten FII/DII if given)
        "fiiActivity": [],
        # Optional images
        "commentary_images": {},
        "stockpick_images": {},
    }

    # Map gainers/losers (if your schema uses top_gainers/top_losers)
    if rr.top_gainers:
        for g in rr.top_gainers:
            payload["gainers"].append({
                "symbol": g.get("symbol"),
                "cmp": g.get("cmp"),
                "change": g.get("price_change"),
                "changePct": g.get("change_pct"),
            })
    if rr.top_losers:
        for l in rr.top_losers:
            payload["losers"].append({
                "symbol": l.get("symbol"),
                "cmp": l.get("cmp"),
                "change": l.get("price_change"),
                "changePct": l.get("change_pct"),
            })

    # IPOs
    if rr.ipo:
        for i in rr.ipo:
            payload["ipos"].append({
                "company": i.get("company"),
                "category": i.get("category"),
                "lotSize": i.get("lot_size"),
                "priceRange": i.get("price_range"),
                "openDate": (i.get("open_date") or "") if isinstance(i.get("open_date"), str) else (i.get("open_date") and i.get("open_date").strftime("%Y-%m-%d")) or "",
                "closeDate": (i.get("close_date") or "") if isinstance(i.get("close_date"), str) else (i.get("close_date") and i.get("close_date").strftime("%Y-%m-%d")) or "",
            })

    # Events: unify three lists into one table (optional)
    if rr.board_meeting:
        for e in rr.board_meeting:
            payload["events"].append({
                "company": e.get("company"),
                "date": (e.get("date") or "") if isinstance(e.get("date"), str) else (e.get("date") and e.get("date").strftime("%Y-%m-%d")) or "",
                "type": "Board Meeting",
                "ltp": "",
                "change": "",
            })
    if rr.corporate_action:
        for e in rr.corporate_action:
            payload["events"].append({
                "company": e.get("company"),
                "date": (e.get("ex_date") or "") if isinstance(e.get("ex_date"), str) else (e.get("ex_date") and e.get("ex_date").strftime("%Y-%m-%d")) or "",
                "type": e.get("action"),
                "ltp": "",
                "change": "",
            })
    if rr.result_calendar:
        for e in rr.result_calendar:
            payload["events"].append({
                "company": e.get("company"),
                "date": (e.get("date") or "") if isinstance(e.get("date"), str) else (e.get("date") and e.get("date").strftime("%Y-%m-%d")) or "",
                "type": e.get("type"),
                "ltp": e.get("ltp"),
                "change": e.get("change"),
            })

    # Commentary: from index calls
    if rr.calls_index:
        for c in rr.calls_index:
            payload["commentary"].append({
                "indexName": c.get("symbol"),
                "text": c.get("view") or "",
                "level1": f"Entry: {c.get('entry_at') or ''} / Buy Above: {c.get('buy_above') or ''}",
                "level2": f"T1: {c.get('t1') or ''}  T2: {c.get('t2') or ''}",
                "level3": f"SL: {c.get('sl') or ''}",
            })
            # Optional image bytes could be attached in payload["commentary_images"][idx] = <bytes>

    # Stock picks: from stock calls
    if rr.calls_stock:
        for s in rr.calls_stock:
            payload["stockPicks"].append({
                "name": s.get("symbol"),
                "cmp": s.get("entry_at"),
                "commentary": s.get("view") or "",
                "buyLevel": s.get("buy_above"),
                "target1": s.get("t1"),
                "target2": s.get("t2"),
                "stopLoss": s.get("sl"),
                # if you host images, you can load bytes and put in stockpick_images
            })

    # FII Activity (if rr.fii_dii provided)
    if rr.fii_dii and isinstance(rr.fii_dii, dict):
        d = rr.fii_dii
        d_date = d.get("date")
        if isinstance(d_date, datetime):
            d_date = d_date.date()
        d_date_str = d_date.strftime("%Y-%m-%d") if d_date else datetime.utcnow().strftime("%Y-%m-%d")
        if d.get("fii_fpi"):
            f = d["fii_fpi"]
            payload["fiiActivity"].append({
                "item": "FII/FPI",
                "date": d_date_str,
                "buy": f.get("buy"),
                "sell": f.get("sell"),
                "netPosition": ( (f.get("buy") or 0) - (f.get("sell") or 0) ),
            })
        if d.get("dii"):
            f = d["dii"]
            payload["fiiActivity"].append({
                "item": "DII",
                "date": d_date_str,
                "buy": f.get("buy"),
                "sell": f.get("sell"),
                "netPosition": ( (f.get("buy") or 0) - (f.get("sell") or 0) ),
            })

    return payload

async def generate_outlook_pdf(rr_or_payload):
    """
    Accepts either:
      - ORM object ResearchReport (we adapt it), or
      - already-prepared payload dict for the HTML template.
    Returns signed PDF bytes (you can upload/store if needed).
    """
    if isinstance(rr_or_payload, dict):
        payload = rr_or_payload
    else:
        payload = _adapt_research_report_to_html_payload(rr_or_payload)

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
        page_width, page_height = 595.276, 841.890  # A4 in points

        wm = create_watermark_overlay(page_width, page_height)
        for i, page in enumerate(pdf_reader.pages):
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
