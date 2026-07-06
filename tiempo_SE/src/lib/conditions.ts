// Lógica compartida de la escena "Condiciones ahora": tipos, paleta de
// temperatura, mapeo de condición→símbolo, dirección de viento y colocación
// anti-solape de las cajas. Sin JSX (los componentes viven en components/CondBox).

export type Sky = "sol" | "nubes-claros" | "nublado" | "lluvia" | "tormenta" | "nieve";

// Condición de una ciudad para rotular (temperatura en °F, viento en mph).
export type CityCond = {
  name: string;
  lon: number;
  lat: number;
  tempF: number;
  sky: Sky;
  windMph: number;
  windDeg: number; // grados a los que APUNTA la flecha (downwind)
};

// Temperatura rotulada (°F; decisión de producto).
export function fmtTemp(tempF: number): string {
  return `${Math.round(tempF)}°`;
}

// Paleta de temperatura (°F → color), para el acento de la caja.
export function tempColor(f: number): string {
  const stops: [number, string][] = [
    [10, "#7c4dff"],
    [32, "#3d7bff"],
    [45, "#21b6c9"],
    [55, "#2ecc71"],
    [68, "#f4d03f"],
    [80, "#ef8e2d"],
    [92, "#e74c3c"],
    [104, "#c0298a"],
  ];
  if (f <= stops[0][0]) return stops[0][1];
  if (f >= stops[stops.length - 1][0]) return stops[stops.length - 1][1];
  for (let i = 0; i < stops.length - 1; i++) {
    const [a, ca] = stops[i];
    const [b, cb] = stops[i + 1];
    if (f >= a && f <= b) return lerpColor(ca, cb, (f - a) / (b - a));
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

// Condición en español (del feed weather.json) → símbolo de cielo.
export function skyFromConditionEs(es: string | undefined, isNight = false): Sky {
  const s = (es || "").toLowerCase();
  if (/tormenta|eléctric/.test(s)) return "tormenta";
  if (/nieve|nevad/.test(s)) return "nieve";
  if (/lluvia|chubasc|llovizn|aguacero/.test(s)) return "lluvia";
  if (/niebla|neblin|bruma/.test(s)) return "nublado";
  if (/parcial/.test(s)) return "nubes-claros";
  if (/mayormente nublado|nublado|cubierto/.test(s)) return "nublado";
  if (/soleado|despejado|sol/.test(s)) return "sol";
  return isNight ? "nubes-claros" : "sol";
}

// Punto cardinal (dirección DESDE la que sopla) → grados a los que apunta la
// flecha (downwind = desde + 180). "↑" = norte.
const COMPASS: Record<string, number> = {
  N: 0, NNE: 22.5, NE: 45, ENE: 67.5, E: 90, ESE: 112.5, SE: 135, SSE: 157.5,
  S: 180, SSW: 202.5, SW: 225, WSW: 247.5, W: 270, WNW: 292.5, NW: 315, NNW: 337.5,
};
export function windArrowDeg(dirFrom: string | undefined): number {
  const d = COMPASS[(dirFrom || "").toUpperCase()] ?? 0;
  return (d + 180) % 360;
}

// ─── Colocación anti-solape de cajas ───────────────────────────────
export type Rect = { x0: number; y0: number; x1: number; y1: number };

// Tamaño aproximado de la caja (para el cálculo de solapes). Depende del nombre.
export function estimateBox(name: string): { w: number; h: number } {
  const nameW = name.length * 13 + 24;
  return { w: 23 + Math.max(150, nameW, 96), h: 122 };
}

// Área de intersección de dos rectángulos (0 si no se tocan).
export function overlapArea(a: Rect, b: Rect, pad = 6): number {
  const ix = Math.min(a.x1, b.x1 + pad) - Math.max(a.x0, b.x0 - pad);
  const iy = Math.min(a.y1, b.y1 + pad) - Math.max(a.y0, b.y0 - pad);
  return ix > 0 && iy > 0 ? ix * iy : 0;
}

export type Projected<T> = T & { x: number; y: number };
export type Placed<T> = Projected<T> & { bx: number; by: number };

// Coloca cada caja eligiendo, por orden de prioridad, la primera posición
// (arriba/abajo/lados/diagonales del punto) sin solape con las ya colocadas ni con
// los bordes/título/leyenda. Si ninguna es perfecta, elige la de menor penalización.
export function placeBoxes<T extends { name: string }>(
  cities: Projected<T>[],
  W: number,
  H: number,
  opts: { top?: number; bottom?: number } = {}
): Placed<T>[] {
  const margin = 24;
  const top = opts.top ?? 110;
  const bottom = (opts.bottom ?? H) - 0;
  const gap = 16;
  const taken: Rect[] = [];
  const out: Placed<T>[] = [];

  for (const c of cities) {
    const { w, h } = estimateBox(c.name);
    const cands: [number, number][] = [
      [c.x, c.y - gap - h / 2],
      [c.x, c.y + gap + h / 2],
      [c.x + gap + w / 2, c.y],
      [c.x - gap - w / 2, c.y],
      [c.x + gap + w / 2, c.y - gap - h / 2],
      [c.x - gap - w / 2, c.y - gap - h / 2],
      [c.x + gap + w / 2, c.y + gap + h / 2],
      [c.x - gap - w / 2, c.y + gap + h / 2],
    ];
    let best: { cx: number; cy: number; rect: Rect } | null = null;
    let bestScore = Infinity;
    for (const [cx0, cy0] of cands) {
      const cx = Math.max(margin + w / 2, Math.min(W - margin - w / 2, cx0));
      const cy = Math.max(top + h / 2, Math.min(bottom - h / 2, cy0));
      const rect: Rect = { x0: cx - w / 2, y0: cy - h / 2, x1: cx + w / 2, y1: cy + h / 2 };
      let overlap = 0;
      for (const t of taken) overlap += overlapArea(rect, t);
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
