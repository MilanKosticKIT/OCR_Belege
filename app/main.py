from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from app.database import Base, engine, SessionLocal
from app import models
from app import ocr as ocr_mod
from app import parser as parser_mod
from app.utils import save_upload_to_disk
import magic
import logging, traceback
import os

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))

app = FastAPI(title="OCR Belege – Schritt 1")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ocr-belege")


# DB erstellen (SQLite-Datei im gemounteten Volume)
Base.metadata.create_all(bind=engine)

# Ensure /data/debug exists when OCR_DEBUG_DUMP=1 and write a marker file
if os.getenv("OCR_DEBUG_DUMP", "0") == "1":
    try:
        os.makedirs("/data/debug", exist_ok=True)
        with open("/data/debug/._debug_enabled", "w") as f:
            f.write("ok\n")
        logger.info("DEBUG_DUMP enabled: /data/debug created and marker written")
    except Exception as e:
        logger.warning("Failed to init /data/debug: %s", e)

# Serve uploaded files (download links)
UPLOAD_DIR = "/data/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/files", StaticFiles(directory=UPLOAD_DIR), name="files")


@app.post("/api/upload", response_model=None)
async def upload_receipt(file: UploadFile = File(...)):
    try:
        # Datei einlesen (im Speicher) und Größe prüfen
        content = await file.read()
        size = len(content)
        logger.info("UPLOAD: name=%s size=%d bytes", file.filename, size)
        if size > MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Datei zu groß")

        # Auf Disk speichern
        path = save_upload_to_disk(file.filename, content)
        logger.info("UPLOAD: saved to %s", path)

        # Mimetype prüfen – robust mit Fallback
        try:
            m = magic.Magic(mime=True)
            mime = m.from_buffer(content[:4096])
        except Exception:
            try:
                mime = magic.Magic(mime=True).from_file(path)
            except Exception:
                mime = "application/octet-stream"
        logger.info("UPLOAD: mime=%s", mime)
        if not ("image" in mime or "pdf" in mime or file.filename.lower().endswith((".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"))):
            raise HTTPException(status_code=415, detail=f"Nicht unterstützter Typ: {mime}")

        # OCR
        logger.info("UPLOAD: calling OCR for %s", path)
        text = ocr_mod.ocr_file(path)
        logger.info("UPLOAD: OCR returned len=%d", len(text or ""))

        if os.getenv("OCR_DEBUG_DUMP", "0") == "1":
            try:
                os.makedirs("/data/debug", exist_ok=True)
                with open(f"/data/debug/receipt_{os.path.basename(path)}.txt", "w", encoding="utf-8") as f:
                    f.write(text or "")
                logger.info("DEBUG_DUMP: wrote /data/debug/receipt_%s.txt", os.path.basename(path))
            except Exception as e:
                logger.warning("DEBUG_DUMP: failed to write receipt text dump: %s", e)

        if not text:
            logger.warning("OCR returned empty text for %s", path)

        # Parser-Infos (Store/Chain/Total)
        store_name, chain_name, total = parser_mod.parse_store_and_total(text or "")
        logger.info("PARSE: store=%s chain=%s total=%s", store_name, chain_name, total)

        # Persistieren
        with SessionLocal() as db:
            store = None
            if store_name or chain_name:
                store = (
                    db.query(models.Store)
                    .filter(models.Store.name == (store_name or chain_name))
                    .first()
                )
                if not store:
                    store = models.Store(name=store_name or chain_name, chain=chain_name)
                    db.add(store)
                    db.flush()
            receipt = models.Receipt(
                store_id=store.id if store else None,
                raw_text=text or "",
                source_file=path,
                total=total,
            )
            db.add(receipt)
            db.commit()
            db.refresh(receipt)
            logger.info("DB: saved receipt id=%s file=%s total=%s", receipt.id, path, total)

        download_url = f"/files/{os.path.basename(path)}"
        return {"status": "ok", "receipt_id": receipt.id, "download_url": download_url, "parsed_total": total}
    except HTTPException:
        # Durchreichen von kontrollierten API-Fehlern
        raise
    except Exception as e:
        # Unerwartete Fehler: loggen und generische Fehlermeldung senden
        logger.error("Upload failed: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail="Interner Fehler beim Verarbeiten des Belegs. Bitte Logs prüfen.")

# List receipts endpoint
@app.get("/api/receipts")
def list_receipts(limit: int = 50, offset: int = 0):
    """Listet Belege paginiert auf (neueste zuerst)."""
    with SessionLocal() as db:
        q = db.query(models.Receipt).order_by(models.Receipt.id.desc()).offset(offset).limit(limit)
        rows = q.all()
        data = []
        for r in rows:
            store = None
            if r.store_id:
                s = db.query(models.Store).get(r.store_id)
                if s:
                    store = {"id": s.id, "name": s.name, "chain": s.chain}
            data.append({
                "id": r.id,
                "store": store,
                "purchase_datetime": r.purchase_datetime.isoformat(),
                "total": r.total,
                "download_url": f"/files/{os.path.basename(r.source_file)}" if r.source_file else None,
            })
        return {"items": data, "count": len(data), "offset": offset, "limit": limit}

# Receipt details endpoint
@app.get("/api/receipts/{receipt_id}")
def get_receipt(receipt_id: int):
    with SessionLocal() as db:
        r = db.query(models.Receipt).get(receipt_id)
        if not r:
            raise HTTPException(status_code=404, detail="Receipt not found")
        store = None
        if r.store_id:
            s = db.query(models.Store).get(r.store_id)
            if s:
                store = {"id": s.id, "name": s.name, "chain": s.chain}
        return {
            "id": r.id,
            "store": store,
            "purchase_datetime": r.purchase_datetime.isoformat(),
            "currency": r.currency,
            "total": r.total,
            "source_file": r.source_file,
            "download_url": f"/files/{os.path.basename(r.source_file)}" if r.source_file else None,
            "raw_text": r.raw_text,
        }



@app.get("/", response_class=HTMLResponse)
def index_page():
    # Serve the UI from app/static/index.html so PyCharm/Compose share the same file
    base_dir = os.path.dirname(__file__)
    path = os.path.join(base_dir, "static", "index.html")
    if not os.path.exists(path):
        # Friendly hint if the file is missing
        return HTMLResponse("<h3>index.html not found</h3><p>Please place your UI at app/static/index.html</p>", status_code=200)
    return FileResponse(path)

@app.get("/api/health")
async def health():
    return {"status": "ok"}
