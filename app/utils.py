import os, uuid

def ensure_dirs():
    os.makedirs("/data/uploads", exist_ok=True)


def save_upload_to_disk(filename: str, content: bytes) -> str:
    ensure_dirs()
    ext = os.path.splitext(filename)[1].lower() or ".bin"
    safe = f"{uuid.uuid4().hex}{ext}"
    path = f"/data/uploads/{safe}"
    with open(path, "wb") as f:
        f.write(content)
    return path