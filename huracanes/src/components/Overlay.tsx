import React from "react";
import { loadFont } from "@remotion/google-fonts/Outfit";
import { tropCat } from "../lib/tropical";

const { fontFamily } = loadFont();
const mono = "'JetBrains Mono', monospace";

// Barra de tópico grande (≈ doble que antes). Icono de categoría opcional.
export const TopicBar: React.FC<{
  topic: string;
  sub: string;
  topicColor?: string;
  topicTextColor?: string;
  catKey?: string;
  opacity?: number;
}> = ({ topic, sub, topicColor = "#1565c0", topicTextColor = "#fff", catKey, opacity = 1 }) => {
  const cat = catKey ? tropCat(catKey) : null;
  return (
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
      {cat ? (
        <div
          style={{
            background: cat.color,
            display: "flex",
            alignItems: "center",
            padding: "0 22px",
          }}
        >
          <div
            style={{
              width: 64,
              height: 64,
              borderRadius: "50%",
              border: `4px solid ${catKey === "H1" ? "#1a2530" : "#fff"}`,
              color: catKey === "H1" ? "#1a2530" : "#fff",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontWeight: 800,
              fontSize: 36,
            }}
          >
            {cat.letter}
          </div>
        </div>
      ) : null}
      <div
        style={{
          background: topicColor,
          color: topicTextColor,
          padding: "20px 38px",
          fontWeight: 800,
          fontSize: 44,
          letterSpacing: 1,
          display: "flex",
          alignItems: "center",
        }}
      >
        {topic}
      </div>
      <div
        style={{
          background: "rgba(13,26,38,0.92)",
          color: "#fff",
          padding: "20px 38px",
          fontWeight: 700,
          fontSize: 42,
          display: "flex",
          alignItems: "center",
        }}
      >
        {sub}
      </div>
    </div>
  );
};

// Reloj grande arriba a la derecha
export const Clock: React.FC<{ time: string; sub?: string; opacity?: number }> = ({
  time,
  sub,
  opacity = 1,
}) => (
  <div
    style={{
      position: "absolute",
      top: 56,
      right: 56,
      textAlign: "right",
      opacity,
      fontFamily: mono,
    }}
  >
    <div style={{ fontSize: 76, fontWeight: 800, color: "#fff", lineHeight: 1 }}>{time}</div>
    {sub ? (
      <div
        style={{
          fontSize: 26,
          color: "rgba(255,255,255,0.7)",
          marginTop: 6,
          fontFamily,
        }}
      >
        {sub}
      </div>
    ) : null}
  </div>
);

// Icono grande del sistema tropical (D / T / 1-5) para el zoom a la tormenta.
export const SystemBadge: React.FC<{
  catKey: string;
  label: string; // "Tormenta tropical", "Huracán Cat. 3"...
  opacity?: number;
}> = ({ catKey, label, opacity = 1 }) => {
  const cat = tropCat(catKey);
  const txt = catKey === "H1" ? "#1a2530" : "#fff";
  return (
    <div
      style={{
        position: "absolute",
        top: 150,
        right: 56,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 12,
        opacity,
        fontFamily,
      }}
    >
      <div
        style={{
          width: 150,
          height: 150,
          borderRadius: "50%",
          background: cat.color,
          border: `6px solid #fff`,
          color: txt,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontWeight: 800,
          fontSize: 88,
          lineHeight: 1,
          boxShadow: "0 10px 36px rgba(0,0,0,0.55)",
        }}
      >
        {cat.letter}
      </div>
      <div
        style={{
          fontSize: 24,
          fontWeight: 700,
          color: "#fff",
          textShadow: "0 2px 6px rgba(0,0,0,0.7)",
          textAlign: "center",
          maxWidth: 220,
        }}
      >
        {label}
      </div>
    </div>
  );
};

// Barra de tiempo con fecha: muestra la fecha/hora del frame actual del satélite
// y una barra de progreso entre el inicio (hace 6h) y el final (ahora).
export const TimeBar: React.FC<{
  startUnix: number;
  endUnix: number;
  curUnix: number;
  opacity?: number;
}> = ({ startUnix, endUnix, curUnix, opacity = 1 }) => {
  const d = new Date(curUnix * 1000);
  const raw = new Intl.DateTimeFormat("es", {
    weekday: "long",
    day: "numeric",
    month: "long",
    timeZone: "America/New_York",
  }).format(d);
  const dateStr = raw.charAt(0).toUpperCase() + raw.slice(1); // "Martes, 9 de junio"
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
        width: 760,
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
        <span style={{ fontSize: 24, fontWeight: 800 }}>
          {dateStr}
        </span>
        <span style={{ fontSize: 24, fontWeight: 800, fontFamily: "'JetBrains Mono', monospace" }}>
          {hhmm(curUnix)} ET
        </span>
      </div>
      <div
        style={{
          position: "relative",
          height: 8,
          borderRadius: 4,
          background: "rgba(255,255,255,0.18)",
        }}
      >
        <div
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            bottom: 0,
            width: `${prog * 100}%`,
            background: "#457A99",
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
            background: "#F39C12",
            border: "2px solid #fff",
          }}
        />
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          color: "rgba(255,255,255,0.6)",
          fontSize: 15,
          marginTop: 4,
        }}
      >
        <span>{hhmm(startUnix)}</span>
        <span>últimas 6 h</span>
        <span>{hhmm(endUnix)}</span>
      </div>
    </div>
  );
};
