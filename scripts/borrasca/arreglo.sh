cd /opt/canalmeteo/scripts/borrasca
source /opt/canalmeteo/venv/bin/activate

python3 << 'EOF'
import boto3
from config import SPACES_CONFIG, SPACES_BASE_PATH

client = boto3.client(
    's3',
    endpoint_url=f"https://{SPACES_CONFIG['endpoint']}",
    aws_access_key_id=SPACES_CONFIG['key'],
    aws_secret_access_key=SPACES_CONFIG['secret'],
    region_name=SPACES_CONFIG['region']
)

bucket = SPACES_CONFIG['bucket']
prefix = f"{SPACES_BASE_PATH}/radar/tiles/"

print(f"Arreglando permisos en {bucket}/{prefix}...")

paginator = client.get_paginator('list_objects_v2')
count = 0

for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
    for obj in page.get('Contents', []):
        key = obj['Key']
        try:
            client.put_object_acl(Bucket=bucket, Key=key, ACL='public-read')
            count += 1
            if count % 500 == 0:
                print(f"  {count} objetos procesados...")
        except Exception as e:
            print(f"Error en {key}: {e}")

print(f"\n✅ Total: {count} objetos con permisos públicos")
EOF
