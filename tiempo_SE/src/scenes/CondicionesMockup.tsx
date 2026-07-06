import React, { useEffect, useRef, useState } from "react";
import {
  AbsoluteFill,
  continueRender,
  delayRender,
  staticFile,
  useVideoConfig,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/Outfit";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { MAPBOX_TOKEN, CONUS_VIEW, CONUS_PAD } from "../lib/cdn";
import {
  setWaterColor,
  setLandColor,
  addReliefRaster,
  addBathymetry,
  addCoastBorder,
  raiseBorders,
  hideAutoLabels,
} from "../lib/basemap";
import { TopicBar } from "../components/Overlay";

const { fontFamily } = loadFont();

// ─────────────────────────────────────────────────────────────
// MOCKUP "Condiciones ahora"  (Still → PNG, para pulir el diseño)
// ─────────────────────────────────────────────────────────────
// Objetivo: decidir el LOOK antes de cablear datos reales. Lleva:
//   1) base cartográfica "sistema TV" (gris + relieve + batimetría)
//   2) una CAPA DE TEMPERATURA falsa (gradiente meteorológico) que simula el
//      raster NBM que después generará el pipeline (data/nbm/temp)
//   3) CAJAS por ciudad con símbolo + temperatura + viento
// Cuando esté pulido, se reimplementa como escena con la capa NBM real.

// Unidad de temperatura. Canal en español → °C. Cambiar a "F" si se decide
// rotular en Fahrenheit (audiencia EE. UU.).
const UNIT = "F" as "C" | "F";

type Sky = "sol" | "nubes-claros" | "nublado" | "lluvia" | "tormenta" | "nieve";
type Cond = {
  name: string;
  lon: number;
  lat: number;
  tempC: number; // temperatura en °C (se convierte al rotular)
  sky: Sky;
  windKmh: number;
  windDeg: number; // dirección a la que APUNTA la flecha (downwind), en grados
};

// Datos de muestra (verano típico) para juzgar el diseño, no son reales. El orden
// es PRIORIDAD: las primeras eligen mejor hueco al colocar las cajas (anti-solape).
const SAMPLE: Cond[] = [
  { name: "Nueva York", lon: -74.01, lat: 40.71, tempC: 27, sky: "nubes-claros", windKmh: 14, windDeg: 45 },
  { name: "Los Ángeles", lon: -118.24, lat: 34.05, tempC: 26, sky: "sol", windKmh: 10, windDeg: 45 },
  { name: "Chicago", lon: -87.63, lat: 41.88, tempC: 25, sky: "lluvia", windKmh: 18, windDeg: 225 },
  { name: "Houston", lon: -95.37, lat: 29.76, tempC: 32, sky: "nubes-claros", windKmh: 16, windDeg: 315 },
  { name: "Miami", lon: -80.19, lat: 25.76, tempC: 31, sky: "tormenta", windKmh: 22, windDeg: 270 },
  { name: "Dallas", lon: -96.8, lat: 32.78, tempC: 33, sky: "sol", windKmh: 20, windDeg: 0 },
  { name: "Washington", lon: -77.04, lat: 38.91, tempC: 29, sky: "sol", windKmh: 12, windDeg: 0 },
  { name: "Atlanta", lon: -84.39, lat: 33.75, tempC: 30, sky: "tormenta", windKmh: 10, windDeg: 0 },
  { name: "Seattle", lon: -122.33, lat: 47.61, tempC: 18, sky: "nublado", windKmh: 12, windDeg: 135 },
  { name: "Denver", lon: -104.99, lat: 39.74, tempC: 24, sky: "tormenta", windKmh: 14, windDeg: 180 },
  { name: "Phoenix", lon: -112.07, lat: 33.45, tempC: 38, sky: "sol", windKmh: 8, windDeg: 0 },
  { name: "San Francisco", lon: -122.42, lat: 37.77, tempC: 17, sky: "nubes-claros", windKmh: 18, windDeg: 90 },
  { name: "Mineápolis", lon: -93.27, lat: 44.98, tempC: 23, sky: "nubes-claros", windKmh: 12, windDeg: 135 },
  { name: "Kansas City", lon: -94.58, lat: 39.1, tempC: 31, sky: "nubes-claros", windKmh: 16, windDeg: 45 },
  { name: "Salt Lake City", lon: -111.89, lat: 40.76, tempC: 32, sky: "sol", windKmh: 10, windDeg: 180 },
  { name: "Albuquerque", lon: -106.65, lat: 35.08, tempC: 33, sky: "sol", windKmh: 12, windDeg: 0 },
  { name: "Cleveland", lon: -81.69, lat: 41.5, tempC: 24, sky: "lluvia", windKmh: 14, windDeg: 225 },
  { name: "Bismarck", lon: -100.78, lat: 46.81, tempC: 27, sky: "sol", windKmh: 18, windDeg: 90 },
];

// Paleta de temperatura (estilo meteo). Devuelve color por °C.
function tempColor(c: number): string {
  const stops: [number, string][] = [
    [-10, "#7c4dff"],
    [0, "#3d7bff"],
    [8, "#21b6c9"],
    [15, "#2ecc71"],
    [22, "#f4d03f"],
    [28, "#ef8e2d"],
    [34, "#e74c3c"],
    [42, "#c0298a"],
  ];
  if (c <= stops[0][0]) return stops[0][1];
  if (c >= stops[stops.length - 1][0]) return stops[stops.length - 1][1];
  for (let i = 0; i < stops.length - 1; i++) {
    const [a, ca] = stops[i];
    const [b, cb] = stops[i + 1];
    if (c >= a && c <= b) {
      const t = (c - a) / (b - a);
      return lerpColor(ca, cb, t);
    }
  }
  return stops[stops.length - 1][1];
}

function lerpColor(a: string, b: string, t: number): string {
  const pa = hex(a),
    pb = hex(b);
  const r = Math.round(pa[0] + (pb[0] - pa[0]) * t);
  const g = Math.round(pa[1] + (pb[1] - pa[1]) * t);
  const bl = Math.round(pa[2] + (pb[2] - pa[2]) * t);
  return `rgb(${r},${g},${bl})`;
}
function hex(h: string): [number, number, number] {
  const m = h.replace("#", "");
  return [parseInt(m.slice(0, 2), 16), parseInt(m.slice(2, 4), 16), parseInt(m.slice(4, 6), 16)];
}

function fmtTemp(c: number): string {
  const v = UNIT === "F" ? Math.round((c * 9) / 5 + 32) : Math.round(c);
  return `${v}°`;
}

// ── Iconos de cielo (SVG inline; fiables en headless, sin depender de emoji) ──
const SkyIcon: React.FC<{ sky: Sky; size?: number }> = ({ sky, size = 38 }) => {
  const s = size;
  const sun = "#FFC83D";
  const cloud = "#E7EDF2";
  const cloudDark = "#B7C2cc";
  const drop = "#5BA6FF";
  const bolt = "#FFD23D";
  const snow = "#DDE9F5";
  const Cloud = ({ x = 0, y = 0, fill = cloud }: { x?: number; y?: number; fill?: string }) => (
    <path
      d={`M${x + 7} ${y + 22} a7 7 0 0 1 1 -13 a9 9 0 0 1 17 -2 a6 6 0 0 1 2 15 z`}
      fill={fill}
    />
  );
  return (
    <svg width={s} height={s} viewBox="0 0 36 36" style={{ display: "block" }}>
      {sky === "sol" && (
        <>
          {[...Array(8)].map((_, i) => (
            <rect
              key={i}
              x={17}
              y={2}
              width={2}
              height={6}
              rx={1}
              fill={sun}
              transform={`rotate(${i * 45} 18 18)`}
            />
          ))}
          <circle cx={18} cy={18} r={8} fill={sun} />
        </>
      )}
      {sky === "nubes-claros" && (
        <>
          {[...Array(8)].map((_, i) => (
            <rect key={i} x={11} y={1} width={1.6} height={4.5} rx={1} fill={sun} transform={`rotate(${i * 45} 12 12)`} />
          ))}
          <circle cx={12} cy={12} r={6} fill={sun} />
          <Cloud x={6} y={9} />
        </>
      )}
      {sky === "nublado" && (
        <>
          <Cloud x={2} y={4} fill={cloudDark} />
          <Cloud x={8} y={9} />
        </>
      )}
      {sky === "lluvia" && (
        <>
          <Cloud x={5} y={3} />
          {[10, 17, 24].map((x) => (
            <rect key={x} x={x} y={26} width={2.4} height={7} rx={1.2} fill={drop} transform={`rotate(15 ${x} 28)`} />
          ))}
        </>
      )}
      {sky === "tormenta" && (
        <>
          <Cloud x={5} y={3} fill={cloudDark} />
          <polygon points="18,25 13,33 17,33 14,40 24,30 19,30 22,25" fill={bolt} />
        </>
      )}
      {sky === "nieve" && (
        <>
          <Cloud x={5} y={3} />
          {[11, 18, 25].map((x) => (
            <text key={x} x={x} y={33} fontSize="9" fill={snow} textAnchor="middle">
              ❄
            </text>
          ))}
        </>
      )}
    </svg>
  );
};

// Caja de condición por ciudad (símbolo + temperatura + nombre + viento).
const CondBox: React.FC<{ c: Cond }> = ({ c }) => {
  const accent = tempColor(c.tempC);
  return (
    <div
      style={{
        background: "rgba(13,24,34,0.86)",
        border: "1px solid rgba(255,255,255,0.16)",
        borderLeft: `4px solid ${accent}`,
        borderRadius: 12,
        padding: "8px 12px 9px 11px",
        boxShadow: "0 10px 26px rgba(0,0,0,0.5)",
        backdropFilter: "blur(2px)",
        minWidth: 132,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
        <SkyIcon sky={c.sky} size={46} />
        <span
          style={{
            fontSize: 42,
            fontWeight: 800,
            color: "#fff",
            lineHeight: 1,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {fmtTemp(c.tempC)}
        </span>
      </div>
      <div style={{ fontSize: 23, fontWeight: 700, color: "#fff", marginTop: 5, whiteSpace: "nowrap" }}>
        {c.name}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 7, marginTop: 3 }}>
        <span
          style={{
            display: "inline-block",
            fontSize: 20,
            color: "#cfe0ee",
            transform: `rotate(${c.windDeg}deg)`,
          }}
        >
          ↑
        </span>
        <span style={{ fontSize: 20, color: "rgba(255,255,255,0.85)" }}>
          {Math.round(c.windKmh / 1.609)} mph
        </span>
      </div>
    </div>
  );
};

type Rect = { x0: number; y0: number; x1: number; y1: number };
// x,y = punto de la ciudad (donde va el localizador). bx,by = centro de la caja.
type Placed = Cond & { x: number; y: number; bx: number; by: number };

// Tamaño aproximado de la caja (para el cálculo de solapes). Depende del nombre.
function estimateBox(c: Cond): { w: number; h: number } {
  const nameW = c.name.length * 13 + 24;
  const w = 23 + Math.max(150, nameW, 96);
  return { w, h: 122 };
}

// Área de intersección de dos rectángulos (0 si no se tocan).
function overlapArea(a: Rect, b: Rect, pad = 6): number {
  const ix = Math.min(a.x1, b.x1 + pad) - Math.max(a.x0, b.x0 - pad);
  const iy = Math.min(a.y1, b.y1 + pad) - Math.max(a.y0, b.y0 - pad);
  return ix > 0 && iy > 0 ? ix * iy : 0;
}

// Coloca cada caja eligiendo, por orden de prioridad, la primera posición (arriba/
// abajo/lados/diagonales del punto) sin solape con las ya colocadas ni con los
// bordes/título/leyenda. Si ninguna es perfecta, elige la de menor penalización.
function placeBoxes(
  cities: (Cond & { x: number; y: number })[],
  W: number,
  H: number
): Placed[] {
  const margin = 24;
  const top = 110; // bajo la barra de título
  const bottom = H - 56;
  const gap = 16;
  const taken: Rect[] = [];
  const out: Placed[] = [];

  for (const c of cities) {
    const { w, h } = estimateBox(c);
    const cands: [number, number][] = [
      [c.x, c.y - gap - h / 2], // arriba
      [c.x, c.y + gap + h / 2], // abajo
      [c.x + gap + w / 2, c.y], // derecha
      [c.x - gap - w / 2, c.y], // izquierda
      [c.x + gap + w / 2, c.y - gap - h / 2], // arriba-dcha
      [c.x - gap - w / 2, c.y - gap - h / 2], // arriba-izq
      [c.x + gap + w / 2, c.y + gap + h / 2], // abajo-dcha
      [c.x - gap - w / 2, c.y + gap + h / 2], // abajo-izq
    ];
    let best: { cx: number; cy: number; rect: Rect } | null = null;
    let bestScore = Infinity;
    for (const [cx0, cy0] of cands) {
      // Clampa el centro para que la caja quepa dentro de los límites.
      const cx = Math.max(margin + w / 2, Math.min(W - margin - w / 2, cx0));
      const cy = Math.max(top + h / 2, Math.min(bottom - h / 2, cy0));
      const rect: Rect = { x0: cx - w / 2, y0: cy - h / 2, x1: cx + w / 2, y1: cy + h / 2 };
      let overlap = 0;
      for (const t of taken) overlap += overlapArea(rect, t);
      // Penaliza también el desvío del clamp (preferimos no tener que recolocar).
      const drift = Math.abs(cx - cx0) + Math.abs(cy - cy0);
      const score = overlap * 4 + drift;
      if (score < bestScore) {
        bestScore = score;
        best = { cx, cy, rect };
      }
      if (score === 0) break;
    }
    if (best) {
      taken.push(best.rect);
      out.push({ ...c, bx: best.cx, by: best.cy });
    }
  }
  return out;
}

export const CondicionesMockup: React.FC = () => {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const [placed, setPlaced] = useState<Placed[]>([]);
  const { width, height } = useVideoConfig();

  useEffect(() => {
    if (!ref.current) return;
    const handle = delayRender("condiciones-mockup");
    mapboxgl.accessToken = MAPBOX_TOKEN;

    const map = new mapboxgl.Map({
      container: ref.current,
      style: "mapbox://styles/mapbox/dark-v11",
      center: [-96, 38],
      zoom: 3.4,
      interactive: false,
      attributionControl: false,
      preserveDrawingBuffer: true,
      fadeDuration: 0,
      projection: "mercator",
    });
    mapRef.current = map;

    map.on("load", () => {
      // Base "sistema TV" (mismos helpers que el mockup de base).
      setLandColor(map, "#c6c9cb");
      setWaterColor(map, "#5aa9e2");
      addReliefRaster(map, staticFile("relief_conus.png"));
      addBathymetry(map, staticFile("bathymetry.geojson"));
      addCoastBorder(map, "rgba(55,65,75,0.9)", 1.2);
      raiseBorders(map, "rgba(70,80,90,0.85)", 0.85);
      hideAutoLabels(map);

      map.resize();
      const cam = map.cameraForBounds(CONUS_VIEW, { padding: CONUS_PAD });
      if (cam) map.jumpTo(cam);
      else map.fitBounds(CONUS_VIEW, { animate: false });

      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        // Proyecta cada ciudad a píxeles y coloca las cajas sin solape.
        const projected = SAMPLE.map((c) => {
          const p = map.project([c.lon, c.lat]);
          return { ...c, x: p.x, y: p.y };
        });
        setPlaced(placeBoxes(projected, width, height));
        map.off("idle", finish);
        clearTimeout(fb);
        continueRender(handle);
      };
      map.on("idle", finish);
      const fb = setTimeout(finish, 90000);
    });

    return () => {
      try {
        continueRender(handle);
      } catch {
        /* noop */
      }
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [width, height]);

  return (
    <AbsoluteFill style={{ background: "#000", fontFamily }}>
      <style>{`.mapboxgl-ctrl-logo,.mapboxgl-ctrl-attrib,.mapboxgl-ctrl-bottom-left,.mapboxgl-ctrl-bottom-right{display:none !important;}`}</style>
      <div ref={ref} style={{ position: "absolute", inset: 0 }} />

      {/* CAPA DE TEMPERATURA (FALSA): gradiente meteorológico que simula el raster
          NBM. Norte frío (verde/azul) → sur cálido (naranja/rojo) + SW desértico
          muy cálido y Rockies frescas. Se sustituirá por el PNG NBM real. */}
      <AbsoluteFill
        style={{
          pointerEvents: "none",
          opacity: 0.72,
          background:
            // SW desértico muy cálido (rojo) y Texas/sureste cálido
            "radial-gradient(38% 42% at 30% 70%, rgba(220,50,47,0.95) 0%, rgba(231,90,60,0.55) 55%, rgba(244,180,60,0.0) 100%)," +
            "radial-gradient(42% 40% at 70% 82%, rgba(231,76,60,0.85) 0%, rgba(244,180,60,0.4) 55%, rgba(244,208,63,0.0) 100%)," +
            // Rockies/norte frescos (azul-verde)
            "radial-gradient(46% 50% at 80% 22%, rgba(33,150,201,0.8) 0%, rgba(46,180,160,0.45) 55%, rgba(46,204,113,0.0) 100%)," +
            "radial-gradient(34% 44% at 24% 40%, rgba(33,182,201,0.6) 0%, rgba(46,204,113,0.0) 70%)," +
            // base sur cálido → norte frío
            "linear-gradient(180deg, rgba(61,123,255,0.7) 0%, rgba(46,204,113,0.45) 34%, rgba(244,208,63,0.5) 62%, rgba(239,142,45,0.62) 100%)",
        }}
      />

      {/* Viñeta para legibilidad de cajas y barras */}
      <AbsoluteFill
        style={{
          pointerEvents: "none",
          background:
            "linear-gradient(180deg, rgba(0,0,0,0.45) 0%, rgba(0,0,0,0) 18%, rgba(0,0,0,0) 82%, rgba(0,0,0,0.5) 100%)",
        }}
      />

      {/* Cajas por ciudad: caja colocada sin solape (bx,by) + punto sobre la coord. */}
      {placed.map((c) => (
        <React.Fragment key={c.name}>
          <div style={{ position: "absolute", left: c.bx, top: c.by, transform: "translate(-50%, -50%)" }}>
            <CondBox c={c} />
          </div>
          <div
            style={{
              position: "absolute",
              left: c.x,
              top: c.y,
              width: 12,
              height: 12,
              borderRadius: "50%",
              background: "#fff",
              border: "2px solid rgba(0,0,0,0.6)",
              boxShadow: "0 0 6px rgba(0,0,0,0.6)",
              transform: "translate(-50%, -50%)",
            }}
          />
        </React.Fragment>
      ))}

      <TopicBar topic="CONDICIONES AHORA" sub="TEMPERATURA Y VIENTO" topicColor="#F39C12" opacity={1} />

      {/* Leyenda de temperatura (colorbar) */}
      <div
        style={{
          position: "absolute",
          right: 48,
          bottom: 40,
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-end",
          gap: 6,
        }}
      >
        <div style={{ color: "#fff", fontSize: 18, fontWeight: 700, opacity: 0.9 }}>
          Temperatura {UNIT === "F" ? "(°F)" : "(°C)"}
        </div>
        <div
          style={{
            width: 360,
            height: 14,
            borderRadius: 7,
            border: "1px solid rgba(255,255,255,0.3)",
            background:
              "linear-gradient(90deg,#7c4dff 0%,#3d7bff 16%,#21b6c9 30%,#2ecc71 44%,#f4d03f 60%,#ef8e2d 74%,#e74c3c 88%,#c0298a 100%)",
          }}
        />
        <div style={{ width: 360, display: "flex", justifyContent: "space-between", color: "#dfe8f0", fontSize: 14 }}>
          <span>{UNIT === "F" ? "14°" : "-10°"}</span>
          <span>{UNIT === "F" ? "60°" : "16°"}</span>
          <span>{UNIT === "F" ? "108°" : "42°"}</span>
        </div>
      </div>
    </AbsoluteFill>
  );
};
