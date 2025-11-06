import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from database import db, create_document
from schemas import Asset

app = FastAPI(title="HoloShare API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Storage directory
STORAGE_DIR = os.path.join(os.getcwd(), "uploads")
os.makedirs(STORAGE_DIR, exist_ok=True)

# Ensure TTL index for 15 days on created_at
if db is not None:
    try:
        db["asset"].create_index("created_at", expireAfterSeconds=60 * 60 * 24 * 15)
    except Exception:
        pass

class UploadResponse(BaseModel):
    id: str
    url: str

@app.get("/")
def read_root():
    return {"message": "HoloShare backend running"}

@app.post("/upload", response_model=UploadResponse)
async def upload_model(file: UploadFile = File(...)):
    # Validate extension
    name_lower = file.filename.lower()
    if not (name_lower.endswith('.glb') or name_lower.endswith('.gltf') or name_lower.endswith('.usdz')):
        raise HTTPException(status_code=400, detail="Only .glb, .gltf, .usdz files are supported")

    # Store to disk
    unique = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    save_name = f"{unique}_{file.filename}"
    save_path = os.path.join(STORAGE_DIR, save_name)

    content = await file.read()
    with open(save_path, 'wb') as f:
        f.write(content)

    # Public URL served via /files/{name}
    public_url = f"/files/{save_name}"

    # Save metadata to DB
    doc_id = create_document(
        "asset",
        {
            "filename": file.filename,
            "content_type": file.content_type,
            "size_bytes": len(content),
            "url": public_url,
            "storage_path": save_path,
        },
    )

    return UploadResponse(id=doc_id, url=public_url)

@app.get("/files/{filename}")
async def serve_file(filename: str):
    path = os.path.join(STORAGE_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    # Let model-viewer handle correct type based on extension
    return FileResponse(path)

@app.get("/asset/{id}")
async def get_asset(id: str):
    from bson import ObjectId
    try:
        oid = ObjectId(id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")

    doc = db["asset"].find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found or expired")

    return {"id": id, "url": doc.get("url")}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
