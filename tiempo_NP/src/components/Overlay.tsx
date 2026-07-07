import React from "react";
import { loadFont } from "@remotion/google-fonts/Outfit";
import { BRAND } from "../lib/theme";

const { fontFamily } = loadFont();
const mono = "'JetBrains Mono', monospace";

// Barra de tópico grande arriba a la izquierda.
export const TopicBar: React.FC<{
  topic: string;
  sub?: string;
  topicColor?: string;
  topicTextColor?: string;
  opacity?: number;
}> = ({ topic, sub, topicColor = BRAND.blueVivid, topicTextColor = "#fff", opacity = 1 }) => (
  <div
    style={{
      position: "absolute",
      top: 56,
      left: 56,
      display: "flex",
      alignItems: "stretch",
      borderRadius: 16,
      overflow: "hidden",
      boxShadow: "0 8px 30px rgba(0,0,0,0.45)",
      opacity,
      fontFamily,
    }}
  >
    <div
      style={{
        background: topicColor,
        color: topicTextColor,
        padding: "22px 42px",
        fontWeight: 800,
        fontSize: 52,
        letterSpacing: 1,
        display: "flex",
        alignItems: "center",
      }}
    >
      {topic}
    </div>
    {sub ? (
      <div
        style={{
          background: "rgba(13,26,38,0.92)",
          color: "#fff",
          padding: "22px 42px",
          fontWeight: 700,
          fontSize: 50,
          display: "flex",
          alignItems: "center",
        }}
      >
        {sub}
      </div>
    ) : null}
  </div>
);

// Barra de tiempo con fecha + barra de progreso entre inicio y fin.
export const TimeBar: React.FC<{
  startUnix: number;
  endUnix: number;
  curUnix: number;
  centerLabel?: string;
  accent?: string;
  opacity?: number;
}> = ({ startUnix, endUnix, curUnix, centerLabel = "últimas 3 h", accent = BRAND.orange, opacity = 1 }) => {
  const d = new Date(curUnix * 1000);
  const raw = new Intl.DateTimeFormat("es", {
    weekday: "long",
    day: "numeric",
    month: "long",
    timeZone: "America/New_York",
  }).format(d);
  const dateStr = raw.charAt(0).toUpperCase() + raw.slice(1);
  const hhmm = (u: number) =>
    new Intl.DateTimeFormat("es", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: "America/New_York",
    }).format(new Date(u * 1000));
  const span = Math.max(1, endUnix - startUnix);
  const prog = Math.max(0, Math.min(1, (curUnix - startUnix) / span));
  return (
    <div
      style={{
        position: "absolute",
        bottom: 48,
        left: "50%",
        transform: "translateX(-50%)",
        width: 820,
        opacity,
        fontFamily,
        background: "rgba(13,26,38,0.82)",
        borderRadius: 14,
        padding: "12px 20px",
        border: "1px solid rgba(255,255,255,0.1)",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          color: "#fff",
          marginBottom: 8,
        }}
      >
        <span style={{ fontSize: 27, fontWeight: 800 }}>{dateStr}</span>
        <span style={{ fontSize: 27, fontWeight: 800, fontFamily: mono }}>{hhmm(curUnix)} ET</span>
      </div>
      <div style={{ position: "relative", height: 8, borderRadius: 4, background: "rgba(255,255,255,0.18)" }}>
        <div
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            bottom: 0,
            width: `${prog * 100}%`,
            background: BRAND.blue,
            borderRadius: 4,
          }}
        />
        <div
          style={{
            position: "absolute",
            left: `${prog * 100}%`,
            top: "50%",
            transform: "translate(-50%,-50%)",
            width: 16,
            height: 16,
            borderRadius: "50%",
            background: accent,
            border: "2px solid #fff",
          }}
        />
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          color: "rgba(255,255,255,0.6)",
          fontSize: 18,
          marginTop: 4,
        }}
      >
        <span>{hhmm(startUnix)}</span>
        <span>{centerLabel}</span>
        <span>{hhmm(endUnix)}</span>
      </div>
    </div>
  );
};
