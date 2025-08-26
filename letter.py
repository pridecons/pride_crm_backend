# letterhead.py
# Professional letterhead with polished header/footer and soft watermark.

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.pdfbase import pdfmetrics

# ---------- Config ----------
DEFAULT_PAGE_SIZE = A4  # change to LETTER if needed
DEFAULT_LOGO_PATH = "logo/pridespheresolutions.png"  # ensure this path exists

DEFAULT_CIN = "CIN: U62090GJ2025PTC163460"
DEFAULT_MAIL = "Mail: support@pridesphere.in"
DEFAULT_CALL = "+91-7772883338"
DEFAULT_WATERMARK = "PRIDESPHERE SOLUTIONS PRIVATE LIMITED"
DEFAULT_ADDRESS = (
    "410-411, 4th Floor, Serene Centrum, "
    "Near Gangotri Exotica, Gotri, Sevasi Road, "
    "VADODARA, GUJARAT, 390021"
)
OUTPUT_PATH = "pridespher_letterhead.pdf"

# Layout constants (tuned for a balanced look)
MARGIN_L = 20
MARGIN_R = 20
MARGIN_T = 28
MARGIN_B = 20
HEADER_LOGO_W = 180
HEADER_LOGO_H = 50
HEADER_TEXT_SIZE = 10
FOOTER_TEXT_SIZE = 8
RULE_COLOR = (0.75, 0.75, 0.75)  # light gray for separators


# ---------- Helpers ----------
def draw_header(c: canvas.Canvas, page_w: float, page_h: float,
                logo_path: str, cin: str, mail: str, call: str) -> None:
    """Logo (left), info (right), and a fine rule below header."""
    # Logo (top-left)
    try:
        c.drawImage(
            logo_path,
            0,   # start from very left
            page_h - HEADER_LOGO_H - MARGIN_T,
            width=HEADER_LOGO_W,
            height=HEADER_LOGO_H,
            preserveAspectRatio=True,
            mask="auto",
        )

    except Exception:
        # Logo optional; don't crash if missing
        pass

    # Right-side stacked lines
    c.setFont("Helvetica", HEADER_TEXT_SIZE)
    lines = [cin, mail, call]
    # Align against top area of header block
    text_top = page_h - MARGIN_T - 6
    y = text_top
    for line in lines:
        c.drawRightString(page_w - MARGIN_R, y, line)
        y -= (HEADER_TEXT_SIZE + 2)

    # Bottom header rule
    c.setStrokeColorRGB(*RULE_COLOR)
    c.setLineWidth(0.6)
    c.line(MARGIN_L, page_h - HEADER_LOGO_H - MARGIN_T - 8, page_w - MARGIN_R,
           page_h - HEADER_LOGO_H - MARGIN_T - 8)


def draw_watermark(c: canvas.Canvas, page_w: float, page_h: float, text: str) -> None:
    """Very soft diagonal watermark with slight letter spacing (looks thinner)."""
    c.saveState()
    # Super light gray + smaller font to keep it subtle
    c.setFont("Helvetica-Bold", 32)
    c.setFillColorRGB(0.97, 0.97, 0.97)

    # Use a text object to add slight character spacing
    text_obj = c.beginText()
    text_obj.setTextOrigin(page_w / 2, page_h / 2)
    text_obj.setCharSpace(1.2)  # subtle spread makes it feel lighter
    # Rotate around page center
    c.translate(page_w / 2, page_h / 2)
    c.rotate(45)
    c.translate(-page_w / 2, -page_h / 2)

    # Centered draw (manually measure to center)
    w = pdfmetrics.stringWidth(text, "Helvetica-Bold", 32) + (len(text) - 1) * 1.2
    x = (page_w - w) / 2
    y = page_h / 2
    text_obj.setTextOrigin(x, y)
    text_obj.textLine(text)
    c.drawText(text_obj)
    c.restoreState()


def draw_footer(c: canvas.Canvas, page_w: float, page_h: float, page_num: int, address: str) -> None:
    """Footer: separator line, page num (left), © (right), centered address."""
    # Separator line above footer content
    c.setStrokeColorRGB(*RULE_COLOR)
    c.setLineWidth(0.5)
    rule_y = MARGIN_B + 24
    c.line(MARGIN_L, rule_y, page_w - MARGIN_R, rule_y)

    # Page number (left) and © (right)
    c.setFont("Helvetica", FOOTER_TEXT_SIZE)
    c.setFillColorRGB(0, 0, 0)

    # Address (centered, with smart wrap), positioned below the line
    draw_centered_wrapped_line(
        c,
        address,
        page_w,
        y=MARGIN_B,  # bottom text baseline
        font_name="Helvetica",
        font_size=FOOTER_TEXT_SIZE,
        max_lines=2,
        side_margin=MARGIN_L,
    )


def draw_centered_wrapped_line(
    c: canvas.Canvas,
    text: str,
    page_w: float,
    y: float,
    font_name: str = "Helvetica",
    font_size: int = 8,
    max_lines: int = 2,
    side_margin: float = 40.0,
):
    """
    Center a long line by splitting into up to `max_lines` lines if it exceeds width.
    Simple split-on-spaces keeps it robust without extra deps.
    """
    c.setFont(font_name, font_size)
    max_width = page_w - 2 * side_margin
    width = pdfmetrics.stringWidth(text, font_name, font_size)
    if width <= max_width or max_lines <= 1:
        x = (page_w - width) / 2
        c.drawString(x, y, text)
        return

    # Try to split into two lines (max_lines=2) at nearest space
    words = text.split()
    line1 = []
    idx = 0
    while idx < len(words):
        test = (" ".join(line1 + [words[idx]])).strip()
        if pdfmetrics.stringWidth(test, font_name, font_size) <= max_width:
            line1.append(words[idx])
            idx += 1
        else:
            break

    l1 = " ".join(line1).strip() or text
    l2 = " ".join(words[idx:]).strip()

    w1 = pdfmetrics.stringWidth(l1, font_name, font_size)
    c.drawString((page_w - w1) / 2, y + (font_size + 3), l1)

    if l2:
        w2 = pdfmetrics.stringWidth(l2, font_name, font_size)
        c.drawString((page_w - w2) / 2, y, l2)


# ---------- Main generator ----------
def generate_blank_letterhead(
    output_path: str = OUTPUT_PATH,
    pages: int = 1,
    page_size=DEFAULT_PAGE_SIZE,
    logo_path: str = DEFAULT_LOGO_PATH,
    cin: str = DEFAULT_CIN,
    mail: str = DEFAULT_MAIL,
    call: str = DEFAULT_CALL,
    watermark_text: str = DEFAULT_WATERMARK,
    address: str = DEFAULT_ADDRESS,
) -> str:
    """
    Create a PDF with N blank pages containing ONLY:
      - Header (logo + CIN + email + call) with a bottom rule
      - Footer (rule + page no. + © + centered address)
      - Diagonal soft watermark
    """
    page_w, page_h = page_size
    c = canvas.Canvas(output_path, pagesize=page_size)

    for i in range(1, pages + 1):
        draw_header(c, page_w, page_h, logo_path, cin, mail, call)
        draw_watermark(c, page_w, page_h, watermark_text)
        draw_footer(c, page_w, page_h, i, address)
        c.showPage()

    c.save()
    return output_path


# ---------- CLI ----------
if __name__ == "__main__":
    path = generate_blank_letterhead(
        output_path=OUTPUT_PATH,
        pages=1,
        page_size=DEFAULT_PAGE_SIZE,  # or LETTER
        logo_path=DEFAULT_LOGO_PATH,
        cin=DEFAULT_CIN,
        mail=DEFAULT_MAIL,
        call=DEFAULT_CALL,
        watermark_text=DEFAULT_WATERMARK,
        address=DEFAULT_ADDRESS,
    )
    print("✅ Created:", path)
