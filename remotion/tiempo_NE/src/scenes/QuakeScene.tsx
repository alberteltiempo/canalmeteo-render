import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/Outfit";
import { SatMap } from "../components/SatMap";
import { TopicBar } from "../components/Overlay";
import { MAJOR_CITIES } from "../lib/cities";
import { BRAND } from "../lib/theme";
import { Quake, SatView } from "../types";

const { fontFamily } = loadFont();

// Vista "base" (cartografía sistema, sin satélite).
const BASE_VIEW: SatView = { view: "base", band: "", bounds: null, frames: [] };

// Color por magnitud: naranja (5.5–5.9) → rojo (6–6.9) → morado (7+).
function magColor(m: number): string {
  if (m >= 7) return "#b026ff";
  if (m >= 6) return "#e74c3c";
  return "#ef8e2d";
}

// Hora del sismo: usa la etiqueta ya formateada por el pipeline si existe; si no,
// HH:MM UTC a partir del unix. (Evita suposiciones de zona horaria en EEUU.)
function quakeTime(q: Quake): string | null {
  if (q.timeLabel) return q.timeLabel;
  if (typeof q.time !== "number") return null;
  const d = new Date(q.time * 1000);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${hh}:${mm} UTC`;
}

// ═════════════════════════════════════════════════════════════════════════════
// 1) Cartel "ÚLTIMA HORA · TERREMOTO" (título previo, fondo crimson)
// ═════════════════════════════════════════════════════════════════════════════
export const QuakeIntro: React.FC<{ quake?: Quake | null; animate?: boolean }> = ({
  quake,
  animate = true,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const kicker = animate ? spring({ frame, fps, config: { damping: 14, mass: 0.6 } }) : 1;
  const titleIn = animate ? spring({ frame: frame - 8, fps, config: { damping: 16, mass: 0.7 } }) : 1;
  const subIn = animate ? spring({ frame: frame - 18, fps, config: { damping: 18, mass: 0.8 } }) : 1;
  // Latido del distintivo de última hora.
  const pulse = animate ? 1 + 0.04 * Math.sin((frame / fps) * Math.PI * 2 * 1.4) : 1;
  const fadeOut = animate
    ? interpolate(frame, [durationInFrames - 10, durationInFrames], [1, 0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      })
    : 1;

  const mag = quake ? quake.mag.toFixed(1) : null;

  return (
    <AbsoluteFill
      style={{
        fontFamily,
        opacity: fadeOut,
        background: `radial-gradient(120% 120% at 50% 38%, ${BRAND.alertRed} 0%, ${BRAND.alertRedDeep} 60%, #3a0610 100%)`,
        justifyContent: "center",
        alignItems: "center",
      }}
    >
      <AbsoluteFill
        style={{ background: "radial-gradient(80% 80% at 50% 50%, rgba(0,0,0,0) 55%, rgba(0,0,0,0.45) 100%)" }}
      />
      <div style={{ textAlign: "center" }}>
        <div
          style={{
            display: "inline-block",
            transform: `scale(${interpolate(kicker, [0, 1], [0.7, 1]) * pulse})`,
            background: "#fff",
            color: BRAND.alertRedDeep,
            fontSize: 34,
            fontWeight: 900,
            letterSpacing: 6,
            padding: "10px 28px",
            borderRadius: 10,
            boxShadow: "0 8px 30px rgba(0,0,0,0.45)",
          }}
        >
          ÚLTIMA HORA
        </div>
        <div
          style={{
            transform: `translateY(${interpolate(titleIn, [0, 1], [50, 0])}px)`,
            opacity: titleIn,
            fontSize: 168,
            fontWeight: 900,
            color: "#fff",
            lineHeight: 1,
            letterSpacing: 4,
            marginTop: 26,
            textShadow: "0 8px 34px rgba(0,0,0,0.5)",
          }}
        >
          TERREMOTO
        </div>
        {quake ? (
          <div
            style={{
              transform: `translateY(${interpolate(subIn, [0, 1], [40, 0])}px)`,
              opacity: subIn,
              marginTop: 22,
              color: "#fff",
              fontSize: 44,
              fontWeight: 700,
            }}
          >
            Magnitud <b style={{ fontWeight: 900 }}>{mag}</b>
            <span style={{ opacity: 0.85 }}> · {quake.place}</span>
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

// ═════════════════════════════════════════════════════════════════════════════
// 2) Mapa del epicentro + ficha (magnitud, lugar, profundidad, hora)
// ═════════════════════════════════════════════════════════════════════════════
// El mapa se centra EXACTAMENTE en el epicentro → el marcador animado (anillos
// expansivos) se pinta en el centro de pantalla como overlay React (las
// animaciones CSS no corren en el render headless; usamos useCurrentFrame).
const Epicenter: React.FC<{ color: string; op: number }> = ({ color, op }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const period = fps * 1.6;
  const rings = [0, 1, 2].map((i) => {
    const t = ((frame + (i * period) / 3) % period) / period; // 0..1
    return { scale: 0.3 + t * 2.6, opacity: (1 - t) * 0.6 };
  });
  return (
    <div
      style={{
        position: "absolute",
        left: "50%",
        top: "50%",
        transform: "translate(-50%, -50%)",
        opacity: op,
        pointerEvents: "none",
      }}
    >
      {rings.map((r, i) => (
        <div
          key={i}
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            width: 90,
            height: 90,
            marginLeft: -45,
            marginTop: -45,
            borderRadius: "50%",
            border: `4px solid ${color}`,
            transform: `scale(${r.scale})`,
            opacity: r.opacity,
          }}
        />
      ))}
      {/* Núcleo del epicentro. */}
      <div
        style={{
          position: "absolute",
          left: -13,
          top: -13,
          width: 26,
          height: 26,
          borderRadius: "50%",
          background: color,
          border: "3px solid #fff",
          boxShadow: `0 0 18px ${color}, 0 2px 6px rgba(0,0,0,0.6)`,
        }}
      />
    </div>
  );
};

const Stat: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
    <span style={{ fontSize: 15, fontWeight: 800, letterSpacing: 1.5, textTransform: "uppercase", color: "rgba(255,255,255,0.65)" }}>
      {label}
    </span>
    <span style={{ fontSize: 30, fontWeight: 800, color: "#fff" }}>{value}</span>
  </div>
);

export const QuakeScene: React.FC<{ quake?: Quake | null; animate?: boolean }> = ({
  quake,
  animate = true,
}) => {
  const frame = useCurrentFrame();
  const op = animate ? interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" }) : 1;
  if (!quake) return <AbsoluteFill style={{ background: "#000" }} />;
  const color = magColor(quake.mag);
  const time = quakeTime(quake);

  return (
    <AbsoluteFill style={{ background: "#000", fontFamily }}>
      <SatMap
        sat={BASE_VIEW}
        center={[quake.lon, quake.lat]}
        zoom={5.4}
        fitBounds={null}
        cityMarkers={MAJOR_CITIES}
        placeLabels
        showSatellite={false}
      />
      <AbsoluteFill
        style={{
          pointerEvents: "none",
          background:
            "linear-gradient(180deg, rgba(0,0,0,0.5) 0%, rgba(0,0,0,0) 22%, rgba(0,0,0,0) 70%, rgba(0,0,0,0.6) 100%)",
        }}
      />
      <Epicenter color={color} op={op} />
      <TopicBar topic="ÚLTIMA HORA · TERREMOTO" sub="EE. UU. · USGS" topicColor={BRAND.alertRed} opacity={op} />

      {/* Magnitud grande arriba a la derecha, en placa del color de severidad. */}
      <div
        style={{
          position: "absolute",
          right: 48,
          top: 116,
          opacity: op,
          background: "rgba(8,12,18,0.85)",
          border: `2px solid ${color}`,
          borderRadius: 18,
          padding: "16px 30px",
          textAlign: "center",
          boxShadow: "0 8px 28px rgba(0,0,0,0.55)",
        }}
      >
        <div style={{ fontSize: 16, fontWeight: 800, letterSpacing: 3, color: "rgba(255,255,255,0.7)" }}>
          MAGNITUD
        </div>
        <div
          style={{
            fontSize: 110,
            fontWeight: 900,
            color: "#fff",
            lineHeight: 1,
            fontFamily: "'JetBrains Mono', monospace",
            textShadow: `0 0 22px ${color}`,
          }}
        >
          {quake.mag.toFixed(1)}
        </div>
        {quake.tsunami ? (
          <div
            style={{
              marginTop: 10,
              background: "#0b6fb8",
              color: "#fff",
              fontSize: 18,
              fontWeight: 900,
              letterSpacing: 1,
              padding: "5px 12px",
              borderRadius: 8,
            }}
          >
            AVISO DE TSUNAMI
          </div>
        ) : null}
      </div>

      {/* Ficha inferior izquierda: lugar + profundidad + hora (+ "lo sentí"). */}
      <div
        style={{
          position: "absolute",
          left: 48,
          bottom: 44,
          opacity: op,
          background: "rgba(8,12,18,0.82)",
          border: "1.5px solid rgba(255,255,255,0.22)",
          borderRadius: 16,
          padding: "18px 26px",
          maxWidth: 760,
          boxShadow: "0 8px 28px rgba(0,0,0,0.5)",
        }}
      >
        <div style={{ fontSize: 34, fontWeight: 900, color: "#fff", lineHeight: 1.1, marginBottom: 14 }}>
          {quake.place}
        </div>
        <div style={{ display: "flex", gap: 40, flexWrap: "wrap", alignItems: "flex-end" }}>
          {quake.depthKm != null ? (
            <Stat label="Profundidad" value={`${quake.depthKm.toFixed(0)} km`} />
          ) : null}
          {time ? <Stat label="Hora" value={time} /> : null}
          {quake.felt != null && quake.felt > 0 ? (
            <Stat label="Reportes «lo sentí»" value={quake.felt.toLocaleString("es")} />
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ── Mockup (Still, datos de muestra) ──
const QUAKE_SAMPLE: Quake = {
  id: "sample",
  mag: 6.4,
  place: "18 km al SE de Ridgecrest, California",
  lon: -117.5,
  lat: 35.6,
  depthKm: 9,
  time: 1782300000,
  timeLabel: "Hoy 09:41 hora local",
  tsunami: 0,
  felt: 24300,
};

export const QuakeIntroMockup: React.FC = () => <QuakeIntro quake={QUAKE_SAMPLE} animate={false} />;
export const QuakeMockup: React.FC = () => <QuakeScene quake={QUAKE_SAMPLE} animate={false} />;
