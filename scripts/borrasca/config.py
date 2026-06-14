#!/usr/bin/env python3
"""
Borrasca - Configuración Central
================================
Carga credenciales desde /opt/canalmeteo/.env y proporciona
funciones comunes para todos los scripts.
"""

import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

# =============================================
# RUTAS
# =============================================
BASE_DIR = Path('/opt/canalmeteo')
SCRIPTS_DIR = BASE_DIR / 'scripts' / 'borrasca'
DATA_DIR = BASE_DIR / 'data' / 'borrasca'
LOGS_DIR = Path('/var/log/borrasca')
ENV_FILE = BASE_DIR / '.env'

# Crear directorios si no existen
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# =============================================
# CARGAR .ENV
# =============================================
def load_env():
    """Carga variables del archivo .env"""
    env_vars = {}
    if ENV_FILE.exists():
        with open(ENV_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    value = value.strip('"').strip("'")
                    env_vars[key.strip()] = value
                    os.environ[key.strip()] = value
    return env_vars

ENV = load_env()

# =============================================
# CONFIGURACIÓN SPACES
# =============================================
SPACES_CONFIG = {
    'key': ENV.get('SPACES_ACCESS_KEY', ''),
    'secret': ENV.get('SPACES_SECRET_KEY', ''),
    'bucket': ENV.get('SPACES_BUCKET', 'canalmeteo-public'),
    'region': ENV.get('SPACES_REGION', 'sfo3'),
    'endpoint': ENV.get('SPACES_ENDPOINT', 'sfo3.digitaloceanspaces.com'),
}

SPACES_BASE_PATH = 'borrasca'

# =============================================
# LOGGING
# =============================================
def setup_logger(name: str, log_file: Optional[str] = None) -> logging.Logger:
    """Configura logger con archivo y consola."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    if not logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        if log_file:
            log_path = LOGS_DIR / log_file
            file_handler = logging.FileHandler(log_path)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
    
    return logger


# =============================================
# UPLOAD A SPACES CON BOTO3
# =============================================
_s3_client = None

def get_s3_client():
    """Obtiene cliente S3 para DigitalOcean Spaces."""
    global _s3_client
    
    if _s3_client is None:
        try:
            import boto3
            from botocore.config import Config
            
            _s3_client = boto3.client(
                's3',
                region_name=SPACES_CONFIG['region'],
                endpoint_url=f"https://{SPACES_CONFIG['endpoint']}",
                aws_access_key_id=SPACES_CONFIG['key'],
                aws_secret_access_key=SPACES_CONFIG['secret'],
                config=Config(signature_version='s3v4')
            )
        except ImportError:
            print("ERROR: boto3 no instalado. Ejecuta: pip install boto3")
            return None
    
    return _s3_client


def upload_to_spaces(
    data,
    remote_path: str,
    content_type: str = 'application/json',
    cache_control: str = 'max-age=300'
) -> bool:
    """
    Sube datos a DigitalOcean Spaces.
    
    Args:
        data: Contenido a subir (bytes, string o dict)
        remote_path: Ruta relativa dentro de borrasca/
        content_type: Tipo MIME
        cache_control: Header de cache
    
    Returns:
        True si fue exitoso
    """
    if isinstance(data, dict):
        data = json.dumps(data, ensure_ascii=False, indent=2)
    if isinstance(data, str):
        data = data.encode('utf-8')
    
    full_path = f"{SPACES_BASE_PATH}/{remote_path}"
    
    s3 = get_s3_client()
    if s3 is None:
        return False
    
    try:
        s3.put_object(
            Bucket=SPACES_CONFIG['bucket'],
            Key=full_path,
            Body=data,
            ContentType=content_type,
            CacheControl=cache_control,
            ACL='public-read'
        )
        return True
        
    except Exception as e:
        print(f"Error uploading to Spaces: {e}")
        return False


def get_spaces_url(remote_path: str) -> str:
    """Devuelve la URL pública de un archivo en Spaces."""
    return f"https://{SPACES_CONFIG['bucket']}.{SPACES_CONFIG['endpoint']}/{SPACES_BASE_PATH}/{remote_path}"


# =============================================
# UTILIDADES
# =============================================
def download_json(url: str, timeout: int = 60) -> Optional[dict]:
    """Descarga y parsea JSON desde una URL."""
    try:
        headers = {'User-Agent': 'Borrasca/1.0 (canalmeteo.tv)'}
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error downloading {url}: {e}")
        return None


def download_binary(url: str, timeout: int = 180) -> Optional[bytes]:
    """Descarga contenido binario desde una URL."""
    try:
        headers = {'User-Agent': 'Borrasca/1.0 (canalmeteo.tv)'}
        response = requests.get(url, headers=headers, timeout=timeout, stream=True)
        response.raise_for_status()
        return response.content
    except Exception as e:
        print(f"Error downloading {url}: {e}")
        return None


def utcnow() -> datetime:
    """Devuelve datetime UTC actual (sin deprecation warning)."""
    return datetime.now(timezone.utc)


if __name__ == '__main__':
    print("=== Borrasca Config Test ===")
    print(f"Base Dir: {BASE_DIR}")
    print(f"Spaces Bucket: {SPACES_CONFIG['bucket']}")
    print(f"Spaces Region: {SPACES_CONFIG['region']}")
    print(f"Spaces Key: {SPACES_CONFIG['key'][:10]}..." if SPACES_CONFIG['key'] else "Spaces Key: NOT SET")
    print(f"ENV file exists: {ENV_FILE.exists()}")
    
    print("\n=== Test Upload ===")
    test_data = {"test": True, "timestamp": utcnow().isoformat()}
    if upload_to_spaces(test_data, "test/config-test.json"):
        print(f"✅ Upload OK: {get_spaces_url('test/config-test.json')}")
    else:
        print("❌ Upload FAILED")
