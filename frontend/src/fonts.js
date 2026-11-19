// Interface and monospace font choices, remembered per browser like the theme.
//
// Exo 2, Jura and JetBrains Mono (SIL OFL 1.1) are bundled: each family is a
// separate lazily loaded module whose woff2 files are inlined as data: URIs,
// because the installer embeds text assets only and the CSP allows
// font-src data:. Only the chosen families are downloaded.
//
// SF Mono (Apple) is proprietary and is never bundled or served by the
// caster. It is used only when already installed on the viewer's device
// (usual on macOS and iOS); otherwise the browser falls back to the next font.

const UI_FALLBACK =
  '"Segoe UI", system-ui, -apple-system, Roboto, "Helvetica Neue", Arial, sans-serif';
const MONO_FALLBACK =
  'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace';

export const uiFonts = [
  {
    id: "exo2",
    label: "Exo 2",
    family: '"Exo 2"',
    load: () => import("./fonts/exo2.js"),
  },
  {
    id: "jura",
    label: "Jura",
    family: '"Jura"',
    load: () => import("./fonts/jura.js"),
  },
  { id: "system", label: "System default", family: "", system: true },
];

export const monoFonts = [
  {
    id: "jetbrains",
    label: "JetBrains Mono",
    family: '"JetBrains Mono"',
    load: () => import("./fonts/jetbrains-mono.js"),
  },
  {
    id: "sfmono",
    label: "SF Mono",
    family: '"SF Mono", SFMono-Regular',
    local: true,
  },
  { id: "system", label: "System default", family: "", system: true },
];

const KEYS = { ui: "gnss_font_ui", mono: "gnss_font_mono" };
const LISTS = { ui: uiFonts, mono: monoFonts };
const DEFAULTS = { ui: "exo2", mono: "jetbrains" };

function read(kind) {
  try {
    const value = globalThis.localStorage?.getItem(KEYS[kind]);
    if (LISTS[kind].some((font) => font.id === value)) return value;
  } catch {}
  return DEFAULTS[kind];
}

let selection = { ui: read("ui"), mono: read("mono") };
const listeners = new Set();

export function getFonts() {
  return selection;
}
export function subscribeFonts(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
export function setFont(kind, id) {
  if (!LISTS[kind]?.some((font) => font.id === id)) return;
  selection = { ...selection, [kind]: id };
  try {
    globalThis.localStorage?.setItem(KEYS[kind], id);
  } catch {}
  loadFont(fontById(kind, id));
  listeners.forEach((listener) => listener());
}

export function fontById(kind, id) {
  return LISTS[kind].find((font) => font.id === id) || LISTS[kind][0];
}

// CSS font-family value: the chosen font, then the generic fallbacks.
export function fontStack(kind, id) {
  const font = fontById(kind, id);
  const fallback = kind === "mono" ? MONO_FALLBACK : UI_FALLBACK;
  return font.family ? `${font.family}, ${fallback}` : fallback;
}

const loaded = new Map();
// Register a bundled family with the document; repeated calls reuse the work.
export function loadFont(font) {
  if (!font?.load || !globalThis.document?.fonts) return Promise.resolve();
  if (!loaded.has(font.id)) {
    loaded.set(
      font.id,
      font
        .load()
        .then(({ default: faces }) =>
          Promise.all(
            faces.map(async ({ family, source, descriptors }) => {
              const face = new FontFace(family, `url(${source})`, descriptors);
              document.fonts.add(face);
              await face.load();
            }),
          ),
        )
        .catch(() => loaded.delete(font.id)),
    );
  }
  return loaded.get(font.id);
}

export function loadSelectedFonts() {
  loadFont(fontById("ui", selection.ui));
  loadFont(fontById("mono", selection.mono));
}

// A locally installed font changes the measured width of a sample text against
// every generic fallback. Unknown names fall back and measure the same.
export function isInstalled(font) {
  if (!font?.local) return true;
  try {
    const context = document.createElement("canvas").getContext("2d");
    if (!context) return false;
    const sample = "mmmmmmmmmlli10OO@#ЖЩЮ";
    return ["monospace", "serif", "sans-serif"].some((generic) => {
      context.font = `32px ${generic}`;
      const base = context.measureText(sample).width;
      context.font = `32px ${font.family}, ${generic}`;
      return context.measureText(sample).width !== base;
    });
  } catch {
    return false;
  }
}
