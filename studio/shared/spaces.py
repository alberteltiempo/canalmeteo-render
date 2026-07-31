"""Cliente DO Spaces (S3-compatible) compartido.

Mismo patrón que scripts/radar_tile.py: intenta el perfil boto3 `do-tor1`
y, si no existe, cae a las variables de entorno DO_SPACES_KEY/SECRET.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Any, Optional

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from . import config as cfg

log = logging.getLogger("studio.spaces")


@lru_cache(maxsize=1)
def client():
    """Cliente S3 cacheado para DO Spaces.

    Orden de credenciales: 1) DO_SPACES_KEY/SECRET del entorno (nimbus, vía
    studio.env), 2) perfil boto3 `do-tor1` (calamarsa), 3) cadena por defecto.
    """
    common = dict(
        region_name=cfg.SPACES_REGION,
        endpoint_url=cfg.SPACES_ENDPOINT,
        config=Config(retries={"max_attempts": 3, "mode": "adaptive"}),
    )
    key = os.environ.get("DO_SPACES_KEY")
    secret = os.environ.get("DO_SPACES_SECRET")
    if key and secret:
        return boto3.client("s3", aws_access_key_id=key, aws_secret_access_key=secret, **common)
    try:
        return boto3.Session(profile_name=cfg.SPACES_PROFILE).client("s3", **common)
    except Exception:
        return boto3.client("s3", **common)


def public_url(key: str) -> str:
    return f"{cfg.CDN_BASE}/{key}"


# ─── JSON helpers (job.json / status.json) ───────────────────────────
def put_json(key: str, obj: Any, public: bool = False) -> None:
    client().put_object(
        Bucket=cfg.SPACES_BUCKET,
        Key=key,
        Body=json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
        CacheControl="no-cache, max-age=0",
        ACL="public-read" if public else "private",
    )


def get_json(key: str) -> Optional[dict]:
    try:
        resp = client().get_object(Bucket=cfg.SPACES_BUCKET, Key=key)
        return json.loads(resp["Body"].read())
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise


def exists(key: str) -> bool:
    try:
        client().head_object(Bucket=cfg.SPACES_BUCKET, Key=key)
        return True
    except ClientError:
        return False


# ─── Subida prefirmada (navegador → Spaces directo) ──────────────────
def presigned_put(key: str, expires: int = 3600, content_type: Optional[str] = None) -> str:
    """URL PUT firmada para que el navegador suba el origen sin pasar por nimbus."""
    params = {"Bucket": cfg.SPACES_BUCKET, "Key": key}
    if content_type:
        params["ContentType"] = content_type
    return client().generate_presigned_url("put_object", Params=params, ExpiresIn=expires)


# ─── Archivos (lado worker / calamarsa) ──────────────────────────────
def download(key: str, local_path: str) -> None:
    client().download_file(cfg.SPACES_BUCKET, key, local_path)


def upload_file(local_path: str, key: str, public: bool = True, content_type: Optional[str] = None) -> str:
    extra: dict = {"ACL": "public-read" if public else "private"}
    if content_type:
        extra["ContentType"] = content_type
    client().upload_file(local_path, cfg.SPACES_BUCKET, key, ExtraArgs=extra)
    return public_url(key)


def copy_within(src_key: str, dst_key: str, public: bool = True) -> str:
    """Copia servidor-a-servidor dentro del bucket (sin bajar el archivo)."""
    client().copy_object(
        Bucket=cfg.SPACES_BUCKET,
        CopySource={"Bucket": cfg.SPACES_BUCKET, "Key": src_key},
        Key=dst_key,
        ACL="public-read" if public else "private",
        MetadataDirective="COPY",
    )
    return public_url(dst_key)


def list_job_ids() -> list[str]:
    """Devuelve los job_id presentes bajo el prefijo studio/jobs/."""
    prefix = f"{cfg.STUDIO_PREFIX}/jobs/"
    paginator = client().get_paginator("list_objects_v2")
    ids: list[str] = []
    for page in paginator.paginate(Bucket=cfg.SPACES_BUCKET, Prefix=prefix, Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            ids.append(cp["Prefix"][len(prefix):].rstrip("/"))
    return ids
