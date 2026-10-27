const formatters = new Map<string, Intl.DateTimeFormat>();

function formatter(timeZone: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = `${timeZone}|${JSON.stringify(options)}`;
  let f = formatters.get(key);
  if (!f) {
    f = new Intl.DateTimeFormat("en-US", { timeZone, ...options });
    formatters.set(key, f);
  }
  return f;
}

function year(date: Date, timeZone: string): string {
  return formatter(timeZone, { year: "numeric" }).format(date);
}

export function formatDay(iso: string, timeZone: string, now: Date = new Date()): string {
  const date = new Date(iso);
  const sameYear = year(date, timeZone) === year(now, timeZone);
  return formatter(timeZone, { month: "short", day: "numeric", ...(sameYear ? {} : { year: "numeric" }) }).format(date);
}

export function formatMoment(iso: string, timeZone: string): string {
  return formatter(timeZone, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(
    new Date(iso),
  );
}

export function formatAgo(iso: string, timeZone: string, now: Date = new Date()): string {
  const minutes = Math.floor((now.getTime() - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 24 * 60) return `${Math.floor(minutes / 60)} h ago`;
  return formatDay(iso, timeZone, now);
}

export function formatChars(text: string): string {
  return `${text.length.toLocaleString("en-US")} chars`;
}
