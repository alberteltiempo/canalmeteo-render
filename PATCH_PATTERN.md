# Patrón de patch para aislar scripts en sandbox

## Regla
Cualquier path S3 hardcoded debe respetar `CDN_PREFIX`.

## Antes
```python
's3_path': 'data/cities/weather.json',
'public_url': 'https://canalmeteo-public.sfo3.cdn.digitaloceanspaces.com/data/cities/weather.json',
```

## Después
```python
's3_path': os.environ.get('CDN_PREFIX', '') + 'data/cities/weather.json',
'public_url': 'https://canalmeteo-public.sfo3.cdn.digitaloceanspaces.com/' + os.environ.get('CDN_PREFIX', '') + 'data/cities/weather.json',
```

## Por qué es retrocompatible
- Sin CDN_PREFIX (producción): `os.environ.get('CDN_PREFIX', '')` = `''` → path original
- Con CDN_PREFIX=sandbox/ (sandbox): path queda bajo `sandbox/`

## Workflow
1. cp script.py script.py.bak-before-prefix-patch
2. grep -n "s3://\|s3_path\|public_url" script.py  (encuentra los hardcodes)
3. sed -i o edición manual con el patrón arriba
4. cm-run script.py  (verifica que el log diga "sandbox/")
5. curl al CDN sandbox para confirmar

## Aplicado a
- cities_weather_pipeline.py  (2026-05-20)
