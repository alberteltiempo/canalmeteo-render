// fonts.ts — Outfit autoalojada (public/fonts/), sustituye a @remotion/google-fonts.
// MOTIVO: el 2026-09-06 un fallo de enrutado del ISP hacia fonts.gstatic.com tumbó
// todos los renders durante ~15 h ("Timed out loading Google Font"). La antena no
// puede depender de que Google Fonts responda en cada render: la fuente viaja con
// el proyecto. Mismos woff2 v15 (variable, wght 100–900) y unicode-range que
// servía Google; misma firma de loadFont() que el paquete original.
import { cancelRender, continueRender, delayRender, staticFile } from "remotion";

const FAMILY = "Outfit";

const FACES: Array<{ file: string; range: string }> = [
  {
    file: "fonts/outfit-v15-latin.woff2",
    range:
      "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD",
  },
  {
    file: "fonts/outfit-v15-latin-ext.woff2",
    range:
      "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF",
  },
];

let started = false;

export const loadFont = (): { fontFamily: string } => {
  // computeMeta corre en Node (sin document): allí no hay nada que cargar.
  if (typeof document !== "undefined" && !started) {
    started = true;
    for (const { file, range } of FACES) {
      const handle = delayRender(`Cargando ${FAMILY} local (${file})`);
      const face = new FontFace(FAMILY, `url('${staticFile(file)}') format('woff2')`, {
        style: "normal",
        weight: "100 900",
        unicodeRange: range,
      });
      face
        .load()
        .then(() => {
          document.fonts.add(face);
          continueRender(handle);
        })
        .catch((err) => cancelRender(err));
    }
  }
  return { fontFamily: FAMILY };
};
