import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { loadFont } from "@remotion/google-fonts/Outfit";
import { TropMap } from "../components/TropMap";
import { TopicBar } from "../components/Overlay";
import { TROP_CAT } from "../lib/theme";
import { catKeyFromKt, tropCat, tropShortLabel, stormName } from "../lib/tropical";
import { Storm } from "../types";

const { fontFamily } = loadFont();

// Escena 2: trayectoria + cono + avisos (sin satélite), animada.
export const StormTrack: React.FC<{ storm: Storm }> = ({ storm }) => {
  const frame = useCurrentFrame();
  const titleOpacity = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });

  const cats = ["TD", "TS", "H1", "H2", "H3", "H4", "H5"];
  // Categoría máxima prevista a lo largo del pronóstico
  const maxKt = storm._maxFcstKt ?? storm.intensity_kt ?? 0;
  const maxKey = catKeyFromKt(maxKt);
  const maxCat = tropCat(maxKey);
  const maxTxt = maxKey === "H1" ? "#1a2530" : "#fff";

  return (
    <AbsoluteFill style={{ fontFamily, background: "#0d1a26" }}>
      <TropMap storm={storm} />

      <TopicBar
        topic="TRAYECTORIA"
        sub={`${stormName(storm).toUpperCase()} · CONO Y AVISOS`}
        topicColor="#F39C12"
        topicTextColor="#1a2530"
        catKey={catKeyFromKt(storm.intensity_kt)}
        opacity={titleOpacity}
      />

      {/* Categoría máxima prevista (arriba a la derecha) */}
      <div
        style={{
          position: "absolute",
          top: 56,
          right: 56,
          display: "flex",
          alignItems: "center",
          gap: 16,
          background: "rgba(13,26,38,0.85)",
          borderRadius: 14,
          padding: "14px 20px",
          border: "1px solid rgba(255,255,255,0.12)",
          opacity: titleOpacity,
        }}
      >
        <div
          style={{
            width: 60,
            height: 60,
            borderRadius: "50%",
            background: maxCat.color,
            border: `3px solid ${maxTxt}`,
            color: maxTxt,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 800,
            fontSize: 32,
            flexShrink: 0,
          }}
        >
          {maxCat.letter}
        </div>
        <div style={{ color: "#fff" }}>
          <div style={{ fontSize: 18, color: "rgba(255,255,255,0.7)" }}>
            Categoría máxima prevista
          </div>
          <div style={{ fontSize: 30, fontWeight: 800 }}>{tropShortLabel(maxKey)}</div>
        </div>
      </div>

      {/* Leyenda de categorías */}
      <div
        style={{
          position: "absolute",
          bottom: 44,
          left: "50%",
          transform: "translateX(-50%)",
          display: "flex",
          gap: 14,
          background: "rgba(13,26,38,0.85)",
          padding: "14px 24px",
          borderRadius: 16,
          opacity: titleOpacity,
        }}
      >
        {cats.map((k) => (
          <div
            key={k}
            style={{
              width: 38,
              height: 38,
              borderRadius: "50%",
              background: TROP_CAT[k].color,
              border: "2.5px solid #fff",
              color: k === "H1" ? "#333" : "#fff",
              fontWeight: 800,
              fontSize: 20,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            {TROP_CAT[k].letter}
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};
