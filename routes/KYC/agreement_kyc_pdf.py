from fastapi import APIRouter,Depends, HTTPException
import httpx
from weasyprint import HTML
from PyPDF2 import PdfReader, PdfWriter
from io import BytesIO
import base64
import os
from sqlalchemy.orm import Session
from db.connection import get_db
import asyncio
from config import PAN_API_ID, PAN_API_KEY

from reportlab.pdfgen import canvas
from reportlab.pdfgen import canvas as rl_canvas
import tempfile
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import signers, PdfSignatureMetadata
from pyhanko.sign.fields import SigFieldSpec

from db.models import Lead

from typing import Any, Dict, Optional
from config import PAN_API_ID, PAN_API_KEY

router = APIRouter(tags=["Agreement KYC"])

async def request_with_retry(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    json: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    retries: int = 3,
    backoff_factor: float = 0.5,
) -> Any:
    """
    Generic HTTP request with automatic retry on failures.

    - retries: कुल कितनी बार कोशिश करनी है (default 3)
    - backoff_factor: पहले retry से पहले कितनी देर रुके (seconds), फिर doubling होगी
    """
    last_exc: Optional[Exception] = None

    async with httpx.AsyncClient() as client:
        for attempt in range(1, retries + 1):
            try:
                response = await client.request(
                    method, url, headers=headers, json=json, params=params
                )
                # status 4xx/5xx के लिए exception
                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                # अगर client-side error (4xx), तो retry नहीं करना
                if 400 <= status < 500:
                    raise HTTPException(
                        status_code=status,
                        detail=f"API returned client error {status}: {exc.response.text}"
                    )
                last_exc = exc

            except (httpx.ReadError, httpx.RequestError) as exc:
                # network या timeout error
                last_exc = exc

            # अभी तक success नहीं हुआ, तो retry करने से पहले wait करें
            if attempt < retries:
                wait_time = backoff_factor * (2 ** (attempt - 1))
                await asyncio.sleep(wait_time)

    # सारे प्रयास fail हुए
    raise HTTPException(
        status_code=500,
        detail=f"API request failed after {retries} attempts: {last_exc}"
    )


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
                    box=(340, 630, 490, 570)
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

def create_header_overlay(page_width: float, page_height: float, pride_logo_path: str, cin: str, mail: str, call: str):
    """
    Create an overlay PDF page containing the header.
    - Top left: pride logo
    - Top right: CIN, email, and call details (one per line)
    """
    packet = BytesIO()
    c = canvas.Canvas(packet, pagesize=(page_width, page_height))
    
    # Draw the pride logo on the top left
    # Adjust logo dimensions as needed
    logo_width = 140  
    logo_height = 40  
    # Position: 40 pts from left, 20 pts from top (adjusting for logo height)
    c.drawImage(pride_logo_path, 40, page_height - logo_height - 20, width=logo_width, height=logo_height)
    
    # Draw the CIN, email, and call details on the top right
    header_details = [cin, mail, call]
    c.setFont("Helvetica", 10)
    margin = 40  # margin from right edge
    line_height = 12  # vertical space between lines
    
    # Start from the top with some padding (20 pts from the top)
    text_y = page_height - 20 - line_height
    for line in header_details:
        # text_width = c.stringWidth(line, "Helvetica", 10)
        c.drawString(page_width - 160 - margin, text_y, line)
        text_y -= line_height
    c.save()
    packet.seek(0)
    return PdfReader(packet).pages[0]

def create_footer_overlay(page_width: float, page_height: float, page_num: int):
    """
    Create an overlay PDF page containing the footer.
    - Left bottom: page number ("Page X")
    - Right bottom: fixed footer text
    """
    packet = BytesIO()
    c = canvas.Canvas(packet, pagesize=(page_width, page_height))
    c.setFont("Helvetica", 10)
    
    # Draw the page number at bottom left (40 points from left, 20 points from bottom)
    c.drawString(40, 20, f"Page {page_num}")
    
    # Draw the footer text at bottom right
    footer_text = "©Service Agreement of Pride Trading Consultancy Pvt. Ltd."
    text_width = c.stringWidth(footer_text, "Helvetica", 10)
    c.drawString(page_width - text_width - 40, 20, footer_text)
    
    c.save()
    packet.seek(0)
    # Return the first (and only) page of the generated overlay PDF
    return PdfReader(packet).pages[0]

def create_watermark_overlay(page_width: float, page_height: float, text: str):
    buffer = BytesIO()
    c = rl_canvas.Canvas(buffer, pagesize=(page_width, page_height))
    c.setFont("Helvetica-Bold", 38)
    c.setFillColorRGB(0.8, 0.8, 0.8, alpha=0.2)  # light gray with some transparency

    # Save the current state before rotating
    c.saveState()
    
    # Rotate and translate (this centers the text)
    c.translate(page_width / 2, page_height / 2)
    c.rotate(45)  # 270 degrees rotation
    
    # Draw the watermark centered
    c.drawCentredString(0, 0, text)

    c.restoreState()
    c.save()
    buffer.seek(0)

    return PdfReader(buffer).pages[0]

async def generate_kyc_pdf(data,mobile:str,db:Session = Depends(get_db)):
    kyc_user = db.query(Lead).filter(Lead.mobile == mobile).first()
    
    father_row = f"<tr><td>Father Name</td><td>{kyc_user.father_name}</td></tr>" if kyc_user.father_name else ""
    director_row = f"<tr><td>Director Name / Proprietor</td><td>{kyc_user.director_name}</td></tr>" if kyc_user.director_name else ""
    gst_row = f"<tr><td>GST NO.</td><td>{kyc_user.gstin}</td></tr>" if kyc_user.gstin else ""
    aadhaar_row = f"<tr><td>Aadhaar No.</td><td>{kyc_user.aadhaar}</td></tr>" if kyc_user.aadhaar else ""
    gender_row = f"<tr><td>Gender</td><td>{kyc_user.gender}</td></tr>" if kyc_user.gender else ""
    marital_row = f"<tr><td>Marital Status</td><td>{kyc_user.marital_status}</td></tr>" if kyc_user.marital_status else ""
    occupation_row = f"<tr><td>Occupation</td><td>{kyc_user.occupation}</td></tr>" if kyc_user.occupation else ""
    so = f"S/O" if kyc_user.father_name else "Director Name / Proprietor"
    so_name = f"{kyc_user.father_name}" if kyc_user.father_name else f"{kyc_user.director_name}"


    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <style>
        @page {{
            margin-top: 100px;
            }}
          body {{
          font-family: "Times New Roman", serif;
            background: #f0f0f0;
            margin: 0;
          }}
          .container {{
            background: #fff;
          }}
          h2,
          h3 {{
            text-align: center;
            margin-top: 20px;
            margin-bottom: 10px;
          }}
          h2 {{
            padding-bottom: 5px;
          }}
          p {{
            text-align: justify;
            line-height: 1.6;
            margin: 10px 0;
          }}
          table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 20px;
          }}
          table,
          th,
          td {{
            border: 1px solid #000;
          }}
          th,
          td {{
            padding: 8px;
            text-align: center;
          }}
          .signature-container {{
            display: flex;
            justify-content: space-between;
            margin-top: 40px;
          }}
          .signature-box {{
            width: 45%;
            text-align: center;
          }}
          .signature-box .sig-area {{
            width: 150px;
            height: 100px;
            # border: 1px solid #ccc;
            margin: 0 auto 20px auto;
          }}
          a {{
            color: #0000FF;
          }}
          @media print {{
            body {{
              background: none;
            }}
            .container {{
              box-shadow: none;
            }}
          }}
            h2 {{
                color: #333;
            }}
            h3 {{
                margin-bottom: 5px;
                color: #555;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 20px;
            }}
            table, th, td {{
                border: 1px solid #000;
            }}
            th, td {{
                padding: 8px;
                text-align: left;
                vertical-align: top;
            }}
            .light-gray {{
                background-color: #f2f2f2;
            }}
            
        </style>
      </head>
      <body>
        <div class="container">
          <h2 style="text-align:center;">A. Know Your Customer</h2>
          <div style="display:flex;">
            <table style="width:85%">
                <tr class="light-gray">
                    <td>Client Name</td>
                    <td >{kyc_user.full_name}</td>
                </tr>
                {father_row}
                {director_row}
                {gst_row}
                <tr><td>DOB</td><td >{kyc_user.dob}</td></tr>
                <tr><td>Nationality</td><td  >{kyc_user.nationality}</td></tr>
                <tr><td>PAN No.</td><td >{kyc_user.pan}</td></tr>
                {aadhaar_row}
                {gender_row}
                {marital_row}
                {occupation_row}
            </table>
        </div>

        <h2 style="text-align:center;">Contact Details</h2>
        <table>
            <tr class="light-gray"><td>Contact No.</td><td>{kyc_user.mobile}</td></tr>
            <tr><td>Alternate No.</td><td>{kyc_user.alternate_mobile}</td></tr>
            <tr><td>Email</td><td>{kyc_user.email}</td></tr>
        </table>

        <h2 style="text-align:center;">Address Details</h2>
        <table>
            <tr class="light-gray"><td>Address</td><td>{kyc_user.address}</td></tr>
            <tr><td>City</td><td>{kyc_user.city}</td></tr>
            <tr><td>State</td><td>{kyc_user.state}</td></tr>
            <tr><td>Pin Code</td><td>{kyc_user.pincode}</td></tr>
        </table>

          <h2 style="text-align:center; page-break-before: always; break-before: page;" >B. RESEARCH SERVICE AGREEMENT</h2>
          <p>
            This Research Services Agreement is made on 26th day of March 2025
            (date) between Pride Trading Consultancy Private Limited, which is a
            SEBI registered Research Analyst having registration number INH000010362
            and having its registered office at 410-411 Serene Centrum Sevasi Road
            Gotri Vadodara Gujarat 390021 hereinafter called the Research Analyst.
          </p>
          <h2>AND</h2>
          <p>
            {kyc_user.full_name}, {so}, {so_name}, having its residence at {kyc_user.address}, hereinafter called the Client.
          </p>
          <p>
            That the expression of the term, Research Analyst and Client shall mean
            and include their legal heirs, successors, assigns and representatives,
            etc.
          </p>
          <p>
            WHEREAS Research Analyst is been authorised by SEBI to provide research
            recommendations in terms of SEBI (Research Analysts) Regulations, 2014.
          </p>
          <p>
            AND WHEREAS Client is desirous of availing the research services from
            the Research Analyst on the terms & conditions as described hereinafter.
          </p>
          <p>
            NOW, THEREFORE, in consideration of the mutual covenants contained in
            this agreement, the parties hereby agree as follows:
          </p>
          <p>
            (A) In accordance with the applicable laws, client hereby appoints,
            entirely at his/her/its risk, Pride Trading Consultancy Private Limited
            to provide research recommendations in accordance with the terms and
            conditions of the agreement.
          </p>
          <p>
            (B) Recommendations services provided by the Research Analyst to the
            client and the client has read and understood the terms and conditions
            of Research analyst along with the fee structure and mechanism for
            charging and payment of fee.
          </p>
          <p>
            (C) Research Analyst does not manage funds and securities on behalf of
            the client and that it shall only receive such sums of monies from the
            client as are necessary to discharge the client’s liability towards fees
            owed to the Research Analyst.
          </p>
          <p>
            (D) Research Analyst does not, in the course of performing its services
            to the client, holds out any research services implying any assured
            returns or minimum returns or target return or percentage accuracy or
            service provision till achievement of target returns or any other
            nomenclature that gives the impression to the client that the research
            recommendation provided is risk-free and/or not susceptible to market
            risks and/or that it can generate returns with any level of assurance.
          </p>
          <p>
            (E) In consideration for the services to be rendered by Research
            Analyst, the Client agrees to pay to Research Analyst service
            charges/fees and the Research Analyst shall issue Invoices against the
            fees as and when received which shall contain details such as tenure,
            type of service and amount of fees charged which will be subjected to
            this agreement. This agreement will be binding on both the parties until
            it is specifically amended for all the transactions between the parties
            and all the invoices issued.
          </p>
          <p>
            (F) The payment of fees shall be through any mode which shows
            traceability of funds. Such modes may include account payee crossed
            cheque/ Demand Drafts or by way of direct credit to the bank accounts
            through NEFT/ RTGS/ IMPS/ UPI or any other mode specified by SEBI from
            time to time. However, the fees shall not be in cash.
          </p>
          <p>
            (G) The Research Analyst agrees to provide services to the client as
            mentioned below:
            <br />
            • Research recommendations on the fee-based model.
            <br />
            • The subject matter of recommendations will be related to the equity
            market or commodity market.
            <br />
            • Sending updates to the client regarding recommended stocks, whenever
            Research Analyst thinks necessary/required.
          </p>
          <p>8. Functions of the Research Analyst:</p>
          <p>
            8.1 Research Analyst shall provide research recommendation Services to
            the Client during the term of this Agreement as permitted under
            applicable laws and regulations governing Research Analyst. The services
            rendered by the Research Analyst are non-binding and non-recourse in
            nature and the final decision on the type of instruments; the proportion
            of exposure and tenure of the investments shall be taken by the Client
            at its discretion.
          </p>
          <p>
            8.2 Research Analyst shall be in compliance with the SEBI (Research
            Analysts) Regulations, 2014 and its amendments, rules, circulars and
            notifications.
          </p>
          <p>
            8.3 Research Analyst shall be in compliance with the eligibility
            criteria as specified under the SEBI Regulations at all times.
          </p>
          <p>
            8.4 Research Analyst shall get annual compliance audit conducted as per
            the SEBI (Research Analysts) Regulations, 2014.
          </p>
          <p>
            8.5 Research Analyst undertakes to abide by the Code of Conduct as
            specified in the Third Schedule of the SEBI (Research Analysts)
            Regulations, 2014. Research Analyst shall not receive any consideration
            in any form if the client desires to avail the services of intermediary
            recommended by Research Analyst.
          </p>
          <p>9. Objective and guidelines:</p>
          <p>
            Research Analyst would provide recommendations in listed Equity Shares
            (Large cap/ Mid-Cap/ Small Cap). Further, Client expressly understands
            and agrees that Research Analyst is not qualified to, and does not
            purport to provide, any legal, accounting, estate, actuary, investment
            or tax advice or to prepare any legal, accounting or tax documents.
            Nothing in this Agreement shall be construed as providing for such
            services. Client will rely on his or her tax attorney or accountant for
            tax advice or tax preparation.
          </p>
          <p>10. Liability of Research Analyst.</p>
          <p>
            Except as otherwise provided by law, Research Analyst or its officers,
            Directors, employees or affiliates will not be liable to Client for any
            loss that:
          </p>
          <p>
            a. Client may suffer by reason of any depletion in the value of the
            assets, which may result by reason of fluctuation in asset value, or by
            reason of non-performance or under-performance of the securities/funds
            or any other market conditions;
          </p>
          <p>
            b. Client may suffer as a result of Research Analyst’s recommendations
            or other action taken or omitted in good faith and with the degree of
            care, skill, prudence and diligence that a prudent person acting in a
            similar fiduciary capacity would use in conducting an enterprise of a
            similar nature and with similar objectives under the circumstances;
          </p>
          <p>c. Caused by following Client’s written or oral instructions;</p>
          <p>11. Adherence to grievance redressal timelines</p>
          <p>
            Research Analyst shall be responsible to resolve the grievances within
            the timelines specified under SEBI circulars. In case of any query or
            grievance, client shall contact through the following medium:
          </p>
          <p>Tel No.: 81410-54547 | Mail id: compliance@pridecons.com</p>
          <p>12. Means of communication</p>
          <p>
            The Research Analyst will render its recommendations by SMS. Client
            shall only accept such recommendations provided to him/her by SMS.
            Research Analyst shall not be liable if the client accepts
            recommendations provided by any other means. Further, the client shall
            acknowledge any communication via mail through
            compliance@Prideresearch.com or the Prideresearch.com domain only.
            Research Analyst will not be liable for any email received from any
            other domain.
          </p>
          <p>13. Terms & Conditions</p>
          <p>A. Expectations from the investors (Responsibilities of investors)</p>
          <p>
            <strong>Do’s</strong>
          </p>
          <p>
            ● Always deal with SEBI registered Research Analyst.
            <br />
            ● Ensure that the Research Analyst has a valid registration certificate.
            <br />
            ● Check for SEBI registration number.
            <br />
            ● Please refer to the list of all SEBI registered Research Analysts
            available on the SEBI website at the following link:
            <a
              href="https://www.sebi.gov.in/sebiweb/other/OtherAction.do?doRecognisedFpi=yes&intmId=14"
              target="_blank"
              >SEBI Registered Analysts</a
            >.
            <br />
            ● Always pay attention to disclosures made in the research reports
            before investing.
            <br />
            ● Pay your Research Analyst through banking channels only and maintain
            duly signed receipts mentioning the details of your payments.
            <br />
            ● Before buying securities or applying in public offers, check the
            research recommendation provided by your Research Analyst.
            <br />
            ● Ask all relevant questions and clear your doubts with your Research
            Analyst before acting on the recommendation.
            <br />
            ● Inform SEBI if any Research Analyst offers assured or guaranteed
            returns.
            <br />
            ● Do not make any payments into personal accounts of any employee or
            Analyst. All payments shall be made only in authorized bank accounts.
          </p>
          <p>
            <strong>Don’ts</strong>
          </p>
          <p>
            ● Do not provide funds for investment to the Research Analyst.
            <br />
            ● Don’t fall prey to luring advertisements or market rumors.
            <br />
            ● Do not get attracted to limited period discount or other incentive,
            gifts, etc. offered by Research Analyst, if any such services or offers
            are made bring it to the notice of the company immediately within 48
            hours by email at compliance@pridecons.com
            <br />
            ● Don’t take decisions just because of repeated messages and calls by
            Research Analyst.
            <br />
            ● Trade only on recommendation provided through companies authorised
            communication channels DO NOT TRADE ON ANY CALL PROVIDED OVER TELEPHONIC
            CONVERSATION BY ANY EMPLOYEE, IF ANY SUCH ACTIVITY IS DONE BRING IT
            IMMEDIATELY TO COMPANIES NOTICE WITHIN 48 HOURS OF SUCH ACTIVITY BY
            EMAIL AT compliance@pridecons.com, if client trades on any personal
            recommendation without bringing it to companies notice the company will
            hold no liability of any profits or losses arising out of such trades.
            <br />
            ● Don’t rush into making investments that do not match your risk taking
            appetite and investment goals.
            <br />
            ● Do not share login credential and password of your trading and demat
            accounts with the Research Analyst.
          </p>
          <p>B. Refund Policy</p>
          <p>
            We value our customers and are committed to providing best services. Our
            clients need to realise that we do not offer a 100% guarantee on our
            calls and hence cannot offer any refund on subscriptions regardless of
            the individual client’s performance. Once a service has been subscribed
            to and a payment has been made for the same, it can’t be canceled or
            refunded. If for some unforeseen reason, the client is not satisfied
            with our services, they may call us to seek direction on future calls.
            We will give our best effort to increase the satisfaction levels in such
            cases. In exceptional cases if a refund has to be considered it will
            strictly be made only according to the following policy:
          </p>
          <p>
            This Agreement may be terminated under the following circumstances,
            namely a. Voluntary / mandatory termination by the Research analyst
            after giving 30 days written notice however the refund amount will be
            reduced by service active period, notice period time of 30 days and all
            deducted applicable taxes on the full amount.
          </p>
          <p>
            b. Voluntary / mandatory termination by the client after giving 30 days
            written notice however the refund amount will be reduced by service
            active period plus the amount due for the corresponding quarter in which
            such termination has taken place plus notice period time of 30 days and
            all deducted applicable taxes on the full amount.
          </p>
          <p>
            c. Suspension/Cancellation of registration of Research Analyst by SEBI
            however the refund amount will be reduced by service active period, plus
            the amount due for the corresponding quarter in which such termination
            has taken place plus notice period time of 30 days and all deducted
            applicable taxes on the full amount.
          </p>
          <p>
            d. Any other action taken by other regulatory body/ Government authority
            however the refund amount will be reduced by service active period, plus
            the amount due for the corresponding quarter in which such termination
            has taken place plus notice period time of 30 days and all deducted
            applicable taxes on the full amount.
          </p>
          <p>
            e. The client shall not be entitled for any service after the completion
            of the notice period of 30 days, within which the client will be
            required to either liquidate all positions or take charge on his own.
          </p>
          <p>
            We strongly recommend that before making a payment, our visitors and
            potential clients, please:
          </p>
          <p>
            • Read all information about our services and support given to our
            clients.
            <br />
            • Read our Terms and Conditions.
            <br />
            • Read our Privacy Policy and Refund Policy.
            <br />
            • There is no refund possible in any case whatsoever.
          </p>
          <p>C. Privacy Policy</p>
          <p>
            We at Pride Trading Consultancy Pvt. Ltd. understand the confidentiality
            of your personal information and maintain it forever. We understand that
            the information which you have given us is to be kept private and
            confidential, and we keep up the promise that we will safeguard the
            information of our clients whether old or new. The information like your
            name, mobile no, email id, address etc are required for the company as
            well as the client as it helps in better communication of the services.
            Following policy has been implemented for safeguarding the information.
            For more details kindly visit our website
            <a href="https://pridecons.com" target="_blank">pridecons.com</a>
            Kindly make the payment after reading all terms and conditions,
            disclaimers and refund policy.
          </p>
          <p>14. Disclosure</p>
          <p>
            The particulars given in this Disclosure Document have been prepared in
            accordance with SEBI (Research Analyst) Regulations, 2014.
          </p>
          <p>
            The purpose of the Document is to provide essential information about
            the Research and recommendation Services in a manner to assist and
            enable the perspective client/client in making an informed decision for
            engaging in Research and recommendation services before investing.
          </p>
          <p>
            For the purpose of this Disclosure Document, Research Analyst of Pride
            Research Analyst, (hereinafter referred as “Research Analyst”)
          </p>
          <p>
            • Descriptions about “Research Analyst”
            <br />
            • History, present business, and background
          </p>
          <p>
            Research Analyst is registered with SEBI as a Research Analyst with
            Registration No. INH000010362.
          </p>
          <p>
            For more details, kindly visit our website
            <a href="https://pridecons.com" target="_blank">pridecons.com</a>
          </p>
          <p>15. Disclaimer</p>
          <p>
            We do not receive any consideration by way of remuneration or
            compensation or in any other form whatsoever, by us or any of our
            associates or subsidiaries for any distribution or execution services in
            respect of the products or securities for which the Research advice is
            provided to the client. Investment in stock or commodity markets is
            subject to market risk, though best attempts are made for predicting
            markets, but no surety of return or accuracy of any kind is guaranteed,
            while the performance sheet of various products is available but should
            not be considered as a guarantee for future performance of the
            products/services. Clients are advised to consider all the advice as
            just an opinion and make investment decision on their own.
          </p>
          <p>
            Research Analyst does not, in the course of performing its services to
            the client, holds out any Research recommendation implying any assured
            returns or minimum returns or target return or percentage accuracy or
            service provision till achievement of target returns or any other
            nomenclature that gives the impression to the client that the research
            recommendation is risk- free and/or not susceptible to market risks and
            or that it can generate returns with any level of assurance.
          </p>
          <p>
            For more details, kindly visit our website
            <a href="https://pridecons.com" target="_blank">pridecons.com</a>
          </p>
          <p>16. General Risk Factor</p>
          <p>
            The Client hereby agrees to undertake the risks pertaining to the
            investments as stated herein or an indicative list of the risks
            associated with investing:
            <br />
            a) Investment in equities, derivatives, mutual funds and Exchange Traded
            Index are subject to market risks and there is no assurance or guarantee
            that the objective of the Investment Strategy will be achieved.
            <br />
            b) Past performance of the Research Analyst does not indicate the future
            performance. Investors are not being offered any guaranteed returns.
            <br />
            c) Client may note that Research Analyst’s recommendations may not be
            always profitable, as actual market movements may be at variance with
            anticipated trends.
            <br />
            d) The Research Analyst is neither responsible nor liable for any losses
            resulting from its research services.
            <br />
            e) The names of the products/nature of investments do not in any manner
            indicate their prospects or returns. The performance of equity related
            Research strategies may be adversely affected by the performance of
            individual companies, changes in the market place and industry specific
            and macro-economic factors.
            <br />
            f) Price/Volatility Risk: Equity market can show large fluctuations in
            price, even in short period of time. Investors should be aware of this
            and only invest in equity or equity related products if their
            investments horizon is long enough to support these important price
            movements.
            <br />
            g) Clients are not being offered any guaranteed/assured returns
            <br />
            h) The value of asset may increase or decrease depending upon various
            market forces affecting the capital markets such as de- listing
            securities ,market closure,etc. Consequently we make no assurance of ant
            guaranteed returns.
            <br />
            i) Not following the recommendations or allocation may impact the
            profitability of the portfolio.
            <br />
            j) System/Network/Technical congestion: Recommendation communicated via
            electronic modes i.e. via SMS or client portals exits a possibility of
            delivery failure, which may be beyond our control.
            <br />
            k) Changes in Applicable Law may impact the performance of the
            Portfolio.
          </p>
          <p>17. Miscellaneous</p>
          <p>
            Each party agrees to perform such further actions and execute such
            further agreements as are necessary to effectuate the purposes hereof.
          </p>
          <p>
            IN WITNESS WHEREOF, the parties hereto have executed the Agreement on
            the date(s) set forth below, and the Agreement is effective on the date
            of acceptance by the Research Analyst.
          </p>
          <h2>Most Important Terms and Conditions (MITC)</h2>
          <p>
            1. These terms and conditions, and consent thereon are for the research
            services provided by the Research Analyst (RA) and RA cannot
            execute/carry out any trade (purchase/sell transaction) on behalf of the
            client. Thus, the clients are advised not to permit RA to execute any
            trade on their behalf.
          </p>
          <p>
            2. The fee charged by RA to the client will be subject to the maximum of
            amount prescribed by SEBI/ Research Analyst Administration and
            Supervisory Body (RAASB) from time to time (applicable only for
            Individual and HUF Clients).
          </p>
          <p>
            ● 2.1. The current fee limit is Rs 1,51,000/- per annum per family of
            client for all research services of the RA.
          </p>
          <p>● 2.2. The fee limit does not include statutory charges.</p>
          <p>
            ● 2.3. The fee limits do not apply to a non-individual client /
            accredited investor.
          </p>
          <p>
            3. RA may charge fees in advance if agreed by the client. Such advance
            shall not exceed the period stipulated by SEBI; presently it is one
            quarter. In case of pre-mature termination of the RA services by either
            the client or the RA, the client shall be entitled to seek refund of
            proportionate fees only for unexpired period.
          </p>
          <p>
            4. Fees to RA may be paid by the client through any of the specified
            modes like cheque, online bank transfer, UPI, etc. Cash payment is not
            allowed. Optionally the client can make payments through Centralized Fee
            Collection Mechanism (CeFCoM) managed by BSE Limited (i.e. currently
            recognized RAASB).
          </p>
          <p>
            5. The RA is required to abide by the applicable regulations/ circulars/
            directions specified by SEBI and RAASB from time to time in relation to
            disclosure and mitigation of any actual or potential conflict of
            interest. The RA will endeavor to promptly inform the client of any
            conflict of interest that may affect the services being rendered to the
            client.
          </p>
          <p>
            6. Any assured/guaranteed/fixed returns schemes or any other schemes of
            similar nature are prohibited by law. No scheme of this nature shall be
            offered to the client by the RA.
          </p>
          <p>
            7. The RA cannot guarantee returns, profits, accuracy, or risk-free
            investments from the use of the RA’s research services. All opinions,
            projections, estimates of the RA are based on the analysis of available
            data under certain assumptions as of the date of preparation/publication
            of research report.
          </p>
          <p>
            8. Any investment made based on recommendations in research reports are
            subject to market risks, and recommendations do not provide any
            assurance of returns. There is no recourse to claim any losses incurred
            on the investments made based on the recommendations in the research
            report. Any reliance placed on the research report provided by the RA
            shall be as per the client’s own judgment and assessment of the
            conclusions contained in the research report.
          </p>
          <p>
            9. The SEBI registration, Enlistment with RAASB, and NISM certification
            do not guarantee the performance of the RA or assure any returns to the
            client.
          </p>
          <h2>10. For any grievances, follow the steps below:</h2>
          <h3>Step 1: Contact the RA using the details below:</h3>
          <table>
            <tr>
              <th>Designation</th>
              <th>Contact Person Name</th>
              <th>Address</th>
              <th>Contact No.</th>
              <th>Email-ID</th>
              <th>Working Hours</th>
            </tr>
            <tr>
              <td>Customer Care</td>
              <td>Ms. Anjali</td>
              <td>Vadodara, Gujarat</td>
              <td>+91-9981919424</td>
              <td>compliance@pridecons.com</td>
              <td>Mon-Fri 10 AM – 05 PM</td>
            </tr>
            <tr>
              <td>Compliance Officer</td>
              <td>Mr. Ajay Kumar</td>
              <td>Vadodara, Gujarat</td>
              <td>+91-9981919424</td>
              <td>compliance@pridecons.com</td>
              <td>Mon-Fri 10 AM – 05 PM</td>
            </tr>
            <tr>
              <td>Principal Officer</td>
              <td>Ms. Apeksha Bansal</td>
              <td>Vadodara, Gujarat</td>
              <td>+91-9981919424</td>
              <td>info.prideconsultancy@gmail.com</td>
              <td>Mon-Fri 09 AM – 05 PM</td>
            </tr>
          </table>
          <p>
            Step 2: If the resolution is unsatisfactory, the client can also lodge
            grievances through SEBI’s SCORES platform at
            <a href="http://www.scores.sebi.gov.in" style="text-decoration: none;" target="_blank"
              >www.scores.sebi.gov.in</a
            >
          </p>
          <p>
            Step 3: The client may also consider the Online Dispute Resolution (ODR)
            through the Smart ODR portal at
            <a href="https://smartodr.in" style="text-decoration: none;" target="_blank">https://smartodr.in</a>
          </p>
          <p>
            11. Clients are required to keep contact details, including email ID and
            mobile number/s updated with the RA at all times.
          </p>
          <p>
            12. The RA shall never ask for the client’s login credentials and OTPs
            for the client’s Trading Account, Demat Account, and Bank Account. Never
            share such information with anyone including the RA.
          </p>
          
          <h2 style="text-align: center;">Details of Services</h2>
          <div class="service-details">
            <p>
              "Pride Trading Consultancy Private Limited." is a Research Analyst
              having a team consisting of highly qualified analysts who are skilled
              and impeccable in their analysis. These analysts, using their
              experience and latest software tools, are able to predict movements in
              the share market on time with high accuracy. As a result, using our
              tips, We provide recommendations for Stocks – Cash and F&amp;O traded
              in NSE &amp; Commodities including Bullions, Metals, Energy, and
              Agro-commodities traded in MCX, NCDEX.
            </p>
            <p>
              We also provide daily and weekly reports having overview of commodity
              market which helps the investors understand the trends of the market
              and aids in taking wise decisions. Always trade in the calls given
              only through SMS. It is mandatory to trade in all the provided calls
              and always trade as per the level provided in the call. Always trade
              with equal investment in all the call. Always trade with uniform
              number of lots in all the calls – for example, if you are trading in
              the Derivative Market (Futures, Options, &amp; Commodity), then each
              call can be with the same quantity. Initially, for at least one month
              you should trade with 1 lot &amp; then increase the number of lots as
              per your investment and risk taking capacity.
            </p>
            <p>
              Please keep enough space in your message inbox to receive trading
              messages on time. Always maintain stop-loss (SL) while trading in all
              calls even if anyone asks to eradicate SL. Avoid trading without
              stop-loss. Keep booking partial profits at 1st and 2nd target as
              messages received from research team. Revise your SL once you start
              booking profit as per company's follow up message. Do not enter in the
              trade if prices are significantly higher than the given price; please
              call us for assistance.
            </p>
            <p>
              Also, the medium of our services is only SMS. Thus, please do trade
              only on SMS provided by Pride Trading Consultancy – Research Analyst.
              Please do not trade on verbal calls. Telephonic support provided, if
              any, will only be to confirm the calls/tips provided through SMS. No
              separate calls/tips are provided through telephone. We provide advice
              only through our registered SMS Channel. Kindly insist on SMS or
              Messenger services from your business analyst. DO NOT Trade on
              Telephonic calls.
            </p>
            <p>
              Also, we would request you to read our Refund Policy, Disclaimer,
              Disclosures, Terms &amp; Conditions etc. mentioned on our website
              www.pridecons.com before proceeding for the services, as further
              company will not be responsible for any confusion or inconvenience
              caused to client. Pride Trading Consultancy Private Limited. provides
              only advisory services NOT any Brokerage or Demat. By taking our
              services you are agreeing that you will get our SMS and Telephone call
              on your DND numbers too.
            </p>
            <p>
              *Investment in market is subject to market risk. <br />
              *Accuracy mentioned is as per past record and may vary as per market
              conditions. <br />
              *Please read all disclaimer, disclosure, and terms &amp; conditions
              prior to subscribing to services.
            </p>
          </div>
          <div class="signature-container">
            <!-- Client Signature -->
            <div class="signature-box">
              <p style="font-weight: bold; margin-bottom: 10px">
                Client Signature:
              </p>
              <div class="sig-area"></div>
              <p style="font-weight: bold">Date: {data.get("date")}</p>
            </div>
            <!-- Research Analyst Signature -->
            <div class="signature-box">
              <p style="font-weight: bold; margin-bottom: 10px">
                Research Analyst (Principal Officer):
              </p>
              <div class="sig-area"></div>
              <p style="font-weight: bold">Date: {data.get("date")}</p>
            </div>
          </div>
        </div>
        </div>
      </body>
    </html>
"""

    # watermark = "routes/KYC_Verification/pride.cdr"
    # Convert the HTML to PDF using WeasyPrint
    pdf_bytes = HTML(string=html_content).write_pdf()
    
    # Define the assets and details for the header overlay
    pride_logo = "logo/pride-logo1.png"
    cin = "CIN: U67190GJ2022PTC130684"
    mail = "Mail:- compliance@pridecons.com"
    call = "Call:- +91-9981919424"
    
    overlay_pdf = PdfReader(BytesIO(pdf_bytes))
    
    # Create a PdfWriter object and add each page after overlaying the header, watermark, and footer
    output_pdf = PdfWriter()
    watermark_text = "Pride Trading Consultancy Private Limited"

    for i, page in enumerate(overlay_pdf.pages, start=1):
        page_width = float(page.mediabox.width)
        page_height = float(page.mediabox.height)
        
        # Create and merge header overlay
        header_overlay = create_header_overlay(page_width, page_height, pride_logo, cin, mail, call)
        page.merge_page(header_overlay)
        
        # Create and merge watermark overlay
        watermark_overlay = create_watermark_overlay(page_width, page_height, watermark_text)
        page.merge_page(watermark_overlay)

        # Create and merge footer overlay
        footer_overlay = create_footer_overlay(page_width, page_height, i)
        page.merge_page(footer_overlay)

        output_pdf.add_page(page)
    
    output_path = "routes/kyc_service/final_merged.pdf"
    with open(output_path, "wb") as f:
        output_pdf.write(f)

    with open(output_path, "rb") as pdf_file:
        final_pdf_bytes = pdf_file.read()

    # Sign the PDF and obtain signed PDF bytes
    signed_pdf_bytes = await sign_pdf(final_pdf_bytes)
    pdf_base64 = base64.b64encode(signed_pdf_bytes).decode("utf-8")
    
    signers = {
        "signer_name": data.get("full_name"),
        "signer_email": kyc_user.email,
        "signer_city": data.get("city"),
        "signer_purpose": "©Service Agreement of Pride Trading Consultancy Pvt. Ltd.",
        "sign_coordinates": [
            {
                "page_num": 1,
                "x_coord": 360,
                "y_coord": 2
            },
            {
                "page_num": 2,
                "x_coord": 360,
                "y_coord": 2
            },
            {
                "page_num": 3,
                "x_coord": 360,
                "y_coord": 2
            },
            {
                "page_num": 4,
                "x_coord": 360,
                "y_coord": 2
            },
            {
                "page_num": 5,
                "x_coord": 360,
                "y_coord": 2
            },
            {
                "page_num": 6,
                "x_coord": 360,
                "y_coord": 2
            },
            {
                "page_num": 7,
                "x_coord": 360,
                "y_coord": 2
            },
            {
                "page_num": 8,
                "x_coord": 360,
                "y_coord": 2
            },
            {
                "page_num": 9,
                "x_coord": 360,
                "y_coord": 2
            },
            {
                "page_num": 10,
                "x_coord": 360,
                "y_coord": 2
            },
            {
                "page_num": 11,
                "x_coord": 360,
                "y_coord": 2
            },
            {
                "page_num": 12,
                "x_coord": 380,
                "y_coord": 570
            }
        ]
    }
    # "y_coord": 570
    url = "https://live.zoop.one/contract/esign/v5/init"
    headers = {
        "app-id": PAN_API_ID,
        "api-key": PAN_API_KEY,
        "Content-Type": "application/json",
    }

    mobile=data.get("mobile")
    platform=data.get("platform","pridebuzz")
    payload = {
        "document": {
            "name": "Agreement Esigning",
            "data": pdf_base64,
            "info": "test"
        },
        "signers": [signers],
        "txn_expiry_min": "10080",
        "white_label": "N",
        "redirect_url": f"https://pridecons.sbs/redirect/{platform}/{mobile}",
        "response_url": f"https://pridecons.sbs/response_url/{mobile}",
        "esign_type": "AADHAAR",
        "email_template": {
            "org_name": "Pride Trading Consultancy"
        }
    }

    data = await request_with_retry(
        method="POST",
        url=url,
        headers=headers,
        json=payload,
        retries=50,
        backoff_factor=0.5,
    )

    return data
