"""Worker de calamarsa: sondea Spaces, coge jobs pendientes y los procesa.

No se conecta a nimbus: lee job.json / escribe status.json en Spaces. Pensado
para un único worker por GPU (sin condiciones de carrera reales en el claim).
Arrancar con:  python -m studio.worker.poller
"""
from __future__ import annotations

import logging
import time
import traceback

from studio.shared import config as cfg
from studio.shared import schemas, spaces
from .pipeline import process

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("studio.worker")


def _set_status_fn(job_id: str):
    def set_status(state: str, progress: int, message: str, outputs=None, error=None):
        doc = schemas.new_status_doc(job_id, state, message)
        doc["progress"] = progress
        if outputs is not None:
            doc["outputs"] = outputs
        if error is not None:
            doc["error"] = error
        spaces.put_json(cfg.status_key(job_id), doc)
    return set_status


def claim_next() -> bool:
    """Coge el primer job pendiente. Devuelve True si procesó alguno."""
    for job_id in spaces.list_job_ids():
        status = spaces.get_json(cfg.status_key(job_id))
        if not status or status.get("state") != schemas.STATE_PENDING:
            continue

        job = spaces.get_json(cfg.job_doc_key(job_id))
        if not job:
            continue

        set_status = _set_status_fn(job_id)
        set_status(schemas.STATE_CLAIMED, 5, "Cogido por calamarsa")
        log.info("procesando job %s (%s)", job_id, job.get("source_filename"))
        try:
            outputs = process(job, set_status)
            set_status(schemas.STATE_DONE, 100, "Completado", outputs=outputs)
            log.info("job %s OK (%d outputs)", job_id, len(outputs))
        except Exception as e:
            log.error("job %s FALLÓ: %s\n%s", job_id, e, traceback.format_exc())
            set_status(schemas.STATE_ERROR, 100, "Error en el procesado", error=str(e))
        return True
    return False


def main() -> None:
    log.info("worker arrancado — bucket=%s poll=%ss", cfg.SPACES_BUCKET, cfg.POLL_INTERVAL)
    while True:
        try:
            if not claim_next():
                time.sleep(cfg.POLL_INTERVAL)
        except KeyboardInterrupt:
            log.info("parando worker")
            break
        except Exception as e:
            log.error("error en el bucle de sondeo: %s", e)
            time.sleep(cfg.POLL_INTERVAL)


if __name__ == "__main__":
    main()
