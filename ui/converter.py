"""
Robust Document Conversion & Preview Pipeline
=============================================
Converts PDF documents and image files into high-resolution, normalized PNG frames
with multi-tier fallback rendering (pypdfium2 -> pdfplumber -> PIL text-layout),
automatic blank-frame detection, and preview disk caching.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import List, Optional, Tuple, Union

from PIL import Image, ImageDraw, ImageFont, ImageOps
import pypdfium2 as pdfium

logger = logging.getLogger("ui.converter")

PREVIEWS_CACHE_DIR = Path("outputs") / "previews"
PREVIEWS_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def is_image_blank(img: Image.Image, threshold: int = 250) -> bool:
    """
    Checks if an image is completely or virtually blank (e.g. all white pixels).
    Returns True if min pixel brightness is >= threshold (250/255).
    """
    try:
        gray = img.convert("L")
        min_val, max_val = gray.getextrema()
        # If minimum pixel value is >= 250, virtually no dark ink exists
        return min_val >= threshold
    except Exception:
        return False


def create_fallback_text_image(
    file_path: Path,
    page_idx: int = 0,
    width: int = 1000,
    height: int = 1400,
) -> Image.Image:
    """
    Constructs a clean, styled, synthetic image rendering of an invoice from extracted text
    or companion txt when direct PDF pixel rasterization fails or is blank.
    """
    text = ""
    # Try pdfplumber text
    try:
        import pdfplumber

        with pdfplumber.open(file_path) as plumb:
            if 0 <= page_idx < len(plumb.pages):
                text = plumb.pages[page_idx].extract_text() or ""
    except Exception:
        pass

    # Try companion txt file
    if not text.strip():
        txt_path = file_path.with_suffix(".txt")
        if txt_path.exists():
            text = txt_path.read_text(encoding="utf-8")

    if not text.strip():
        text = f"Document: {file_path.name}\n(No readable textual content extracted)"

    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Draw page border & header
    draw.rectangle([15, 15, width - 15, height - 15], outline=(226, 232, 240), width=2)
    draw.rectangle([15, 15, width - 15, 80], fill=(248, 250, 252))
    draw.text(
        (35, 30),
        f"📄 {file_path.name}  (Page {page_idx + 1} Preview)",
        fill=(30, 41, 59),
    )
    draw.line([(15, 80), (width - 15, 80)], fill=(203, 213, 225), width=1)

    # Draw document text lines
    y = 110
    lines = text.splitlines()
    for line in lines:
        if y > height - 60:
            draw.text((35, y), "... [Page content truncated]", fill=(148, 163, 184))
            break
        # Header style lines
        if any(h in line.lower() for h in ("invoice", "grand total", "subtotal", "tax")):
            draw.text((35, y), line, fill=(15, 23, 42))
        else:
            draw.text((35, y), line, fill=(51, 65, 85))
        y += 26

    return img


def get_document_page_count(file_path: Union[str, Path]) -> int:
    """Returns number of pages in document."""
    target = Path(file_path)
    if target.suffix.lower() == ".pdf":
        try:
            doc = pdfium.PdfDocument(target)
            return len(doc)
        except Exception:
            return 1
    return 1


def render_document_to_pil(
    file_path: Union[str, Path],
    page_idx: int = 0,
    scale: float = 2.0,
    force_refresh: bool = False,
) -> Image.Image:
    """
    Renders any PDF or image file into a normalized, high-resolution PIL Image.
    Uses multi-tier fallback to guarantee non-blank previews.
    """
    target = Path(file_path)
    if not target.exists():
        raise FileNotFoundError(f"Document not found: {target}")

    suffix = target.suffix.lower()

    # 1. Image formats (.png, .jpg, .jpeg, .webp, .bmp)
    if suffix in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        img = Image.open(target)
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            mask = img.split()[-1] if "A" in img.mode else None
            bg.paste(img, mask=mask)
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        return img

    # 2. PDF formats: Tiered conversion
    if suffix == ".pdf":
        # Check cache first
        cache_key = f"{target.stem}_p{page_idx}_s{int(scale*10)}.png"
        cache_path = PREVIEWS_CACHE_DIR / cache_key
        if not force_refresh and cache_path.exists():
            try:
                cached_img = Image.open(cache_path)
                if not is_image_blank(cached_img):
                    return cached_img
            except Exception:
                pass

        rendered_img: Optional[Image.Image] = None

        # Tier 1: pypdfium2 with white fill_color
        try:
            pdf = pdfium.PdfDocument(target)
            if 0 <= page_idx < len(pdf):
                page = pdf[page_idx]
                candidate = page.render(
                    scale=scale, fill_color=(255, 255, 255, 255)
                ).to_pil()
                if not is_image_blank(candidate):
                    rendered_img = candidate
                else:
                    logger.warning(
                        "pypdfium2 rendered blank image for %s (page %d)",
                        target.name,
                        page_idx,
                    )
        except Exception as e:
            logger.warning("pypdfium2 error rendering %s: %s", target.name, e)

        # Tier 2: pdfplumber fallback
        if rendered_img is None:
            try:
                import pdfplumber

                with pdfplumber.open(target) as plumb:
                    if 0 <= page_idx < len(plumb.pages):
                        candidate = plumb.pages[page_idx].to_image(
                            resolution=int(72 * scale)
                        ).original
                        if not is_image_blank(candidate):
                            rendered_img = candidate
                        else:
                            logger.warning(
                                "pdfplumber rendered blank image for %s", target.name
                            )
            except Exception as e:
                logger.warning("pdfplumber error rendering %s: %s", target.name, e)

        # Tier 3: Synthetic text-layout fallback
        if rendered_img is None:
            logger.info(
                "Using synthetic text layout preview for %s (page %d)",
                target.name,
                page_idx,
            )
            rendered_img = create_fallback_text_image(target, page_idx=page_idx)

        # Ensure RGB
        if rendered_img.mode != "RGB":
            rendered_img = rendered_img.convert("RGB")

        # Cache valid image
        try:
            rendered_img.save(cache_path, format="PNG")
        except Exception as e:
            logger.warning("Failed to cache preview: %s", e)

        return rendered_img

    raise ValueError(f"Unsupported document format: {suffix}")


def render_document_to_png_bytes(
    file_path: Union[str, Path],
    page_idx: int = 0,
    scale: float = 2.0,
    force_refresh: bool = False,
) -> bytes:
    """Renders document to PNG bytes."""
    img = render_document_to_pil(
        file_path, page_idx=page_idx, scale=scale, force_refresh=force_refresh
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
