import { continueRender, delayRender, staticFile } from "remotion";

// The looks' type, bundled in public/fonts (latin, from Google Fonts, each with its OFL text beside it), so a render
// needs no network.
export const ANTON = "ReelAnton", SERIF = "ReelSerif", MONO = "ReelMono", SANS = "ReelSans";
export const SERIF_ROMAN = "ReelSerifRoman";   // Instrument Serif upright, for its numerals (Darkroom, Stillness)
export const HAND = "ReelHand";                // Caveat, pencil on a print's border (Darkroom)
export const GARAMOND = "ReelGaramond";        // Cormorant Garamond, roman and italic, 300 to 700 (Chiaroscuro)
export const ARCHIVO = "ReelArchivo";          // Archivo, 100 to 900, widths 62% to 125% (Axis, Titles, Manifesto, ...)
const FACES: [string, string, FontFaceDescriptors][] = [
  [ANTON, "Anton-400.woff2", { weight: "400" }],
  [SERIF, "InstrumentSerif-400i.woff2", { style: "italic", weight: "400" }],
  [MONO, "JetBrainsMono-500.woff2", { weight: "500" }],
  [SANS, "InterTight.woff2", { weight: "100 900" }],
  [SERIF_ROMAN, "InstrumentSerif-Regular.ttf", { weight: "400" }],
  [HAND, "Caveat.ttf", { weight: "400 700" }],
  [GARAMOND, "CormorantGaramond.woff2", { weight: "300 700" }],
  [GARAMOND, "CormorantGaramond-Italic.woff2", { style: "italic", weight: "300 700" }],
  [ARCHIVO, "Archivo.woff2", { weight: "100 900", stretch: "62% 125%" }],
];
const handle = delayRender("Loading the looks' fonts");
/** Resolves once every face is in, so a look that measures its type can wait for the real metrics. */
export const fontsLoaded: Promise<void> = Promise.all(FACES.map(([family, file, desc]) => new FontFace(family, `url(${staticFile(`fonts/${file}`)})`, desc).load().then((f) => (document.fonts as unknown as { add: (f: FontFace) => void }).add(f))))
  .then(() => continueRender(handle))
  .catch((e) => { console.error(e); continueRender(handle); });
