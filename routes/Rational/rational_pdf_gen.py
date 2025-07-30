#!/usr/bin/env python3
import os
import io
import base64
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML, CSS
from weasyprint.text.fonts import FontConfiguration
import tempfile
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import signers, PdfSignatureMetadata
from pyhanko.sign.fields import SigFieldSpec
import asyncio
from datetime import datetime

this_dir = os.path.dirname(os.path.abspath(__file__))
templates_dir = this_dir
project_root = os.path.dirname(os.path.dirname(this_dir))
static_dir = os.path.join(project_root, "static")

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
            try:
                signer = signers.SimpleSigner.load_pkcs12(
                    pfx_file='./certificate.pfx', 
                    passphrase=b'123456'  # Update your passphrase
                )
            except FileNotFoundError:
                print("⚠️ Certificate file not found. Creating unsigned PDF.")
                return tmp_path
            
            with open(tmp_path, 'rb') as doc:
                writer = IncrementalPdfFileWriter(doc, strict=False)

                # Position signature in footer area (bottom right)
                sig_field_spec = SigFieldSpec(
                    'Signature1',
                    on_page=-1,  # Last page
                    box=(400, 100, 580, 150)  # (left, bottom, right, top) - bottom right corner
                )

                # Create signature metadata
                sig_meta = PdfSignatureMetadata(
                    field_name='Signature1',
                    reason='Document authentication',
                    location='Pride Trading Consultancy',
                    name='Pride Trading System'
                )

                signed_pdf_io = signers.sign_pdf(
                    writer,
                    signature_meta=sig_meta,
                    signer=signer,
                    existing_fields_only=False, 
                    new_field_spec=sig_field_spec
                )

            with open(signed_pdf_path, 'wb') as outf:
                outf.write(signed_pdf_io.getvalue())

            return signed_pdf_path

        result = await asyncio.to_thread(sign_pdf_sync)
        
        # Clean up original temp file
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        # Read the signed PDF
        with open(result, "rb") as f:
            signed_pdf_bytes = f.read()
        
        # Clean up signed temp file
        if os.path.exists(result):
            os.remove(result)
            
        return signed_pdf_bytes

    except Exception as e:
        print(f"❌ PDF signing failed: {str(e)}")
        # Return original PDF if signing fails
        return pdf_bytes


def encode_image_to_base64(image_path):
    """Convert image to base64 string for embedding in HTML"""
    try:
        with open(image_path, "rb") as img_file:
            img_data = img_file.read()
            img_base64 = base64.b64encode(img_data).decode('utf-8')
            
            # Detect image format
            if image_path.lower().endswith('.png'):
                mime_type = 'image/png'
            elif image_path.lower().endswith(('.jpg', '.jpeg')):
                mime_type = 'image/jpeg'
            elif image_path.lower().endswith('.svg'):
                mime_type = 'image/svg+xml'
            else:
                mime_type = 'image/png'  # default
                
            return f"data:{mime_type};base64,{img_base64}"
    except FileNotFoundError:
        print(f"⚠️ Warning: Image not found at {image_path}")
        return None

def process_data_for_pdf(data):
    """Process data to convert image paths to base64"""
    processed_data = data.copy()
    
    # Handle logo
    logo_path = os.path.join(project_root, "logo", "pride-logo1.png")
    if os.path.exists(logo_path):
        processed_data['logo_base64'] = encode_image_to_base64(logo_path)
        print(f"✅ Logo encoded: {logo_path}")
    else:
        print(f"⚠️ Logo not found at: {logo_path}")
        processed_data['logo_base64'] = None
    
    # Handle graph image
    if data.get('graph'):
        # Remove leading slash and construct full path
        graph_relative_path = data['graph'].lstrip('/')
        graph_path = os.path.join(project_root, graph_relative_path)
        
        if os.path.exists(graph_path):
            processed_data['graph_base64'] = encode_image_to_base64(graph_path)
            print(f"✅ Graph encoded: {graph_path}")
        else:
            print(f"⚠️ Graph not found at: {graph_path}")
            processed_data['graph_base64'] = None
    
    return processed_data

async def generate_signed_pdf(recommendation):
    data = {
        "id": recommendation.id,
        "entry_price": recommendation.entry_price,
        "stop_loss": recommendation.stop_loss,
        "targets": recommendation.targets,
        "targets2": recommendation.targets2,
        "targets3": recommendation.targets3,
        "status": recommendation.status,
        "rational": recommendation.rational,
        "stock_name": recommendation.stock_name,
        "recommendation_type": recommendation.recommendation_type,
        "graph": recommendation.graph,
        "pdf": recommendation.pdf,
        "user_id": recommendation.user_id,
        "created_at": recommendation.created_at,
        "updated_at": recommendation.updated_at,
    }
    """Generate PDF and optionally sign it"""
    # Process data to handle images
    processed_data = process_data_for_pdf(data)
    
    # Load the Jinja2 template
    env = Environment(
        loader=FileSystemLoader(templates_dir),
        autoescape=True
    )
    template = env.get_template("narration.html")

    # Render HTML with processed data
    html_content = template.render(data=processed_data)
    
    # Create font configuration for better font rendering
    font_config = FontConfiguration()
    
    # Convert to PDF with proper base_url and font config
    pdf_bytes = HTML(
        string=html_content, 
        base_url=f"file://{project_root}/"
    ).write_pdf(
        font_config=font_config,
        optimize_size=('fonts', 'images')
    )


    pdf_bytes = await sign_pdf(pdf_bytes)
    print("✅ PDF signed successfully")

    rational_dir = os.path.join(project_root, "static", "rational")
    os.makedirs(rational_dir, exist_ok=True)
    
    # Save to file
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_filename = f"{timestamp}.pdf"

    output_path = os.path.join(rational_dir, output_filename)
    with open(output_path, "wb") as f:
        f.write(pdf_bytes)
    
    rel_path = os.path.relpath(output_path, project_root)      # e.g. "static/rational/2025-07-30_13-30-33.pdf"
    url_path = "/" + rel_path.replace(os.path.sep, "/")

    print(f"✅ PDF generated at: {output_path}")
    return output_path, url_path, pdf_bytes

# if __name__ == "__main__":
#     data = {
#         "entry_price": 44,
#         "stop_loss": 40,
#         "targets": 46,
#         "targets2": 48,
#         "targets3": 50,
#         "graph": "/static/graphs/sgvgedtededj625.png",
#         "rational": "HCLTECH TREND IS BEARISH…",
#         "stock_name": "HCLTECH",
#         "recommendation_type": "Equity Cash",
#         "created_at": "2025-07-29T10:16:08Z",
#         "updated_at": "2025-07-29T10:21:26Z"
#     }
    
#     # Generate signed PDF
#     async def main():
#         try:
#             print("📄 Generating signed PDF...")
#             output_path, pdf_bytes = await generate_signed_pdf(data)
#             print(f"🎉 Success! Signed PDF saved to: {output_path}")
#         except Exception as e:
#             print(f"❌ Base64 method failed: {e}")
#             print("🔄 Trying file URL method...")

#     # Run the async function
#     asyncio.run(main())