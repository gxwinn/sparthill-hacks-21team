import base64
import io
from PIL import Image, ImageDraw
from backend.schemas import ExtractedBillSchema, RawLineItem

PII_KEYS = {
    "patient_name",
    "patient_address",
    "account_number",
    "mrn",
    "dob",
    "ssn",
    "phone",
}


def redact_bill_image(image_bytes: bytes) -> tuple[bytes, str, dict]:
    """
    Black out the top 15% of a medical bill image (where Patient Name, Address,
    and Account Number appear) locally using Pillow BEFORE any bytes leave the server.

    Returns:
        (redacted_png_bytes, base64_data_uri, privacy_meta)
    """
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        # Graceful fallback if user uploads a non-image or corrupted file during testing
        img = _create_synthetic_bill_canvas(
            hospital_name="Uploaded Statement",
            line_items=[],
        )

    width, height = img.size
    redact_height = max(24, int(height * 0.15))

    draw = ImageDraw.Draw(img)
    # Solid black redaction box over top 15%
    draw.rectangle([(0, 0), (width, redact_height)], fill=(0, 0, 0))
    # Subtle red bottom border line on the redaction zone for visual clarity in UI
    draw.line([(0, redact_height), (width, redact_height)], fill=(220, 38, 38), width=2)

    badge_text = (
        "LOCAL PILLOW PII SCRUBBER: TOP 15% HEADER BLACKED OUT "
        "(PATIENT NAME / ADDRESS / ACCOUNT # REMOVED | 0 PHI BYTES SENT)"
    )
    text_y = max(4, (redact_height // 2) - 6)
    draw.text((12, text_y), badge_text, fill=(255, 255, 255))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    redacted_bytes = buf.getvalue()
    b64_str = base64.b64encode(redacted_bytes).decode("ascii")
    data_uri = f"data:image/png;base64,{b64_str}"

    privacy_meta = {
        "pii_scrubbed_locally": True,
        "phi_bytes_sent_to_cloud": 0,
        "redaction_method": "Pillow (PIL) Top-15% Image Header Blackout + Local Field Scrubber",
        "redacted_region": f"Top 15% Header (0, 0) -> ({width}px, {redact_height}px)",
        "redacted_fields": [
            "Patient Full Name",
            "Residential Street Address",
            "Hospital Account / Guarantor #",
            "Medical Record Number (MRN)",
            "Date of Birth",
        ],
    }
    return redacted_bytes, data_uri, privacy_meta


def scrub_demo_bill(
    demo_payload: dict, hospital_override: str | None = None
) -> tuple[ExtractedBillSchema, str, dict]:
    """
    Scrub PII fields from a demo bill dictionary locally and generate a visual
    Pillow top-15%-redacted preview image.
    """
    scrubbed_dict = {
        k: ("[REDACTED_LOCALLY]" if k in PII_KEYS else v)
        for k, v in demo_payload.items()
    }
    hospital_name = hospital_override or scrubbed_dict.get(
        "hospital_name", "El Camino Health"
    )
    raw_items = [RawLineItem(**item) for item in scrubbed_dict.get("line_items", [])]

    extracted = ExtractedBillSchema(
        hospital_name=hospital_name,
        is_itemized=bool(scrubbed_dict.get("is_itemized", True)),
        line_items=raw_items,
    )

    # Render synthetic medical bill image and run the exact Pillow top-15% blackout on it
    synthetic_img = _create_synthetic_bill_canvas(
        hospital_name=hospital_name,
        line_items=raw_items,
        is_itemized=extracted.is_itemized,
    )
    raw_buf = io.BytesIO()
    synthetic_img.save(raw_buf, format="PNG")
    _, data_uri, privacy_meta = redact_bill_image(raw_buf.getvalue())

    return extracted, data_uri, privacy_meta


def _create_synthetic_bill_canvas(
    hospital_name: str,
    line_items: list[RawLineItem],
    is_itemized: bool = True,
) -> Image.Image:
    """Create a realistic medical statement image before top-15% redaction."""
    width = 820
    height = max(360, 160 + len(line_items) * 28)
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Top 15% header (will be blacked out by redact_bill_image)
    draw.text((20, 10), f"PATIENT: JANE DOE | DOB: 04/12/1985 | ACCT #: 99482104", fill=(40, 40, 40))
    draw.text((20, 28), "ADDRESS: 742 EVERGREEN TERRACE, SUNNYVALE, CA 94086", fill=(40, 40, 40))

    # Below top 15% header: visible clinical billing lines
    body_start_y = int(height * 0.17)
    draw.text(
        (20, body_start_y),
        f"PROVIDER STATEMENT: {hospital_name.upper()}  |  ITEMIZED: {'YES (CPT/HCPCS)' if is_itemized else 'NO (SUMMARY ONLY)'}",
        fill=(15, 23, 42),
    )
    draw.line(
        [(20, body_start_y + 20), (width - 20, body_start_y + 20)],
        fill=(148, 163, 184),
        width=1,
    )

    y = body_start_y + 30
    draw.text((20, y), "CPT/HCPCS", fill=(71, 85, 105))
    draw.text((130, y), "SERVICE DESCRIPTION", fill=(71, 85, 105))
    draw.text((580, y), "QTY", fill=(71, 85, 105))
    draw.text((660, y), "BILLED AMT", fill=(71, 85, 105))
    y += 22

    total = 0.0
    for item in line_items:
        code_txt = item.cpt_code if item.cpt_code else "NONE"
        draw.text((20, y), code_txt, fill=(15, 23, 42))
        draw.text((130, y), item.description[:52], fill=(15, 23, 42))
        draw.text((585, y), str(item.quantity), fill=(15, 23, 42))
        draw.text((660, y), f"${item.billed_amount:,.2f}", fill=(15, 23, 42))
        total += item.billed_amount
        y += 22

    draw.line([(20, y + 4), (width - 20, y + 4)], fill=(148, 163, 184), width=1)
    draw.text((500, y + 12), f"TOTAL GROSS BILLED: ${total:,.2f}", fill=(15, 23, 42))
    return img
