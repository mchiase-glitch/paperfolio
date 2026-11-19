// I valori arrivano come stringhe decimali esatte; Number serve solo per la visualizzazione.
const TZ = "Europe/Rome";

export function money(v, currency = "EUR", digits = 2) {
  if (v === null || v === undefined || v === "") return "—";
  // useGrouping "always": in italiano Intl ometterebbe il punto delle migliaia sotto 10.000
  return new Intl.NumberFormat("it-IT", { style: "currency", currency, minimumFractionDigits: digits, maximumFractionDigits: digits, useGrouping: "always" }).format(Number(v));
}

export function num(v, maxDigits = 4, minDigits = 0) {
  if (v === null || v === undefined || v === "") return "—";
  return new Intl.NumberFormat("it-IT", { minimumFractionDigits: minDigits, maximumFractionDigits: maxDigits, useGrouping: "always" }).format(Number(v));
}

export function price(v, currency) {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  const digits = Math.abs(n) < 10 ? 4 : n < 1000 ? 3 : 2;
  return `${num(v, digits, 2)} ${currency === "EUR" ? "€" : currency}`;
}

export function pct(v, digits = 2) {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  return `${n > 0 ? "+" : ""}${num(n, digits, digits)}%`;
}

export function signedMoney(v, currency = "EUR") {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  return `${n > 0 ? "+" : ""}${money(n, currency)}`;
}

export function cls(v) {
  const n = Number(v);
  return n > 0 ? "pos" : n < 0 ? "neg" : "";
}

export function dateTime(iso) {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("it-IT", { timeZone: TZ, day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

export function priceTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  const day = (x) => new Intl.DateTimeFormat("it-IT", { timeZone: TZ, day: "2-digit", month: "2-digit", year: "numeric" }).format(x);
  const time = new Intl.DateTimeFormat("it-IT", { timeZone: TZ, hour: "2-digit", minute: "2-digit" }).format(d);
  return day(d) === day(new Date()) ? `ore ${time}` : `${day(d).slice(0, 5)} ${time}`;
}

export function date(iso) {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
}

// Sposta la virgola di un decimale in forma di stringa senza passare dai float (es. "0.0007" ↔ "0.07")
export function shiftDecimal(str, places) {
  let s = String(str).trim().replace(",", ".");
  if (s === "" || isNaN(Number(s))) return null;
  const neg = s.startsWith("-");
  if (neg) s = s.slice(1);
  let [int, frac = ""] = s.split(".");
  let digits = int + frac;
  let point = int.length + places;
  if (point <= 0) { digits = "0".repeat(1 - point) + digits; point = 1; }
  if (point > digits.length) digits = digits + "0".repeat(point - digits.length);
  let out = digits.slice(0, point).replace(/^0+(?=\d)/, "") + (point < digits.length ? "." + digits.slice(point) : "");
  out = out.includes(".") ? out.replace(/0+$/, "").replace(/\.$/, "") : out;
  return (neg ? "-" : "") + (out || "0");
}

export const toPercent = (fraction) => shiftDecimal(fraction, 2);
export const fromPercent = (percent) => shiftDecimal(percent, -2);

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export const TYPE_LABELS = { stock: "Azioni", etf: "ETF", bond: "Obbligazioni", derivative: "Derivati" };
export const MARKET_LABELS = { ITA: "Borsa Italiana", EUR: "Europa", USA: "USA" };
