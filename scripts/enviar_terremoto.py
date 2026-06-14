#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, base64, mimetypes, json
import requests

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL       = os.getenv("FROM_EMAIL")
TO_EMAILS        = [e.strip() for e in os.getenv("TO_EMAILS", "").split(",") if e.strip()]

if not SENDGRID_API_KEY or not FROM_EMAIL or not TO_EMAILS:
    print("❌ Faltan variables: SENDGRID_API_KEY, FROM_EMAIL o TO_EMAILS en sendgrid.env")
    sys.exit(1)

# Archivos a adjuntar pasados como argumentos
attachments = []
for path in sys.argv[1:]:
    if not os.path.exists(path):
        print(f"⚠️ No existe {path}, se omite.")
        continue
    ctype, _ = mimetypes.guess_type(path)
    if ctype is None:
        ctype = "application/octet-stream"
    with open(path, "rb") as f:
        data_b64 = base64.b64encode(f.read()).decode("utf-8")
    attachments.append({
        "content": data_b64,
        "type": ctype,
        "filename": os.path.basename(path),
        "disposition": "attachment"
    })

subject = "🌍 Alerta terremoto (magnitud ≥ 7)"
html = """<h2>Evento sísmico detectado</h2>
<p>Se adjuntan capturas y HTML generado.</p>"""

payload = {
    "personalizations": [{
        "to": [{"email": e} for e in TO_EMAILS],
        "subject": subject
    }],
    "from": {"email": FROM_EMAIL},
    "content": [{"type": "text/html", "value": html}],
}

if attachments:
    payload["attachments"] = attachments

headers = {
    "Authorization": f"Bearer {SENDGRID_API_KEY}",
    "Content-Type": "application/json"
}

try:
    r = requests.post("https://api.sendgrid.com/v3/mail/send",
                      headers=headers, data=json.dumps(payload), timeout=30)
    if 200 <= r.status_code < 300:
        print(f"📤 Correo enviado a {', '.join(TO_EMAILS)} (status {r.status_code})")
    else:
        print(f"❌ Error SendGrid: {r.status_code} {r.text}")
        sys.exit(1)
except Exception as e:
    print(f"❌ Excepción enviando correo: {e}")
    sys.exit(1)
