/**
 * Shared timestamp formatting.
 *
 * ponytail: `sidebar.tsx` and `message.tsx` still carry their own near-identical
 * copies; fold them in here when one of them next needs a change.
 */

/**
 * Relative age ("3 days ago"), falling back to an absolute date beyond a week
 * where "52 weeks ago" stops being useful. Returns "" for unparseable input.
 */
export function formatRelativeTime(
  iso: string,
  locale: string,
  now: number,
  justNowLabel: string,
): string {
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return "";

  const diff = now - parsed;
  if (diff < 60_000) return justNowLabel;

  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  if (diff < 3_600_000) return formatter.format(-Math.floor(diff / 60_000), "minute");
  if (diff < 86_400_000) return formatter.format(-Math.floor(diff / 3_600_000), "hour");
  if (diff < 604_800_000) return formatter.format(-Math.floor(diff / 86_400_000), "day");

  return new Intl.DateTimeFormat(locale, { day: "2-digit", month: "2-digit", year: "numeric" }).format(parsed);
}

/** Full date and time, for tooltips. Returns "" for unparseable input. */
export function formatAbsoluteTime(iso: string, locale: string): string {
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return "";
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(parsed);
}
