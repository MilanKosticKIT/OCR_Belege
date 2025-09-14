from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse
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


@app.post("/api/upload", response_model=None)
async def upload_receipt(file: UploadFile = File(...)):
    try:
        # Datei einlesen (im Speicher) und Größe prüfen
        content = await file.read()
        size = len(content)
        if size > MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Datei zu groß")

        # Auf Disk speichern
        path = save_upload_to_disk(file.filename, content)

        # Mimetype prüfen – robust mit Fallback
        try:
            m = magic.Magic(mime=True)
            mime = m.from_buffer(content[:4096])
        except Exception:
            try:
                mime = magic.Magic(mime=True).from_file(path)
            except Exception:
                mime = "application/octet-stream"
        if not ("image" in mime or "pdf" in mime or file.filename.lower().endswith((".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"))):
            raise HTTPException(status_code=415, detail=f"Nicht unterstützter Typ: {mime}")

        # OCR
        text = ocr_mod.ocr_file(path)
        if not text:
            logger.warning("OCR returned empty text for %s", path)

        # Parser-Infos (Store/Chain/Total)
        store_name, chain_name, total = parser_mod.parse_store_and_total(text or "")

        # Wenn kein Betrag erkannt wurde, dem Client melden (422)
        if total is None:
            raise HTTPException(
                status_code=422,
                detail="Der Betrag (Total) wurde nicht erkannt. Bitte Belegfoto/-PDF prüfen und erneut versuchen."
            )

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

        return {"status": "ok", "receipt_id": receipt.id}

    except HTTPException:
        # Durchreichen von kontrollierten API-Fehlern
        raise
    except Exception as e:
        # Unerwartete Fehler: loggen und generische Fehlermeldung senden
        logger.error("Upload failed: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail="Interner Fehler beim Verarbeiten des Belegs. Bitte Logs prüfen.")


@app.get("/", response_class=HTMLResponse)
def index_page():
    return (
        """
        <!doctype html>
        <html>
        <head>
          <meta charset="utf-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1" />
          <title>OCR Belege – Upload</title>
          <style>
            body { font-family: system-ui, sans-serif; margin: 2rem; }
            .card { max-width: 520px; padding: 1rem; border: 1px solid #ddd; border-radius: 12px; }
            .row { margin: .5rem 0; }
            button { padding: .5rem 1rem; border-radius: 8px; border: 1px solid #444; background: #fff; cursor: pointer; }
            #out { margin-top: 1rem; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
          </style>
        </head>
        <body>
          <div class="card">
            <h2>Beleg hochladen</h2>
            <form id="f">
              <div class="row"><input type="file" id="file" name="file" accept="image/*,.pdf" required /></div>
              <div class="row"><button type="submit">Upload & OCR</button></div>
            </form>
            <div id="out"></div>
          </div>
          <script>
          const f = document.getElementById('f');
          const out = document.getElementById('out');
          f.addEventListener('submit', async (e) => {
            e.preventDefault();
            const fd = new FormData();
            const file = document.getElementById('file').files[0];
            if (!file) return;
            fd.append('file', file);
            out.textContent = 'Lade hoch…';
            const res = await fetch('/api/upload', { method: 'POST', body: fd });
            if (!res.ok) { out.textContent = 'Fehler: ' + (await res.text()); return; }
            const js = await res.json();
            out.textContent = 'OK – Receipt ID: ' + js.receipt_id;
          });
          </script>
        </body>
        </html>
        """
    )

@app.get("/api/health")
async def health():
    return {"status": "ok"}
