import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { loadFont } from "@remotion/google-fonts/Outfit";
import { MapPolygon, MapLine, MapDot } from "../components/SatMap";
import { MapScene, Legend } from "./SurfaceScenes";
import { palette } from "../lib/theme";
import { GlmData, MrmsMesh, SpcWatchesData } from "../lib/cdn";
import { ThemeMode } from "../types";

const { fontFamily } = loadFont();

// Escenas de tiempo severo EN VIVO (feeds de nimbus): rayos GLM, vigilancias/MCD
// del SPC y granizo estimado por radar (MRMS MESH). Todas condicionales: solo
// entran al plan (buildScenePlan) cuando hay actividad y el feed es reciente.

// Caja de dato grande arriba a la derecha (mismo look que el total de reportes).
const CountCard: React.FC<{ value: string; label: string; op: number }> = ({
  value,
  label,
  op,
}) => (
  <div
    style={{
      position: "absolute",
      right: 48,
      top: 56,
      opacity: op,
      textAlign: "center",
      background: "rgba(8,20,30,0.82)",
      border: "1.5px solid rgba(255,255,255,0.28)",
      borderRadius: 14,
      padding: "14px 26px",
      boxShadow: "0 4px 18px rgba(0,0,0,0.5)",
      fontFamily,
    }}
  >
    <div
      style={{
        fontSize: 82,
        fontWeight: 900,
        color: "#fff",
        lineHeight: 1,
        fontFamily: "'JetBrains Mono', monospace",
      }}
    >
      {value}
    </div>
    <div
      style={{
        fontSize: 20,
        fontWeight: 800,
        letterSpacing: 2,
        textTransform: "uppercase",
        color: "rgba(255,255,255,0.85)",
        marginTop: 5,
      }}
    >
      {label}
    </div>
  </div>
);

const Swatch: React.FC<{ color: string; label: string; round?: boolean }> = ({
  color,
  label,
  round = true,
}) => (
  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
    <span
      style={{
        width: 22,
        height: 22,
        borderRadius: round ? "50%" : 6,
        background: color,
        border: "2px solid rgba(255,255,255,0.85)",
        flex: "0 0 auto",
      }}
    />
    <span style={{ color: "#fff", fontSize: 22, fontWeight: 700 }}>{label}</span>
  </div>
);

// ═════════════════════════════════════════════════════════════════════════════
// 1) Rayos GLM (GOES-19) — celdas de destellos de los últimos ~5 min
// ═════════════════════════════════════════════════════════════════════════════
// Color por intensidad de la celda (nº de destellos agrupados).
function glmColor(n: number): string {
  if (n >= 15) return "#ff5533";
  if (n >= 5) return "#ffa020";
  return "#ffd24a";
}

export const LightningScene: React.FC<{
  glm?: GlmData | null;
  mode?: ThemeMode;
  animate?: boolean;
}> = ({ glm, mode = "normal", animate = true }) => {
  const frame = useCurrentFrame();
  const op = animate ? interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" }) : 1;
  if (!glm) return <AbsoluteFill style={{ background: "#000" }} />;

  const dots: MapDot[] = glm.points.map((p) => ({ lon: p.lon, lat: p.lat, color: glmColor(p.n) }));

  return (
    <MapScene
      topic="RAYOS"
      sub={`GOES-19 · ÚLTIMOS ${glm.minutes} MIN`}
      topicColor={palette(mode).topicColor}
      op={op}
      dots={dots}
      dotRadius={5}
      animate={animate}
    >
      <CountCard value={String(glm.flashes)} label="destellos" op={op} />
      <Legend op={op}>
        <Swatch color="#ffd24a" label="Actividad" />
        <Swatch color="#ffa020" label="Frecuente" />
        <Swatch color="#ff5533" label="Intensa" />
      </Legend>
    </MapScene>
  );
};

// ═════════════════════════════════════════════════════════════════════════════
// 2) Vigilancias SPC (TOR/SVR) + discusiones de mesoescala (MCD)
// ═════════════════════════════════════════════════════════════════════════════
const WATCH_STYLE = {
  tornado: { color: "#e53935", label: "Vigilancia de tornado" },
  severe: { color: "#f4a020", label: "Vigilancia de torm. severa" },
} as const;
const MCD_COLOR = "#2ee6d6";

export const WatchesScene: React.FC<{
  spcWatches?: SpcWatchesData | null;
  mode?: ThemeMode;
  animate?: boolean;
}> = ({ spcWatches, mode = "normal", animate = true }) => {
  const frame = useCurrentFrame();
  const op = animate ? interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" }) : 1;
  if (!spcWatches) return <AbsoluteFill style={{ background: "#000" }} />;

  const kinds = new Set(
    spcWatches.watches.map((f) => (f?.properties?.wtype === "tornado" ? "tornado" : "severe"))
  );
  const polygons: MapPolygon[] = spcWatches.watches.map((f) => {
    const st = WATCH_STYLE[f?.properties?.wtype === "tornado" ? "tornado" : "severe"];
    return { data: f, fill: st.color, line: st.color, fillOpacity: 0.22 };
  });
  // Las MCD como contorno discontinuo: son "aviso de posible vigilancia", no una
  // vigilancia en sí — que no compitan visualmente con los polígonos rellenos.
  const lines: MapLine[] = spcWatches.mcds.map((f) => ({
    data: f,
    color: MCD_COLOR,
    width: 3.5,
    dash: [2, 1.5],
  }));

  return (
    <MapScene
      topic="TIEMPO SEVERO"
      sub="VIGILANCIAS SPC · AHORA"
      topicColor={palette(mode).topicColor}
      op={op}
      polygons={polygons}
      lines={lines}
      animate={animate}
    >
      {spcWatches.watches.length ? (
        <CountCard
          value={String(spcWatches.watches.length)}
          label={spcWatches.watches.length === 1 ? "vigilancia" : "vigilancias"}
          op={op}
        />
      ) : (
        <CountCard
          value={String(spcWatches.mcds.length)}
          label={spcWatches.mcds.length === 1 ? "zona MCD" : "zonas MCD"}
          op={op}
        />
      )}
      <Legend op={op}>
        {[...kinds].map((k) => (
          <Swatch key={k} color={WATCH_STYLE[k as keyof typeof WATCH_STYLE].color} label={WATCH_STYLE[k as keyof typeof WATCH_STYLE].label} round={false} />
        ))}
        {spcWatches.mcds.length ? (
          <Swatch color={MCD_COLOR} label="Discusión de mesoescala (posible vigilancia)" round={false} />
        ) : null}
      </Legend>
    </MapScene>
  );
};

// ═════════════════════════════════════════════════════════════════════════════
// 3) Granizo estimado por radar (MRMS MESH, máximo de la última hora)
// ═════════════════════════════════════════════════════════════════════════════
// Rampa del pipeline (mrms_severe_pipeline.py): 10→75 mm, verde→…→blanco.
const MESH_RAMP =
  "linear-gradient(90deg,#33cc33 0%,#9acd32 17%,#ffff33 33%,#ff9900 50%,#ff3300 67%,#cc00cc 83%,#ffffff 100%)";

export const HailScene: React.FC<{
  mesh?: MrmsMesh | null;
  mode?: ThemeMode;
  animate?: boolean;
}> = ({ mesh, mode = "normal", animate = true }) => {
  const frame = useCurrentFrame();
  const op = animate ? interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" }) : 1;
  if (!mesh) return <AbsoluteFill style={{ background: "#000" }} />;

  return (
    <MapScene
      topic="GRANIZO"
      sub="ESTIMADO POR RADAR · ÚLTIMA HORA"
      topicColor={palette(mode).topicColor}
      op={op}
      sat={mesh.view}
    >
      <CountCard value={`${mesh.maxIn.toFixed(1)}"`} label="máx. estimado" op={op} />
      <div
        style={{
          position: "absolute",
          left: 48,
          bottom: 40,
          display: "flex",
          flexDirection: "column",
          gap: 6,
          opacity: op,
        }}
      >
        <div style={{ color: "#fff", fontSize: 22, fontWeight: 700, opacity: 0.9 }}>
          Tamaño estimado (pulgadas)
        </div>
        <div
          style={{
            width: 420,
            height: 18,
            borderRadius: 7,
            border: "1px solid rgba(255,255,255,0.3)",
            background: MESH_RAMP,
          }}
        />
        <div
          style={{
            width: 420,
            display: "flex",
            justifyContent: "space-between",
            color: "#dfe8f0",
            fontSize: 17,
          }}
        >
          <span>0.4"</span>
          <span>1.5"</span>
          <span>3"</span>
        </div>
      </div>
    </MapScene>
  );
};
