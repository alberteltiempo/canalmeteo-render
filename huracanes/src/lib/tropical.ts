import { TROP_CAT } from "./theme";

// Nombre seguro de la tormenta (con fallback para sistemas aún sin bautizar)
export function stormName(
  storm: { name?: string | null; id?: string | null } | null | undefined
): string {
  const n = storm?.name?.trim();
  if (n) return n;
  const id = storm?.id?.trim();
  if (id) return id.toUpperCase(); // p.ej. "EP03"
  return "Sistema tropical";
}

// kt -> mph redondeado a múltiplos de 5 (idéntico a kt_to_mph5 del pipeline).
// null/undefined → null (no 0): un invest sin ráfaga publicada debe salir "—",
// no "0 mph" (Number(null) === 0 lo convertía en un 0 engañoso).
export function ktToMph(kt: number | null | undefined): number | null {
  if (kt == null) return null;
  const v = Number(kt);
  return isFinite(v) && v < 9000 ? Math.round((v * 1.150779) / 5) * 5 : null;
}

// Clave de categoría para un sistema: "INV" si es invest, si no por intensidad.
// Centraliza la decisión para que satélite, lluvia y tarjeta usen el mismo badge.
export function catKeyFor(
  storm: { is_invest?: boolean; intensity_kt?: number | null } | null | undefined
): string {
  if (storm?.is_invest) return "INV";
  return catKeyFromKt(storm?.intensity_kt);
}

// Intensidad (kt) -> clave de categoría Saffir-Simpson
export function catKeyFromKt(kt: number | null | undefined): string {
  const v = Number(kt) || 0;
  if (v >= 137) return "H5";
  if (v >= 113) return "H4";
  if (v >= 96) return "H3";
  if (v >= 83) return "H2";
  if (v >= 64) return "H1";
  if (v >= 34) return "TS";
  return "TD";
}

export function tropCat(key: string) {
  return TROP_CAT[key] || { color: "#90caf9", letter: "?" };
}

export function tropShortLabel(key: string): string {
  if (key === "INV") return "Invest · área de investigación";
  if (key === "TD") return "Depresión tropical";
  if (key === "TS") return "Tormenta tropical";
  const m = /^H([1-5])$/.exec(key);
  if (m) return `Huracán Cat. ${m[1]}`;
  return key;
}

// Formato de hora ET (es-ES) — idéntico al banner del frontend
export function fmtBulletinTime(iso: string): string {
  try {
    const d = new Date(iso);
    return (
      d.toLocaleString("es-ES", {
        timeZone: "America/New_York",
        weekday: "short",
        day: "numeric",
        month: "short",
        hour: "numeric",
        minute: "2-digit",
        hour12: true,
      }) + " ET"
    );
  } catch {
    return iso || "";
  }
}

// Traduce la etiqueta de fecha (datelbl "6:00 PM Tue") al español: "6:00 p.m. mar"
const DAY_ES: Record<string, string> = {
  Mon: "lun", Tue: "mar", Wed: "mié", Thu: "jue", Fri: "vie", Sat: "sáb", Sun: "dom",
};
export function localizeDatelbl(s: string | undefined | null): string {
  if (!s) return "";
  return String(s)
    .replace(/\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b/g, (m) => DAY_ES[m] || m)
    .replace(/\bAM\b/g, "a.m.")
    .replace(/\bPM\b/g, "p.m.");
}

// Grados -> rosa de 16 vientos en español (O = Oeste)
const COMPASS_ES = [
  "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
  "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO",
];
export function degToCompass(deg: number): string {
  return COMPASS_ES[Math.round((deg % 360) / 22.5) % 16];
}

// Movimiento: "ENE a 5 mph" (dir puede venir en grados o ya como texto)
export function formatMovement(
  dir: string | number | null | undefined,
  mph: number | null | undefined
): string | null {
  let dirStr = "";
  if (typeof dir === "number" && isFinite(dir)) dirStr = degToCompass(dir);
  else if (typeof dir === "string" && dir.trim()) dirStr = dir.trim();
  const speed = mph != null && isFinite(mph) ? `${mph} mph` : "";
  if (!dirStr && !speed) return null;
  return [dirStr, speed].filter(Boolean).join(" a ");
}
