# Canal Meteo TV — Vistazo al Trópico (Remotion)

Segmento de huracanes que renderiza un timeline dinámico según las tormentas
activas leídas de `active_storms.json` del CDN.

## Estructura

```
huracanes/
├── package.json          Remotion 4.0.452 (alineado a parques)
├── remotion.config.ts
├── render.sh             --scale=1, --concurrency=3 (sfo3-c)
└── src/
    ├── index.ts
    ├── Root.tsx          Composition "TropicoSegment" + calculateMetadata
    ├── types.ts          esquemas Zod del índice tropical + plan de escenas
    ├── TropicoSegment.tsx  arma el Series desde el plan
    ├── lib/
    │   ├── cdn.ts        CDN, fetch del índice, buildScenePlan, duraciones
    │   ├── tropical.ts   catKeyFromKt, ktToMph, etiquetas (idénticos al frontend)
    │   ├── theme.ts      tokens de marca + colores categoría/avisos/radios
    │   └── sun.ts        día/noche para GeoColor vs IR
    ├── components/       Open, Outro, DataCard, ScenePlaceholder
    └── scenes/           SatelliteGlobal, StormSatellite, StormTrack,
                          StormHazards, StormRain, GenesisAreas
```

## Uso

```bash
npm install          # instala Remotion + deps
npm run dev          # abre Remotion Studio (preview frame a frame)
npm run render       # render local a out/Tropico_2026.mp4
# o en sfo3-c:
bash render.sh
```

## Estado (Fase 1)

- ✅ Open rojo + logo + "Vistazo al Trópico"
- ✅ `calculateMetadata` lee `active_storms.json` y arma el timeline dinámico
  (N tormentas → N×4 escenas; áreas de desarrollo si las hay)
- ✅ Tarjeta de datos con valores reales (nombre, categoría, viento mph)
- ⏳ Escenas como placeholders funcionales (satélite, trayectoria, peligros,
      lluvia, génesis) — se construyen una a una.

## Pendiente (fases siguientes)

1. Satélite Mapbox GL + GIBS (GOES-East), animación 3h/18 frames @10min,
   GeoColor día / IR noche, `delayRender` al cargar tiles, `flyTo` por tormenta.
2. Trayectoria/cono/puntos/avisos (ww)/arrival con leyenda unificada.
3. Peligros con recomendaciones según tipo de aviso.
4. Lluvia 96h: NBM (EEUU, ya en CDN) + **GFS (México/Caribe, runner pendiente)**.
5. Áreas de desarrollo (genesis) con bins NHC.

## Datos (todo del CDN)

- `https://canalmeteo-public.sfo3.digitaloceanspaces.com/data/tropical/active_storms.json`
- Por tormenta: `s.layers.{cone,track,points,forecast_radii,ww,arrival_*,past_*}`
- Modelos: `data/nbm/nbm_f###.json` (+ manifest). GFS pendiente.
