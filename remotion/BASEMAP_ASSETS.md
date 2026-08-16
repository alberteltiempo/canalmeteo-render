# Assets cartográficos autoalojados (post-Mapbox, 2026-08-15)

Desde la migración a **MapLibre GL** (sin token, sin facturación), todos los mapas
renderizan con cartografía **Natural Earth** (dominio público) servida desde el
`public/basemap/` de cada proyecto. Cero peticiones externas durante el render.

## Contenido de `public/basemap/` (cada proyecto)

| Fichero | Fuente | Uso |
|---|---|---|
| `land.geojson` | ne_10m_land + ne_10m_minor_islands | relleno de tierra / línea de costa |
| `ocean.geojson` | ne_10m_ocean | atenuar raster sobre el mar (dimWater) |
| `bathymetry.geojson`* | ne_10m_bathymetry_A…L (12 bandas, prop `depth`) | color del océano por profundidad |
| `admin0.geojson` | ne_50m_admin_0_boundary_lines_land | fronteras de país |
| `admin1.geojson` | ne_10m_admin_1_states_provinces_lines | fronteras de estado/provincia |
| `lakes.geojson` | ne_50m_lakes (scalerank ≤ 3) | lagos grandes |
| `places.geojson` | ne_10m_populated_places_simple (sr ≤ 7) | rótulos de ciudades (props: name/sr/cap/pop) |
| `glyphs/Noto Sans Regular/*.pbf` | demotiles.maplibre.org | glifos para las capas de texto |
| `earth_equirect.jpg` | NASA Blue Marble (land_shallow_topo_2048) | mini-mapa localizador (huracanes) |

\* En los tiempo_* la batimetría sigue siendo el `public/bathymetry.geojson`
original (recorte CONUS) y el relieve `public/relief_conus.png`; en huracanes la
batimetría va en `public/basemap/` (recorte de las dos cuencas).

## Ventanas de recorte

- **huracanes** (Atlántico + Pacífico Oriental y Central): `-180 −10 5 66` (W S E N).
  Ampliada de −165 a −180 el 2026-08-16: las tormentas del Pacífico Central
  (CPHC, p. ej. Lala cp01) salían del recorte y se veía la costura sin batimetría.
- **tiempo_\*** (CONUS, los 9 proyectos comparten assets): `-142 2 -52 60`
  (idéntica a `RELIEF_RASTER_BOUNDS` de basemap.ts — deben coincidir)

## Regenerar (p. ej. para ampliar ventana o refrescar Natural Earth)

```bash
# 1) Descargar GeoJSON de Natural Earth
base=https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson
curl -LO $base/ne_10m_land.geojson   # … (ver tabla)

# 2) Recortar a la ventana (GDAL)
ogr2ogr -f GeoJSON -clipsrc W S E N -lco COORDINATE_PRECISION=4 out.geojson in.geojson

# 3) Batimetría: fusionar las 12 bandas añadiendo la propiedad depth
#    (0,200,1000,…,10000), ordenadas de somera a profunda (la profunda pinta encima).
# 4) places: filtrar scalerank<=7 y mapear props a {name, sr, cap, pop}.
```

El estilo vive en `src/lib/basemap.ts` de cada proyecto:
- huracanes → `buildTropStyle()` (look oscuro)
- tiempo_* → `buildSystemStyle()` (look "sistema TV": gris + relieve + batimetría)

Gotchas MapLibre v5: `preserveDrawingBuffer` va dentro de
`canvasContextAttributes`; no se pasa `projection` en el constructor (mercator es
el defecto); `map.resize()` SIEMPRE antes de `fitBounds` en Remotion.
