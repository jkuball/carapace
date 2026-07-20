/**
 * Route helper for the knowledge browser. The path lives in a query param because the
 * frontend is a static export, which cannot route on arbitrary path segments.
 */
export function knowledgeBrowseHref(path: string): string {
  const clean = path.replace(/^\/+/, "").replace(/\/+$/, "");
  return clean ? `/knowledge?path=${encodeURIComponent(clean)}` : "/knowledge";
}
