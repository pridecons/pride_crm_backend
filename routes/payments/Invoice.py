from jinja2 import Template
from weasyprint import HTML

# HTML with fixed company info
pdf_format = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Tax Invoice {{ invoice_no }}</title>
  <style>

    .header, .footer {
      text-align: center;
    }
    .header h1 {
      margin: 0;
      font-size: 24px;
    }
    .header p {
      margin: 2px 0;
      font-size: 12px;
    }
    .invoice-meta, .billing, .items, .totals, .payment, .terms {
      margin-top: 20px;
    }
    .invoice-meta table,
    .billing table,
    .items table,
    .totals table,
    .payment table {
      width: 100%;
      border-collapse: collapse;
    }
    .invoice-meta td,
    .billing td,
    .items th,
    .items td,
    .totals td,
    .payment td {
      border: 1px solid #ddd;
      padding: 8px;
      font-size: 12px;
    }
    .items th {
      background: #f5f5f5;
    }
    .items td.center,
    .totals td.right,
    .payment td.right {
      text-align: right;
    }
    .terms p {
      font-size: 11px;
      margin: 4px 0;
    }
    .signature {
      margin-top: 40px;
      text-align: right;
      font-size: 12px;
    }

    .header, .footer { text-align:center }
    .header h1 { margin:0; font-size:24px }
    .header p { margin:2px 0; font-size:12px }
    table { width:100%; border-collapse:collapse; margin-top:20px }
    td, th { border:1px solid #ddd; padding:8px; font-size:12px }
    th { background:#f5f5f5 }
    .right { text-align:right }
    .signature { margin-top:40px; text-align:right; font-size:12px }
 
    
    @page {
  size: A4 portrait;
  margin: 5mm;              /* small margins for more room */
}

html, body {
  width: 210mm;             /* exact A4 width */
  height: 297mm;            /* exact A4 height */
  margin: 0;
  padding: 0;
}

.container {
  /* fill the printable width */
  width: 100%;
  max-width: 200mm;         /* a bit less than 210mm to account for borders */
  padding: 5px;            /* reduce padding */
  border: 1px solid #ccc;
  box-sizing: border-box;
  page-break-inside: avoid; /* don't split container across pages */
}

table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 10px;
  page-break-inside: avoid; /* no breaks inside tables */
}

thead { 
  display: table-header-group; /* repeat header if break—but we’re avoiding breaks */
}

tr, td, th {
  border: 1px solid #ddd;
  padding: 6px;             /* smaller padding */
  font-size: 11px;          /* slightly smaller font */
  page-break-inside: avoid;
}

th {
  background: #f5f5f5;
}

.right {
  text-align: right;
}

.signature {
  margin-top: 20px;         /* reduce space */
  text-align: right;
  font-size: 11px;
}


  </style>
</head>
<body>
  <div class="container">
    <!-- Fixed Company Header -->
    <div class="header">
      <h1>Pride Trading Consultancy Pvt. Ltd.</h1>
      <p>410-411, Serene Centrum Sevasi Road, Vadodara, Gujarat 390021</p>
      <p>Phone: +91 9981919424 | Email: compliance@pridecons.com</p>
      <hr/>
      <h2>Tax Invoice</h2>
      <p><strong>Original for Recipient</strong></p>
    </div>

    <!-- Invoice Metadata -->
    <table>
      <tr>
        <td><strong>Invoice No:</strong> {{ invoice_no }}</td>
        <td><strong>Date:</strong> {{ invoice_date }}</td>
      </tr>
      <tr>
        <td><strong>Reverse Charge:</strong> {{ reverse_charge }}</td>
        <td><strong>State:</strong> {{ state }} (Code {{ state_code }})</td>
      </tr>
    </table>

    <!-- Customer Details -->
    <h3>Bill To:</h3>
    <table>
      <tr>
        <td><strong>Name:</strong> {{ customer.name }}</td>
        <td><strong>Mobile:</strong> {{ customer.mobile }}</td>
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
        <td><strong>GSTIN:</strong> {{ customer.gstin }} | <strong>State:</strong> {{ customer.state }} (Code {{ customer.state_code }})</td>
      </tr>
    </table>

    <!-- Items -->
    <h3>Details of Services</h3>
    <table>
      <thead>
        <tr>
          <th>S. No.</th><th>SAC Code</th><th>Description</th>
          <th>Pack</th><th>Start On</th><th>End On</th><th class="right">Rate (₹)</th>
        </tr>
      </thead>
      <tbody>
      {% for item in items %}
        <tr>
          <td>{{ loop.index }}</td>
          <td>{{ item.sac }}</td>
          <td>{{ item.desc }}</td>
          <td>{{ item.pack }}</td>
          <td>{{ item.start }}</td>
          <td>{{ item.end }}</td>
          <td class="right">{{ item.rate }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>

    <!-- Totals -->
    <table>
      <tr><td>Service Charges</td><td class="right">{{ totals.service_charges }}</td></tr>
      <tr><td>CGST</td><td class="right">{{ totals.cgst }}</td></tr>
      <tr><td>SGST</td><td class="right">{{ totals.sgst }}</td></tr>
      <tr><td>Transaction Charges</td><td class="right">{{ totals.txn_charges }}</td></tr>
      <tr><td><strong>Total</strong></td><td class="right"><strong>{{ totals.total }}</strong></td></tr>
    </table>
    <p><em>Amount in Words:</em> {{ totals.in_words }}</p>

    <!-- Payment Details -->
    <h3>Payment Details</h3>
    <table>
      <tr><td>Mode</td><td>{{ payment.mode }}</td></tr>
      <tr><td>Amount Paid</td><td class="right">{{ payment.amount }}</td></tr>
    </table>

    <!-- Terms -->
    <div class="terms">
      <h3>Terms &amp; Conditions</h3>
      <p>1. This is a computer-generated invoice; no signature or stamp is required.</p>
      <p>2. Investment/trading in the market is subject to market risk.</p>
      <p>3. Complimentary services are non-refundable.</p>
      <p>4. Any disputes shall be subject to Vadodara jurisdiction, Gujarat.</p>
      <p>5. Payment confirms full consent to the services rendered.</p>
    </div>

    <div class="signature">
      <p>Authorized Signatory</p>
      <p><strong>Pride Trading Consultancy Pvt. Ltd.</strong></p>
    </div>
  </div>
</body>
</html>
"""

def generate_invoice_pdf(data: dict) -> bytes:
    """
    data must include:
      invoice_no, invoice_date, reverse_charge,
      state, state_code,
      customer: {name, mobile, address, email, pan, aadhaar, gstin, state, state_code},
      items: list of {sac, desc, pack, start, end, rate},
      totals: {service_charges, cgst, sgst, txn_charges, total, in_words},
      payment: {mode, amount},
      terms: list of strings.
    Returns PDF bytes.
    """
    html = Template(pdf_format).render(**data)
    pdf_bytes = HTML(string=html).write_pdf()
    return pdf_bytes


details = {
  "invoice_no": "INV22567 EmpCode-1",
  "invoice_date": "12-Jul-2025",
  "reverse_charge": "N",
  "customer": {
    "name": "Mr. Sandeep Mahobia",
    "mobile": "9131463008",
    "address": "323/4, Khamaria … Jabalpur – 482005",
    "email": "sndpmahobia@gmail.com",
    "pan": "BGSPM4609L",
    "aadhaar": "797263542244",
    "gstin": "URP",
    "state": "Madhya Pradesh", "state_code": "23"
  },
  "items": [{
    "sac": "997156",
    "desc": "Optimistic Whale (P)",
    "pack": "Monthly",
    "start": "13-Jul-2025",
    "end": "29-Jul-2025",
    "rate": "15,000"
  }],
  "totals": {
    "service_charges": "8,475",
    "cgst": "763",
    "sgst": "763",
    "txn_charges": "0",
    "total": "10,000",
    "in_words": "Rs. Ten Thousand only"
  },
  "payment": {
    "mode": "GPay",
    "amount": "₹10,000"
  }
}

pdf_data = generate_invoice_pdf(details)
with open("invoice.pdf", "wb") as f:
    f.write(pdf_data)
