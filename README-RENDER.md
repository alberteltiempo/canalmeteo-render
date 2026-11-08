# Renders de antena (Remotion) · cómo se trabaja desde el 07/11/2026

Este repo es el **árbol vivo de nimbus-03** (`/opt/canalmeteo`): lo que hay en `main`
es lo que renderiza el cron cada hora. El checkout de trabajo está en **nimbus-01**
`/opt/canalmeteo/render` y se despliega con un empujón; nadie edita a mano en nimbus-03.

```bash
cd /opt/canalmeteo/render
# editar… y probar la sintaxis TS en nimbus-03 antes de desplegar si se tocó un proyecto:
ssh nimbus-03 'cd /opt/canalmeteo/remotion/tiempo_SP && sudo -u canalmeteo ./node_modules/.bin/tsc --noEmit'
git commit -am "qué y por qué"
git push nimbus03 main            # despliega en nimbus-03 (receive.denyCurrentBranch=updateInstead)
git push origin main:produccion   # GitHub alberteltiempo/canalmeteo-render (rama `produccion`)
```

- El empujón lo hace root por SSH; los ficheros nuevos quedan de root. Si un proceso
  de `canalmeteo` tiene que escribirlos, `chown canalmeteo:canalmeteo` tras desplegar.
- Si en nimbus-03 hay cambios a mano, el empujón se niega: mirar `git status` allí y
  decidir (recuperar y cometer aquí, o descartar). No forzar.
- En GitHub, `main` conserva la historia vieja (solo remotion, hasta 09/2026) y
  `produccion` es la real; falta que Albert cambie la rama por defecto.

## Qué hay

| Carpeta | Qué es |
|---|---|
| `remotion/tiempo_CONUS` + `tiempo_{NE,FL,SP,MW,NP,NW,SW,SE}` | Vistazo al Tiempo (9 segmentos horarios; los regionales son forks de CONUS) |
| `remotion/huracanes` | Vistazo al Trópico (por boletín NHC) |
| `remotion/parques-webcams` | Parques Webcams (4 grupos, :30) |
| `scripts/` | render_guardian, nhc_check_and_render, escaleta_preview_worker, feeds_watchdog, webcam_scraper, parques_lynx, conus_lynx, upload_to_dropbox, playout_encode… |
| `scripts/*_pipeline.py` sueltos | copias viejas: la versión real corre desde `/opt/canalmeteo/repo` (repo nimbus-scripts) |

## Escaleta, tema y música (piloto: tiempo_SP)

Cada proyecto lee en cada render `CDN/data/escaleta/<slug>.json` (lo publica el editor
de la intranet). Desde la fase 1 (07/11/2026) **tiempo_SP** además entiende:

- `theme.colors.{navy,navyDark,navyDeep,blue,blueVivid,orange,white,alertRed,alertRedDeep}`
  y `theme.alerts.{tornado,tormenta,inundacion,calor,invierno,costera,viento,fuego}`:
  hex de 6 dígitos; se aplican en `applyThemeRuntime` (lib/theme.ts) partiendo
  SIEMPRE de los valores de código. Clave desconocida o color inválido → se ignora.
- `music.{file,volume,fadeIn,fadeOut}`: `file` es una pista de la biblioteca
  (`CDN/data/escaleta/audio/`, que `render.sh` copia a `public/audio/lib/` antes de
  renderizar), `"default"` (la de código) o `"none"`. `resolveMusic` (lib/cdn.ts)
  comprueba por HEAD que la pista existe en el bundle; si no, usa la de código.
  Volumen 0–1 (código 0,22), fundidos 0–10 s.

Biblioteca: la intranet deja los MP3 en `/opt/canalmeteo/escaleta/outbox/audio_in`
(nimbus-01) y `scripts/escaleta_audio.py` (repo nimbus-scripts, cada minuto) los
normaliza a −14 LUFS y publica `index.json`.

Para probar sin tocar antena: copia del proyecto en `/opt/canalmeteo/data/temp/` con
`ESCALETA_SLUG` apuntando a `tiempo-sp-test` y `render.sh --no-upload`.

## Motor único `remotion/tiempo` (fase 2, 08/11/2026)

Un solo proyecto para los 9 segmentos «Vistazo al Tiempo». Lo que cambia de una
región a otra vive en `src/regions/<id>.ts` (encuadre, estados, catálogos de
ciudades/aeropuertos/servicios/máximas, bbox de sismos, empujones y lados forzados
de las cajas, rótulos, sufijo de feed, escala de la variación térmica, música de
código). `applyRegionRuntime(id)` (lib/cdn.ts) rellena los globales antes de cada
composición; `Root.tsx` registra por región:

- el segmento con el **id de siempre** (`ConusSegment`, `SpSegment`, …): los
  render.sh no cambian de composición, solo de `PROJECT_DIR`;
- los stills y previews con prefijo `<región>-` (`sp-Prev-condiciones`,
  `conus-Mockup-tmax-hoy`). Los solo-CONUS (severo en vivo, mínimas, outlooks, humo)
  existen solo con prefijo `conus-`.

**Pasar una región al motor único** (una a una, con rollback trivial):

1. Paridad: `data/temp/paridad_<reg>.sh` en nimbus-03 renderiza los mismos stills con
   el fork y con el motor y compara (PSNR). Revisar a ojo las diferencias conocidas
   (ver abajo).
2. `remotion/tiempo_<REG>/render.sh`: `PROJECT_DIR="/opt/canalmeteo/remotion/tiempo"`
   (la composición sigue igual). Rollback = volver a poner la ruta del fork.
3. `scripts/escaleta_preview_worker.py`: añadir el slug a `UNIFIED` (proyecto `tiempo`,
   still con prefijo). Para CONUS, también `scripts/conus_lynx.py` (PROY_CONUS y
   prefijo `conus-`).
4. Cuando todas estén migradas: borrar los forks `tiempo_<REG>/src` (dejar render.sh).

Diferencias asumidas al unificar (no son errores): los regionales heredan el estilo
de chips más reciente (bordes 1-2 px más gruesos) y CONUS/NE conservan la escala
«coarse» (±12 °F) de la variación de temperatura mientras el resto usa «fine» (±8 °F);
NE pierde el sufijo «· EE. UU.» de los subtítulos (como el resto de regionales).
