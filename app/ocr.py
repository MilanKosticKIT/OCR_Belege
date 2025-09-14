import os
import subprocess
import pytesseract
from PIL import Image, ImageOps, ImageFilter
from pdf2image import convert_from_path

import logging, traceback
logger = logging.getLogger("ocr-belege")


LANG = os.getenv("OCR_LANG", "deu+eng")

# --- OSD/rotation and band cropping helpers ---
from pytesseract import image_to_osd

def _auto_rotate(img: Image.Image) -> Image.Image:
    """Use Tesseract OSD to detect orientation and rotate if needed."""
    try:
        osd = image_to_osd(img)
        # OSD output contains a line like: "Rotate: 90"
        for line in osd.splitlines():
            if line.strip().startswith("Rotate:"):
                deg = int(line.split(":", 1)[1].strip()) % 360
                if deg and deg in (90, 180, 270):
                    logger.info("OCR: auto-rotate %d°", deg)
                    return img.rotate(360 - deg, expand=True)
        return img
    except Exception:
        return img

def _right_band(img: Image.Image, width_ratio: float = 0.45) -> Image.Image:
    """Crop the rightmost band of the image (useful for right-aligned totals)."""
    w, h = img.size
    x0 = int(w * (1.0 - max(0.05, min(width_ratio, 0.9))))
    return img.crop((x0, 0, w, h))

def _pdftotext(path: str) -> str:
    """Use poppler's pdftotext to extract embedded text (if any). Returns text or empty string."""
    try:
        # -layout keeps visual order; -nopgbrk avoids page breaks; '-' writes to stdout
        res = subprocess.run(
            ["pdftotext", "-layout", "-nopgbrk", path, "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        txt = res.stdout.decode("utf-8", errors="ignore")
        logger.info("OCR: pdftotext len=%d rc=%d", len(txt or ""), res.returncode)
        return txt or ""
    except FileNotFoundError:
        logger.info("OCR: pdftotext not available, skipping text-layer extraction")
        return ""
    except Exception as e:
        logger.error("OCR: pdftotext failed for %s: %s\n%s", path, e, traceback.format_exc())
        return ""

def _preprocess_for_ocr(img: Image.Image) -> Image.Image:
    """Lightweight preprocessing: grayscale, autocontrast, scale, sharpen, binarize."""
    try:
        img = _auto_rotate(img)
        g = ImageOps.grayscale(img)
        g = ImageOps.autocontrast(g)
        # upscale small receipts to help Tesseract
        w, h = g.size
        if max(w, h) < 1800:
            g = g.resize((int(w * 1.5), int(h * 1.5)), Image.LANCZOS)
        g = g.filter(ImageFilter.SHARPEN)
        # simple binarization
        g = g.point(lambda p: 255 if p > 180 else 0)
        return g
    except Exception:
        return img

def ocr_image(img: Image.Image) -> str:
    try:
        # Normalize orientation first
        img = _auto_rotate(img)

        attempts = []
        base_cfg = "--oem 1 --psm 6 -c preserve_interword_spaces=1"
        attempts.append((img, base_cfg))
        attempts.append((_preprocess_for_ocr(img), base_cfg))
        attempts.append((_preprocess_for_ocr(img), "--oem 1 --psm 4 -c preserve_interword_spaces=1"))

        # Right-band focused attempts to capture right-aligned prices/totals
        band = _right_band(img, 0.45)
        attempts.append((_preprocess_for_ocr(band), base_cfg + " -c tessedit_char_whitelist=0123456789.,:-CHFfrSFRFr"))
        attempts.append((_preprocess_for_ocr(band), "--oem 1 --psm 7 -c tessedit_char_whitelist=0123456789.,:-CHFfrSFRFr"))

        best = ""
        for i, (im, cfg) in enumerate(attempts, start=1):
            logger.info("OCR: image_to_string attempt %d config='%s'", i, cfg)
            try:
                txt = pytesseract.image_to_string(im, lang=LANG, config=cfg) or ""
            except Exception as e:
                logger.error("OCR: attempt %d failed: %s\n%s", i, e, traceback.format_exc())
                txt = ""
            logger.info("OCR: attempt %d len=%d", i, len(txt))
            if len(txt) > len(best):
                best = txt
        logger.info("OCR: best len=%d", len(best))
        return best
    except Exception as e:
        logger.error("OCR: image_to_string failed: %s\n%s", e, traceback.format_exc())
        return ""

def ocr_file(path: str) -> str:
    """Supports PNG/JPG/PDF. Returns concatenated text."""
    try:
        ext = os.path.splitext(path)[1].lower()
        logger.info("OCR: start file path=%s ext=%s", path, ext)
        if ext in [".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"]:
            with Image.open(path) as im:
                logger.info(
                    "OCR: opened image size=%sx%s mode=%s",
                    getattr(im, "width", "?"),
                    getattr(im, "height", "?"),
                    getattr(im, "mode", "?"),
                )
                return ocr_image(im)
        elif ext == ".pdf":
            # 1) Try extracting embedded text first
            txt = _pdftotext(path)
            if len(txt.strip()) >= 20:
                logger.info("OCR: using pdftotext result len=%d", len(txt))
                return txt
            # 2) Fallback to rasterize + OCR
            try:
                pages = convert_from_path(path, dpi=450)
            except Exception as e:
                logger.error("OCR: convert_from_path failed for %s: %s\n%s", path, e, traceback.format_exc())
                return ""
            logger.info("OCR: PDF rendered pages=%d", len(pages))
            texts = []
            for i, p in enumerate(pages, start=1):
                logger.info("OCR: page %d/%d", i, len(pages))
                texts.append(ocr_image(p))
            out = "\n\n".join(texts)
            logger.info("OCR: done file=%s total_len=%d", path, len(out or ""))
            return out
        else:
            # Try as image fallback
            try:
                with Image.open(path) as im:
                    logger.info(
                        "OCR: fallback opened image size=%sx%s mode=%s",
                        getattr(im, "width", "?"),
                        getattr(im, "height", "?"),
                        getattr(im, "mode", "?"),
                    )
                    return ocr_image(im)
            except Exception as e:
                logger.error("OCR: unsupported or unreadable file %s: %s\n%s", path, e, traceback.format_exc())
                return ""
    except Exception as e:
        logger.error("OCR: unexpected failure for %s: %s\n%s", path, e, traceback.format_exc())
        return ""