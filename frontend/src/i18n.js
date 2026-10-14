import ru from "./locales/ru.json" with { type: "json" };

export const supportedLanguages = ["en", "ru"];
const normalize = (value) =>
  supportedLanguages.includes(value) ? value : "en";
let language = "en";
try {
  language = normalize(globalThis.localStorage?.getItem("gnss_language"));
} catch {}
const listeners = new Set();

export function getLanguage() {
  return language;
}
export function getLocale() {
  return language === "ru" ? "ru-RU" : "en-US";
}
export function subscribeLanguage(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
export function setLanguage(value) {
  language = normalize(value);
  try {
    globalThis.localStorage?.setItem("gnss_language", language);
  } catch {}
  if (globalThis.document) document.documentElement.lang = language;
  listeners.forEach((listener) => listener());
}

// English messages are stable keys. Interpolate after lookup so user-provided
// names and credentials are never treated as translation keys or HTML.
export function t(message, values = []) {
  if (typeof message !== "string") return message;
  const translated =
    language === "ru" && Object.hasOwn(ru, message) ? ru[message] : message;
  return translated.replace(/\{(\d+)\}/g, (match, index) =>
    index in values ? String(values[index] ?? "") : match,
  );
}

// Known structured API messages only. Never run this over receiver output or
// user object names; unmatched technical diagnostics are retained verbatim.
export function serverMessage(message) {
  if (typeof message !== "string" || language !== "ru") return message;
  const patterns = [
    [/^(\d+)\/(\d+) receivers connected$/, "{0}/{1} receivers connected"],
    [
      /^(\d+)\/(\d+) receivers provide fresh RTCM$/,
      "{0}/{1} receivers provide fresh RTCM",
    ],
    [/^only (\d+) satellites in use$/, "only {0} satellites in use"],
  ];
  const recovery = message.match(
    /^(.*); Bluetooth recovery: ([a-z_]+) \(attempt (\d+)\)$/,
  );
  if (recovery)
    return `${serverMessage(recovery[1])}; ${t("Bluetooth recovery: {0} (attempt {1})", [t(recovery[2]), recovery[3]])}`;
  for (const [pattern, key] of patterns) {
    const match = message.match(pattern);
    if (match) return t(key, match.slice(1));
  }
  return t(message);
}

if (globalThis.document) document.documentElement.lang = language;
