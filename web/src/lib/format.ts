// Money arrives from the API as a decimal string ("549.95"), never a float; it is only formatted here.
const aud = new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD" });

export function money(value: string | number): string {
  return aud.format(Number(value));
}

export function percentOff(base: string, sale: string): string {
  return `${Math.round((1 - Number(sale) / Number(base)) * 100)}% off`;
}

const dateTime = new Intl.DateTimeFormat("en-AU", { dateStyle: "medium", timeStyle: "short" });
const dateOnly = new Intl.DateTimeFormat("en-AU", { dateStyle: "medium" });

export function formatDateTime(iso: string): string {
  return dateTime.format(new Date(iso));
}

export function formatDate(iso: string): string {
  return dateOnly.format(new Date(iso));
}

/** The last day of a half-open period [start, end): the day just before `end` (end is midnight after it). */
export function formatLastDay(endIso: string): string {
  return dateOnly.format(new Date(new Date(endIso).getTime() - 1));
}

export function timeAgo(iso: string, now = Date.now()): string {
  const seconds = Math.round((now - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return formatDateTime(iso);
}

export function signed(n: number): string {
  return n > 0 ? `+${n}` : `${n}`;
}
