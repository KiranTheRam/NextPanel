// Per-browser convenience only: storage can be unavailable (private mode,
// blocked site data), in which case there is simply no history.
const KEY = "nextpanel.recentSearches";
const LIMIT = 8;

export function loadRecentSearches(): string[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((q) => typeof q === "string").slice(0, LIMIT) : [];
  } catch {
    return [];
  }
}

export function rememberSearch(query: string): string[] {
  const q = query.trim();
  const next = q
    ? [q, ...loadRecentSearches().filter((old) => old.toLowerCase() !== q.toLowerCase())].slice(0, LIMIT)
    : loadRecentSearches();
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* not persisted */
  }
  return next;
}

export function clearRecentSearches(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* nothing stored */
  }
}
