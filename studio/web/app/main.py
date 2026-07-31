"""API FastAPI de Canal Meteo Studio (nimbus).

uvicorn sirve API + frontend estático; nginx hace de proxy/TLS delante
para studio.canalmeteo.tv. El vídeo de origen NO pasa por aquí: el navegador
lo sube directo a Spaces con una URL PUT prefirmada.
"""
from __future__ import annotations

import logging
import os
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from studio.shared import config as cfg
from studio.shared import schemas, spaces
from . import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("studio.web")

app = FastAPI(title="Canal Meteo Studio", version="0.1.0")

_STATIC = os.path.join(os.path.dirname(__file__), "..", "static")


@app.on_event("startup")
def _startup() -> None:
    db.init()
    log.info("Studio web lista — bucket=%s prefix=%s", cfg.SPACES_BUCKET, cfg.STUDIO_PREFIX)


# ─── Modelos de petición ─────────────────────────────────────────────
class CreateJobReq(BaseModel):
    filename: str = Field(..., min_length=1)
    content_type: str = "video/mp4"
    script_text: str = ""
    language: str = "es"
    operations: dict = {}


# ─── Endpoints ───────────────────────────────────────────────────────
@app.post("/api/jobs")
def create_job(req: CreateJobReq):
    """Crea el job y devuelve la URL PUT prefirmada para subir el origen."""
    job_id = uuid.uuid4().hex[:12]
    ext = os.path.splitext(req.filename)[1].lstrip(".").lower() or "mp4"
    src_key = cfg.source_key(job_id, ext)

    db.create_job(job_id, req.filename, src_key, req.language, req.script_text, req.operations)
    # Firmamos SIN ContentType a propósito: así el navegador puede subir con un
    # blob sin tipo y NO dispara la cabecera `content-type` en el preflight CORS
    # (que requeriría "Allowed Headers" en el bucket). El worker re-codifica igual.
    upload_url = spaces.presigned_put(src_key, expires=6 * 3600)

    return {
        "job_id": job_id,
        "source_key": src_key,
        "upload_url": upload_url,
        "upload_method": "PUT",
        "upload_headers": {},
    }


@app.post("/api/jobs/{job_id}/confirm")
def confirm_upload(job_id: str):
    """El navegador confirma que ya subió el origen → publicamos el job en Spaces."""
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "job desconocido")
    if not spaces.exists(job["source_key"]):
        raise HTTPException(400, "el origen no está en Spaces todavía")

    job_doc = schemas.new_job_doc(
        job_id=job_id,
        source_key=job["source_key"],
        source_filename=job["source_filename"],
        script_text=job["script_text"],
        operations=job["operations"],
        language=job["language"],
    )
    spaces.put_json(cfg.job_doc_key(job_id), job_doc)
    spaces.put_json(cfg.status_key(job_id), schemas.new_status_doc(job_id))
    db.mark_submitted(job_id)
    log.info("job %s publicado en Spaces (pending)", job_id)
    return {"ok": True, "job_id": job_id}


@app.get("/api/jobs")
def list_jobs():
    out = []
    for j in db.list_jobs():
        st = spaces.get_json(cfg.status_key(j["job_id"])) or {}
        out.append({
            "job_id": j["job_id"],
            "filename": j["source_filename"],
            "created_at": j["created_at"],
            "web_state": j["web_state"],
            "state": st.get("state", j["web_state"]),
            "progress": st.get("progress", 0),
        })
    return {"jobs": out}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "job desconocido")
    status = spaces.get_json(cfg.status_key(job_id)) or schemas.new_status_doc(job_id, job["web_state"])
    return {
        "job_id": job_id,
        "filename": job["source_filename"],
        "language": job["language"],
        "operations": job["operations"],
        "created_at": job["created_at"],
        "web_state": job["web_state"],
        "status": status,
    }


# ─── Frontend estático (montado al final para no pisar /api) ─────────
@app.get("/")
def index():
    return FileResponse(os.path.join(_STATIC, "index.html"))


app.mount("/", StaticFiles(directory=_STATIC), name="static")
