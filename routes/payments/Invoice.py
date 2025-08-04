# invoice_generator.py

from fastapi import HTTPException, status
import os
from datetime import datetime
from typing import List, Dict, Any
from dateutil.relativedelta import relativedelta
from jinja2 import Template
from weasyprint import HTML
from num2words import num2words
from io import BytesIO

from db.connection import get_db
from db.models import Lead, Invoice, Payment

from reportlab.pdfgen import canvas
from reportlab.pdfgen import canvas as rl_canvas
import tempfile
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import signers, PdfSignatureMetadata
from pyhanko.sign.fields import SigFieldSpec
from PyPDF2 import PdfReader, PdfWriter
import uuid
from datetime import datetime
from sqlalchemy import event
import asyncio
from services.mail_with_file import send_mail_by_client_with_file

async def sign_pdf(pdf_bytes: bytes) -> bytes:
    """
    Sign the PDF bytes using the certificate and return the signed PDF bytes.
    """
    try:
        # Save the PDF bytes to a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name

        signed_pdf_path = tmp_path + "_signed.pdf"

        def sign_pdf_sync():
            # Load the signing certificate (PKCS#12 file)
            signer = signers.SimpleSigner.load_pkcs12(
                pfx_file='./certificate.pfx', 
                passphrase=b'123456'  # Update your passphrase
            )
            with open(tmp_path, 'rb') as doc:
                writer = IncrementalPdfFileWriter(doc, strict=False)

                sig_field_spec = SigFieldSpec(
                    'Signature1',
                    on_page=-1,
                    box=(390, 250, 520, 300)
                )

                # (left, bottom, right, top)

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
        raise HTTPException(status_code=500, detail=str(e))

# ─── STATE CODE MAP ────────────────────────────────────────────────────────────

state_code = {
    "JAMMU AND KASHMIR": 1,
    "HIMACHAL PRADESH": 2,
    "PUNJAB": 3,
    "CHANDIGARH": 4,
    "UTTARAKHAND": 5,
    "HARYANA": 6,
    "DELHI": 7,
    "RAJASTHAN": 8,
    "UTTAR PRADESH": 9,
    "BIHAR": 10,
    "SIKKIM": 11,
    "ARUNACHAL PRADESH": 12,
    "NAGALAND": 13,
    "MANIPUR": 14,
    "MIZORAM": 15,
    "TRIPURA": 16,
    "MEGHALAYA": 17,
    "ASSAM": 18,
    "WEST BENGAL": 19,
    "JHARKHAND": 20,
    "ODISHA": 21,
    "CHATTISGARH": 22,
    "MADHYA PRADESH": 23,
    "GUJARAT": 24,
    "DADRA AND NAGAR HAVELI AND DAMAN AND DIU": 26,
    "MAHARASHTRA": 27,
    "ANDHRA PRADESH(BEFORE DIVISION)": 28,
    "KARNATAKA": 29,
    "GOA": 30,
    "LAKSHADWEEP": 31,
    "KERALA": 32,
    "TAMIL NADU": 33,
    "PUDUCHERRY": 34,
    "ANDAMAN AND NICOBAR ISLANDS": 35,
    "TELANGANA": 36,
    "ANDHRA PRADESH": 37,
    "LADAKH (NEWLY ADDED)": 38,
    "OTHER TERRITORY": 97,
    "CENTRE JURISDICTION": 99
}

def create_header_overlay(page_width: float, page_height: float):
    """
    Create an overlay PDF page containing the header.
    - Top left: pride logo
    - Top right: CIN, email, and call details (one per line)
    """
    pride_logo_path = "logo/pride-logo1.png"

    SEBINumber = "SEBI Number: INH000010362"
    GSTIN = "GSTIN : 24AAMCP7919A1ZF"

    cin = "CIN: U67190GJ2022PTC130684"
    
    packet = BytesIO()
    c = canvas.Canvas(packet, pagesize=(page_width, page_height))
    
    # Draw the pride logo on the top left (if file exists)
    if os.path.exists(pride_logo_path):
        logo_width = 140  
        logo_height = 40  
        # Position: 40 pts from left, 20 pts from top (adjusting for logo height)
        c.drawImage(pride_logo_path, 30, page_height - logo_height - 20, 
                   width=logo_width, height=logo_height)
    else:
        # If logo doesn't exist, draw company name instead
        c.setFont("Helvetica-Bold", 14)
        c.drawString(40, page_height - 40, "Pride Trading Consultancy Pvt. Ltd.")
    
    # Draw the CIN, email, and call details on the top right
    header_details = [cin, SEBINumber, GSTIN]
    c.setFont("Helvetica", 10)
    margin = 20  # margin from right edge
    line_height = 12  # vertical space between lines
    
    # Start from the top with some padding (20 pts from the top)
    text_y = page_height - 30
    for line in header_details:
        c.drawString(page_width - 150 - margin, text_y, line)
        text_y -= line_height
    
    c.save()
    packet.seek(0)
    return PdfReader(packet).pages[0]

def create_watermark_overlay(page_width: float, page_height: float, text: str = None):
    """
    Create a watermark overlay with the company name diagonally across the page.
    """
    if text is None:
        text = "Pride Trading Consultancy Private Limited"
    
    buffer = BytesIO()
    c = rl_canvas.Canvas(buffer, pagesize=(page_width, page_height))
    c.setFont("Helvetica-Bold", 38)
    c.setFillColorRGB(0.8, 0.8, 0.8, alpha=0.2)  # light gray with transparency

    # Save the current state before rotating
    c.saveState()
    
    # Rotate and translate (this centers the text)
    c.translate(page_width / 2, page_height / 2)
    c.rotate(45)  # 45 degrees rotation for diagonal watermark
    
    # Draw the watermark centered
    c.drawCentredString(0, 0, text)

    c.restoreState()
    c.save()
    buffer.seek(0)

    return PdfReader(buffer).pages[0]

def apply_overlays_to_pdf(pdf_bytes: bytes, add_header: bool = True, add_watermark: bool = True) -> bytes:
    """
    Apply header and watermark overlays to an existing PDF.
    """
    # Read the original PDF
    pdf_reader = PdfReader(BytesIO(pdf_bytes))
    pdf_writer = PdfWriter()
    
    for page_num, page in enumerate(pdf_reader.pages):
        # Get page dimensions
        page_width = float(page.mediabox.width)
        page_height = float(page.mediabox.height)
        
        # Create overlays
        if add_watermark:
            watermark_overlay = create_watermark_overlay(page_width, page_height)
            page.merge_page(watermark_overlay)
        
        if add_header and page_num == 0:  # Only add header to first page
            header_overlay = create_header_overlay(page_width, page_height)
            page.merge_page(header_overlay)
        
        pdf_writer.add_page(page)
    
    # Write the result to bytes
    output_buffer = BytesIO()
    pdf_writer.write(output_buffer)
    output_buffer.seek(0)
    return output_buffer.getvalue()

# ─── HTML TEMPLATE ──────────────────────────────────────────────────────────────

pdf_format = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Tax Invoice {{ invoice_no }}</title>
  <style>
    body { font-family: Arial, sans-serif; margin:0; padding:0; font-size:10px; line-height:1.2; }
    .container { width:100%; max-width:190mm; margin:0 auto; padding:5mm; box-sizing:border-box; }
    
    .header { text-align:center; margin-bottom:10px; margin-top:70px; }
    .header h1 { margin:60px 0 5px 0; font-size:18px; font-weight:bold; }
    .header p { margin:2px 0; font-size:9px; }
    .header h2 { margin:8px 0 3px 0; font-size:16px; }
    .header hr { margin:5px 0; border:1px solid #000; }
    
    table { width:100%; border-collapse:collapse; margin:5px 0; }
    td, th { border:1px solid #ddd; padding:3px; font-size:9px; vertical-align:top; }
    th { background:#f5f5f5; font-weight:bold; text-align:center; }
    .right { text-align:right; }
    
    .info-table td { padding:4px; }
    .bill-table td { padding:4px; }
    
    .services-table th { font-size:8px; padding:2px; }
    .services-table td { font-size:8px; padding:2px; }
    
    .bottom-section { margin-top:10px; display:flex; justify-content:space-between; }
    .payment-section { width:48%; }
    .totals-section { width:48%; }
    
    .amount-words { margin:8px 0; font-style:italic; font-size:9px; }
    
    .terms { margin-top:8px; }
    .terms h3 { margin:5px 0 3px 0; font-size:10px; }
    .terms p { margin:0; font-size:8px; line-height:1.3; }
    
    .signature { margin-top:8px; text-align:right; font-size:8px; }
    .signature p { margin:2px 0; }
    
    h3 { margin:8px 0 3px 0; font-size:11px; font-weight:bold; }
    
    @page { size: A4 portrait; margin:8mm; }
    
    .col-sno { width:5%; }
    .col-sac { width:8%; }
    .col-plan { width:15%; }
    .col-desc { width:22%; }
    .col-duration { width:15%; }
    .col-start { width:10%; }
    .col-end { width:15%; }
    .col-charges { width:10%; }
    .col-paid { width:10%; }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Pride Trading Consultancy Pvt. Ltd.</h1>
      <p>410-411, Serene Centrum Sevasi Road, Vadodara, Gujarat 390021</p>
      <p style="margin-bottom:20px">Phone: +91 9981919424 | Email: compliance@pridecons.com</p>
      <hr/>
      <h2 style="margin-top:10px;">Tax Invoice</h2>
      <p><strong>Original for Recipient</strong></p>
    </div>

    <table class="info-table">
      <tr>
        <td style="width:33%"><strong>Invoice No:</strong> {{ invoice_no }}</td>
        <td style="width:34%"><strong>Reverse Charge:</strong> {{ reverse_charge }}</td>
        <td style="width:33%"><strong>Invoice Date:</strong> {{ invoice_date }}</td>
      </tr>
      <tr>
        <td colspan="2"><strong>Order Id:</strong> {{ order_id }}</td>
        <td ><strong>State:</strong> {{ state }} (Code {{ state_code }})</td>
      </tr>
    </table>

    <h3 style="text-align:center; margin-top:30px;">Bill To:</h3>
    <table class="bill-table">
      <tr>
        <td style="width:50%"><strong>Name:</strong> {{ customer.name }}</td>
        <td style="width:50%"><strong>Mobile:</strong> {{ customer.mobile }}</td>
      </tr>
      <tr>
        <td colspan="2"><strong>Address:</strong> {{ customer.address }}</td>
      </tr>
      <tr>
        <td><strong>Email:</strong> {{ customer.email }}</td>
        <td><strong>PAN:</strong> {{ customer.pan }}</td>
      </tr>
      <tr>
        <td><strong>Aadhaar:</strong> {{ customer.aadhaar }}</td>
        <td><strong>GSTIN:</strong> {{ customer.gstin }} | <strong>State:</strong> {{ customer.state }} ({{ customer.state_code }})</td>
      </tr>
    </table>

    <h3 style="text-align:center; margin-top:30px;">Details of Services</h3>
    <table class="services-table">
      <thead>
        <tr>
          <th class="col-sno">S.No</th>
          <th class="col-sac">SAC</th>
          <th class="col-plan">Plan</th>
          <th class="col-desc">Description</th>
          <th class="col-duration">Duration</th>
          <th class="col-start">Start</th>
          <th class="col-end">End</th>
          <th class="col-charges">Plan Charges(₹)</th>
          <th class="col-paid">Paid(₹)</th>
        </tr>
      </thead>
      <tbody>
      {% for item in items %}
        <tr>
          <td class="col-sno">{{ loop.index }}</td>
          <td class="col-sac">{{ item.sac }}</td>
          <td class="col-plan">{{ item.plan }}</td>
          <td class="col-desc">{{ item.desc }}</td>
          <td class="col-duration">{{ item.service_qty }}</td>
          <td class="col-start">{{ item.start }}</td>
          <td class="col-end">{{ item.end }}</td>
          <td class="col-charges right">{{ item.charges }}</td>
          <td class="col-paid right">{{ item.paid }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>

    <div class="bottom-section" style="margin-top:30px;">
      <div class="payment-section">
        <h3 style="text-align:center; margin-top:10px;">Payment Details</h3>
        <table>
          <tr><td><strong>Mode:</strong></td><td>{{ payment.mode }}</td></tr>
          <tr><td><strong>Amount Paid:</strong></td><td class="right">{{ payment.amount }}</td></tr>
        </table>
      </div>

      <div class="totals-section">
        <table>
          <tr><td>Service Charges</td><td class="right">₹{{ totals.service_charges }}</td></tr>
          {% if totals.igst %}
          <tr><td>IGST (18%)</td><td class="right">₹{{ totals.igst }}</td></tr>
          {% else %}
          <tr><td>CGST (9%)</td><td class="right">₹{{ totals.cgst }}</td></tr>
          <tr><td>SGST (9%)</td><td class="right">₹{{ totals.sgst }}</td></tr>
          {% endif %}
          <tr><td>Transaction Charges (2%)</td><td class="right">₹{{ totals.txn_charges }}</td></tr>
          <tr style="border-top:1px solid #000; font-weight:bold;">
            <td><strong>Total Paid Amount</strong></td>
            <td class="right"><strong>₹{{ totals.total }}</strong></td>
          </tr>
        </table>
      </div>
    </div>

    <div style="display: flex; justify-content: space-between; align-items: center;">
    <div class="amount-words">
      <strong>Amount in Words:</strong> {{ totals.in_words }}
    </div>

    <p>Certified that the particulars given above are true and correct</p>

    </div>
    <div style="margin-top: 150px; display:flex;">
      <div class="terms"  style="width: 65%;" >
        <h3>Terms &amp; Conditions</h3>
        <p>1. This is Computer Generated Invoice No Need Any Sign. & Stamp.</p>
        <p>2. Investment / Trading in Market is Subject to Market Risk.</p>
        <p>3. We are not liable for any refund with respect to complimentary services.</p>
        <p>4. In case of any disputes arising between Pride Trading Consultancy Pvt. Ltd. & the client, all the matters shall be subject to Vadodara Jurisdiction, Gujarat only.</p>
        <p>5. Payment of this invoice confirms the client's consent to the services rendered, affirming that the payment is made willingly and with full agreement.</p>
      </div>

      <div class="signature" style="width: 35%; display: flex; flex-direction: column; justify-content: flex-end; align-items: flex-end;">
        <p>For <strong>Pride Trading Consultancy Pvt. Ltd.</strong></p>
        <p><strong>Authorized Signatory</strong></p>
      </div>
    </div>

    
    <div style="margin-top:10px; text-align:center; font-size:8px; border-top:1px solid #ddd; padding-top:5px;">
      <p style="margin:2px 0;"><strong>Head Office:</strong> 410-411, Serene Centrum Sevasi Road, Vadodara Gujarat 390021</p>
    </div>
  </div>
</body>
</html>
"""

# ─── HELPERS ─────────────────────────────────────────────────────────────────────

def calculate_end_date(start_str: str, billing_cycle: str, call_count: int = 0) -> str:
    start = datetime.strptime(start_str, "%d-%b-%Y")
    cycle = billing_cycle.upper()
    if cycle == "CALL":
        return f"Until {call_count} calls completed"
    if cycle == "MONTHLY":
        end = start + relativedelta(months=1) - relativedelta(days=1)
    elif cycle == "YEARLY":
        end = start + relativedelta(years=1) - relativedelta(days=1)
    else:
        return ""
    return end.strftime("%d-%b-%Y")

def service_quantity(billing_cycle: str, call_count: int = 0, duration_day: int = 0) -> str:
    cycle = billing_cycle.upper()
    if cycle == "CALL":
        return f"{call_count} calls (No Time Limit)"
    elif cycle == "MONTHLY":
        return duration_day
    elif cycle == "YEARLY":
        return duration_day
    else:
        return billing_cycle

import math

def truncate_to_2(x: float) -> float:
    """Floor/truncate to 2 decimal places (not round)."""
    return math.floor(x * 100) / 100

def calculate_tax_breakdown(total_payment: float, state: str) -> dict:
    """
    Given total payment (which includes tax) and state, returns:
    service_charges (pre-tax), gateway_charges (2% truncated), net_service_charges,
    and IGST or CGST+SGST with rounding as in example.
    """
    if total_payment < 0:
        raise ValueError("total_payment must be non-negative")

    # Derive base service charges by removing 18% tax (since total = service + 18% tax)
    service_charges_raw = total_payment / 1.18
    service_charges = round(service_charges_raw + 1e-9, 2)  # standard rounding

    # Gateway charges: 2% of service, but truncated (floor) to 2 decimals
    gateway_charges_raw = service_charges_raw * 0.02
    gateway_charges = truncate_to_2(gateway_charges_raw)

    net_service_charges = service_charges - gateway_charges

    state_up = state.strip().upper()
    if state_up == "GUJARAT":
        igst = round(service_charges_raw * 0.18 + 1e-9, 2)
        cgst = sgst = 0.0
    else:
        igst = 0.0
        # each 9%, rounding normally
        cgst = round(service_charges_raw * 0.09 + 1e-9, 2)
        sgst = round(service_charges_raw * 0.09 + 1e-9, 2)

    total_tax = round(igst + cgst + sgst + 1e-9, 2)
    reconstructed_total = round(service_charges + total_tax + 1e-9, 2)

    return {
        "service_charges": service_charges,
        "gateway_charges": gateway_charges,
        "net_service_charges": round(net_service_charges + 1e-9, 2),
        "igst": igst,
        "cgst": cgst,
        "sgst": sgst,
        "total_tax": total_tax,
        "reconstructed_total": reconstructed_total,
    }

def build_invoice_details(payment: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pull details from Lead, calculate GST & txn charges INCLUSIVELY,
    where the paid_amount already includes all taxes and charges.
    """
    db_gen = get_db()
    db = next(db_gen)
    try:
        user = db.query(Lead).filter(Lead.mobile == payment["phone_number"]).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No Lead found with mobile {payment['phone_number']}"
            )

        plan = payment["plan"][0]
        discounted_price = plan["discounted_price"]
        start = datetime.fromisoformat(payment["created_at"]).strftime("%d-%b-%Y")
        end   = calculate_end_date(start, plan["billing_cycle"], payment.get("call", 0))

        duration_day = payment.get("duration_day", 0)
        qty   = service_quantity(plan["billing_cycle"], payment.get("call", 0), duration_day)

        # 1) Total paid amount (includes everything)
        paid_amount = payment["paid_amount"]

        # 2) Determine state & code
        cust_state = (user.state or "").upper()
        cust_code  = state_code.get(cust_state, "")


        taxes = calculate_tax_breakdown(paid_amount, cust_state)
        service_charges = taxes["service_charges"]
        gateway_charges = taxes["gateway_charges"]
        net_service_charges = taxes["net_service_charges"]
        igst = taxes["igst"]
        cgst = taxes["cgst"]
        sgst = taxes["sgst"]
        total_tax = taxes["total_tax"]
        
        # 7) Generate proper invoice number (will be set by the SQLAlchemy event listener)
        date_part = datetime.utcnow().strftime("%Y%m%d")
        random_part = uuid.uuid4().hex[:6].upper()
        invoice_no = f"INV-{date_part}-{random_part}"
        
        # 8) Convert to words (Indian English)
        in_words = num2words(paid_amount, lang="en_IN").capitalize() + " only"

        return {
            "invoice_no":     invoice_no,
            "order_id":       payment['order_id'],
            "invoice_date":   start,
            "reverse_charge": "N",
            "state":          user.state or "",
            "state_code":     cust_code,

            "customer": {
                "name":       user.full_name or payment["name"],
                "mobile":     user.mobile or payment["phone_number"],
                "address":    user.address or "",
                "email":      user.email or payment["email"],
                "pan":        user.pan or "",
                "aadhaar":    user.aadhaar or "",
                "gstin":      user.gstin or "URP",
                "state":      user.state or "",
                "state_code": cust_code
            },

            "items": [{
                "sac":         plan.get("id", ""),
                "plan":        plan.get("name", ""),
                "desc":        plan.get("description", ""),
                "service_qty": qty,
                "start":       start,
                "end":         end,
                "charges":     f"{discounted_price:,.2f}",  # Base service charges
                "paid":        f"{paid_amount:,.2f}"   # Total amount paid
            }],

            "totals": {
                "service_charges": f"{net_service_charges:,.2f}",
                "igst":            f"{igst:,.2f}" if igst else "",
                "cgst":            f"{cgst:,.2f}" if cgst else "",
                "sgst":            f"{sgst:,.2f}" if sgst else "",
                "txn_charges":     f"{gateway_charges:,.2f}",
                "total":           f"{paid_amount:,.2f}",  # This matches the paid amount
                "in_words":        in_words
            },

            "payment": {
                "mode":   payment["mode"],
                "amount": f"₹{paid_amount:,.2f}"
            }
        }
    finally:
        try:
            next(db_gen)
        except StopIteration:
            pass

def generate_invoice_pdf(data: Dict[str, Any], add_header: bool = True, add_watermark: bool = True) -> bytes:
    """
    Generate invoice PDF with optional header and watermark overlays.
    """
    # Generate basic PDF from HTML
    html = Template(pdf_format).render(**data)
    pdf_bytes = HTML(string=html).write_pdf()
    
    # Apply overlays if requested
    if add_header or add_watermark:
        pdf_bytes = apply_overlays_to_pdf(pdf_bytes, add_header, add_watermark)
    
    return pdf_bytes

async def generate_invoices_from_payments(
    payments: List[Dict[str, Any]],
    output_dir: str = "static/invoices",
    add_header: bool = True,
    add_watermark: bool = True
) -> None:
    """
    Generate invoices from payment data with optional header and watermark.
    """
    os.makedirs(output_dir, exist_ok=True)
    for pay in payments:
        db = next(get_db())
        details   = build_invoice_details(pay)
        invoice_no = details["invoice_no"]
        pdf_bytes = generate_invoice_pdf(details, add_header, add_watermark)
        signPdf   = await sign_pdf(pdf_bytes)
        order_id  = pay['order_id']
        fn        = f"invoice_{pay['order_id']}.pdf"
        path      = os.path.join(output_dir, fn)
        with open(path, "wb") as f:
            f.write(signPdf)
        print(f"Generated {path}")
        to_addr = pay.get("email")
        subject = f"Your Invoice #{invoice_no}"
        html_body = (
            f"<p>Dear {details['customer']['name']},</p>"
            f"<p>Thank you for your payment of ₹{pay['paid_amount']:.2f}. "
            f"Please find attached your invoice <strong>{invoice_no}</strong>.</p>"
            "<p>Regards,<br/>Pride Trading Consultancy</p>"
        )

        send_mail_by_client_with_file(
            to_email=to_addr,
            subject=subject,
            html_content=html_body,
            pdf_file_path=path
        )

        payment_obj = db.query(Payment).filter(Payment.order_id == order_id).first()
        if payment_obj:
            payment_obj.is_send_invoice = True
            payment_obj.invoice = output_dir
            db.commit()
            db.refresh(payment_obj)

        phone_number  = pay['phone_number']
        employee_code  = pay['employee_code']
        user = db.query(Lead).filter(Lead.mobile == phone_number).first()

        kwargs = {
            "invoice_no": invoice_no,
            "lead_id": user.id,
            "employee_code": employee_code,
            "path": output_dir,
            "order_id": order_id,
        }

        templateInvoice = Invoice(**kwargs)
        db.add(templateInvoice)
        db.commit()
        db.refresh(templateInvoice)
        
