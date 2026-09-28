import { useEffect, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";
import { api } from "../api/client";
import { countOf, titleHref } from "../api/paths";
import { clearRecentSearches, loadRecentSearches, rememberSearch } from "../api/recentSearches";
import { useHideInLibrary } from "../api/preferences";
import type { DiscoverResponse, SearchResponse, SearchResult } from "../api/types";
import { EmptyState, MediaBadge, Spinner, Toolbar } from "../components/common";
import { SearchIcon } from "../components/icons";
import RequestButton from "../components/RequestButton";
import { TitleRow } from "../components/TitleCard";

const RECOMMENDATION_SECTION_KEYS = [
  "because",
  "trending",
  "new_season",
  "top_last_season",
  "all_time",
  "comics_week",
  "comics_new_series",
] as const;

/** Where a row's "See all" leads. Manhwa rows are the manga rows' Korean half. */
function seeAllHref(sectionKey: string): string | null {
  if (sectionKey === "because") return null;
  if (sectionKey.startsWith("comics_")) return `/browse/${sectionKey}`;
  if (sectionKey.startsWith("manhwa_")) return `/browse/${sectionKey.slice("manhwa_".length)}?origin=manhwa`;
  return `/browse/${sectionKey}?origin=manga`;
}

function GenreChips() {
  const { data: genres } = useQuery({
    queryKey: ["discover", "genres"],
    queryFn: () => api.get<string[]>("/discover/genres"),
    staleTime: Infinity,
  });
  if (!genres?.length) return null;
  return (
    <nav className="genre-browse" aria-label="Browse by genre">
      {genres.map((genre) => (
        <Link className="chip" key={genre} to={`/browse/genre?genre=${encodeURIComponent(genre)}`}>
          {genre}
        </Link>
      ))}
    </nav>
  );
}

function Recommendations() {
  const [hideInLibrary, setHideInLibrary] = useHideInLibrary();
  const queries = useQueries({
    queries: RECOMMENDATION_SECTION_KEYS.map((key) => ({
      queryKey: ["discover", "section", key],
      queryFn: () => api.get<DiscoverResponse>(`/discover/sections/${key}`),
      // The upstream AniList data is cached for 30 minutes too. Keeping the
      // browser cache aligned makes returning to Discover instant.
      staleTime: 30 * 60 * 1000,
      gcTime: 60 * 60 * 1000,
      refetchOnWindowFocus: false,
      retry: 1,
    })),
  });

  // useQueries preserves input order, but each response becomes available
  // independently. Fast rows render immediately while slower rows continue.
  const sections = queries.flatMap((query) => query.data?.sections ?? []);
  const pendingCount = queries.filter((query) => query.isPending).length;
  const hasErrors = queries.some(
    (query) => query.isError || Object.keys(query.data?.errors ?? {}).length > 0,
  );
  const retrySections = () => queries.forEach((query) => { void query.refetch(); });

  if (sections.length === 0 && pendingCount > 0) return <Spinner />;
  if (sections.length === 0) {
    return (
      <>
        {hasErrors && (
          <div className="error-banner" role="alert">
            Recommendations could not be loaded. <button className="btn" onClick={retrySections}>Retry</button>
          </div>
        )}
        <EmptyState
          icon={<SearchIcon size={40} />}
          title="Search for something to request"
          hint="Manga and manhwa recommendations come from AniList; comics come from ComicVine."
        />
      </>
    );
  }
  return (
    <>
      <div className="discover-options">
        <label className="check-option">
          <input
            type="checkbox"
            checked={hideInLibrary}
            onChange={(e) => setHideInLibrary(e.target.checked)}
          />
          Hide titles already in the library
        </label>
      </div>
      {hasErrors && (
        <div className="error-banner" style={{ marginBottom: 12 }}>
          Some recommendation rows could not be loaded. <button className="btn" onClick={retrySections}>Retry</button>
        </div>
      )}
      {sections.map((section) => {
        const href = seeAllHref(section.key);
        return (
          <TitleRow
            key={section.key}
            title={section.title}
            items={hideInLibrary ? section.items.filter((item) => !item.in_library) : section.items}
            action={href && <Link className="see-all" to={href}>See all</Link>}
          />
        );
      })}
      {pendingCount > 0 && (
        <div className="recommendations-progress" aria-live="polite">
          <span className="mini-spinner" />
          Loading {pendingCount} more recommendation {pendingCount === 1 ? "section" : "sections"}…
        </div>
      )}
    </>
  );
}

const SOURCE_LABEL: Record<string, string> = {
  anilist: "AniList",
  mangaupdates: "MangaUpdates",
  comicvine: "ComicVine",
};
const ORIGIN_LABEL: Record<string, string> = { KR: "Manhwa", CN: "Manhua", TW: "Manhua" };

function ResultCard({ result, onOpen }: { result: SearchResult; onOpen: () => void }) {
  const displayTitle = result.english_title || result.title;
  return (
    <Link className="result-card" to={titleHref(result)} onClick={onOpen}>
      {result.cover_url ? (
        <img src={result.cover_url} alt="" loading="lazy" />
      ) : (
        <div className="no-cover">{displayTitle}</div>
      )}
      <div className="result-body">
        <h4>
          {displayTitle}
          {result.year ? <span style={{ color: "var(--text-faint)", fontWeight: 400 }}> ({result.year})</span> : null}
        </h4>
        <div className="result-meta">
          <MediaBadge mediaType={result.media_type} />
          {ORIGIN_LABEL[result.country] && <span>{ORIGIN_LABEL[result.country]}</span>}
          {result.publisher && <span>{result.publisher}</span>}
          {result.status && <span>{result.status.replace(/_/g, " ")}</span>}
          {result.total_count != null && (
            <span>
              {countOf(result.total_count, result.media_type)}
            </span>
          )}
          {result.score != null && <span className="discover-score">{result.score}%</span>}
          <span className="result-source">{SOURCE_LABEL[result.provider] ?? result.provider}</span>
        </div>
        {result.description && <div className="result-desc">{result.description.replace(/<[^>]+>/g, "")}</div>}
        <div className="result-actions">
          <RequestButton
            payload={{
              media_type: result.media_type,
              provider: result.provider,
              provider_id: result.provider_id,
              title: result.title,
              english_title: result.english_title,
              alt_titles: result.alt_titles,
              year: result.year,
              cover_url: result.cover_url,
              description: result.description,
            }}
            inLibrary={result.in_library}
            requestStatus={result.request_status}
          />
        </div>
      </div>
    </Link>
  );
}

type MediaFilter = "all" | "manga" | "comic";

// Search as you type, once the typing pauses. Searches reach ComicVine
// through pullarr, whose key has an hourly budget; the server also caches
// each query's results.
const SEARCH_DEBOUNCE_MS = 450;
const MIN_QUERY_LENGTH = 2;

function RecentSearches({
  searches,
  onPick,
  onClear,
}: {
  searches: string[];
  onPick: (q: string) => void;
  onClear: () => void;
}) {
  if (searches.length === 0) return null;
  return (
    <div className="recent-searches" aria-label="Recent searches">
      <span className="recent-label">Recent</span>
      {searches.map((q) => (
        <button type="button" className="chip" key={q} onClick={() => onPick(q)}>
          {q}
        </button>
      ))}
      <button type="button" className="chip-clear" onClick={onClear}>
        Clear
      </button>
    </div>
  );
}

export default function Discover() {
  // The search lives in the URL, not in component state: that is what lets
  // the browser's back button return from a title to the results you came
  // from, and makes a set of results linkable and refresh-safe.
  const [params, setParams] = useSearchParams();
  const query = params.get("q")?.trim() ?? "";
  const mediaType = (params.get("type") as MediaFilter) || "all";
  const [input, setInput] = useState(query);
  const [recent, setRecent] = useState(loadRecentSearches);

  // follow the URL when it changes underneath us (back/forward navigation)
  useEffect(() => setInput(query), [query]);

  const { data, isFetching, isError, error, refetch } = useQuery({
    queryKey: ["search", query, mediaType],
    queryFn: () =>
      api.get<SearchResponse>(
        `/search?q=${encodeURIComponent(query)}&media_type=${mediaType}`,
      ),
    enabled: query.length > 0,
    // keep the previous results on screen while the next query loads
    placeholderData: (previous) => previous,
  });

  const submitSearch = (next: { q?: string; type?: MediaFilter }) => {
    const q = (next.q ?? query).trim();
    const type = next.type ?? mediaType;
    const updated: Record<string, string> = {};
    if (q) updated.q = q;
    if (type !== "all") updated.type = type;
    // The first search pushes, so Back from the results returns to the
    // discover home. Refining an existing search replaces, so Back does not
    // have to walk out through every intermediate query.
    setParams(updated, { replace: query.length > 0 });
  };

  // typing pauses -> search; clearing the box returns to recommendations
  useEffect(() => {
    const q = input.trim();
    if (q === query || (q.length > 0 && q.length < MIN_QUERY_LENGTH)) return;
    const timer = window.setTimeout(() => submitSearch({ q }), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [input]);

  const search = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;
    setRecent(rememberSearch(input));
    submitSearch({ q: input });
  };

  const pickRecent = (q: string) => {
    setInput(q);
    setRecent(rememberSearch(q));
    submitSearch({ q });
  };

  const showingResults = query.length > 0 && !!data && !isError;

  return (
    <>
      <Toolbar title="Discover" />
      <div className="content">
        <form className="search-bar" onSubmit={search} role="search">
          <input
            type="search"
            aria-label="Search manga and comics"
            placeholder="Search manga and comics…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            enterKeyHint="search"
          />
          <div className="seg">
            {(["all", "manga", "comic"] as const).map((t) => (
              <button
                type="button"
                key={t}
                className={mediaType === t ? "active" : ""}
                onClick={() => submitSearch({ q: input, type: t })}
              >
                {t === "all" ? "All" : t === "manga" ? "Manga" : "Comics"}
              </button>
            ))}
          </div>
          <button className="btn primary" type="submit" disabled={!input.trim()}>
            Search
          </button>
        </form>

        {!query && <GenreChips />}
        {!query && (
          <RecentSearches
            searches={recent}
            onPick={pickRecent}
            onClear={() => {
              clearRecentSearches();
              setRecent([]);
            }}
          />
        )}

        {query && Object.entries(data?.errors ?? {}).map(([source, message]) => (
          <div className="error-banner" key={source} style={{ marginBottom: 12 }}>
            {SOURCE_LABEL[source] ?? source}: {message}
          </div>
        ))}

        {isError && query && (
          <div className="error-banner" role="alert">
            Search failed: {(error as Error).message}{" "}
            <button className="btn" type="button" onClick={() => refetch()}>Retry</button>
          </div>
        )}

        {query && isFetching && !data && <Spinner />}
        {query && isFetching && data && (
          <div className="recommendations-progress" aria-live="polite">
            <span className="mini-spinner" /> Searching…
          </div>
        )}
        {showingResults && !isFetching && data.results.length === 0 && (
          <EmptyState icon={<SearchIcon size={40} />} title="No results" hint="Try another title or spelling." />
        )}
        {!query && <Recommendations />}
        {showingResults && data.results.length > 0 && (
          <div className={`results-grid${isFetching ? " refreshing" : ""}`}>
            {data.results.map((r) => (
              <ResultCard
                key={`${r.media_type}-${r.provider}-${r.provider_id}`}
                result={r}
                onOpen={() => setRecent(rememberSearch(query))}
              />
            ))}
          </div>
        )}
      </div>
    </>
  );
}
