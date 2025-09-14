import os
import pytesseract
from PIL import Image
from pdf2image import convert_from_path

LANG = os.getenv("OCR_LANG", "deu+eng")


def ocr_image(img: Image.Image) -> str:
    return pytesseract.image_to_string(img, lang=LANG)


def ocr_file(path: str) -> str:
    """Supports PNG/JPG/PDF. Returns concatenated text."""
    ext = os.path.splitext(path)[1].lower()
    if ext in [".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"]:
        with Image.open(path) as im:
            return ocr_image(im)
    elif ext == ".pdf":
        pages = convert_from_path(path, dpi=300)
        texts = [ocr_image(p) for p in pages]
        return "\n\n".join(texts)
    else:
        # Versuch als Bild
        try:
            with Image.open(path) as im:
                return ocr_image(im)
        except Exception:
            return ""