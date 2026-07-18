import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { DiscoverItem, DiscoverResponse, SearchResponse, SearchResult } from "../api/types";
import { EmptyState, MediaBadge, Spinner, Toolbar } from "../components/common";
import { SearchIcon } from "../components/icons";
import RequestButton from "../components/RequestButton";

export function titleHref(
  item: { media_type: string; provider: string; provider_id: number; title: string },
): string {
  // the title hint lets providers without a by-id lookup (MangaUpdates,
  // ComicVine) resolve the detail page from a cold URL
  return `/title/${item.media_type}/${item.provider}/${item.provider_id}` +
    `?title=${encodeURIComponent(item.title)}`;
}

function DiscoverCard({ item }: { item: DiscoverItem }) {
  const displayTitle = item.english_title || item.title;
  return (
    <Link className="discover-card" to={titleHref(item)}>
      <div className="poster">
        {item.cover_url ? (
          <img src={item.cover_url} alt="" loading="lazy" />
        ) : (
          <div className="no-cover">{displayTitle}</div>
        )}
        {item.in_library && <span className="poster-flag green">In Library</span>}
        {!item.in_library && item.request_status && (
          <span className="poster-flag orange">Requested</span>
        )}
      </div>
      <div className="discover-card-title" title={displayTitle}>
        {displayTitle}
      </div>
      <div className="discover-card-meta">
        <span>{item.subtitle || (item.year ?? "")}</span>
        {item.score != null && <span className="discover-score">{item.score}%</span>}
      </div>
      <div className="discover-card-action">
        <RequestButton
          payload={{
            media_type: item.media_type,
            provider: item.provider,
            provider_id: item.provider_id,
            title: item.title,
            english_title: item.english_title,
            year: item.year,
            cover_url: item.cover_url,
            description: item.description,
          }}
          inLibrary={item.in_library}
          requestStatus={item.request_status}
          size="sm"
        />
      </div>
    </Link>
  );
}

function Recommendations() {
  const { data, isLoading } = useQuery({
    queryKey: ["discover"],
    queryFn: () => api.get<DiscoverResponse>("/discover"),
    staleTime: 5 * 60 * 1000,
  });

  if (isLoading) return <Spinner />;
  if (!data || data.sections.length === 0) {
    return (
      <EmptyState
        icon={<SearchIcon size={40} />}
        title="Search for something to request"
        hint="Manga results come from mangarr (MangaUpdates); comics from pullarr (ComicVine)."
      />
    );
  }
  return (
    <>
      {Object.keys(data.errors).length > 0 && (
        <div className="error-banner" style={{ marginBottom: 12 }}>
          Some recommendation rows could not be loaded.
        </div>
      )}
      {data.sections.map((section) => (
        <div className="discover-section" key={section.key}>
          <h3>{section.title}</h3>
          <div className="discover-row">
            {section.items.map((item) => (
              <DiscoverCard key={`${item.provider}-${item.provider_id}`} item={item} />
            ))}
          </div>
        </div>
      ))}
    </>
  );
}

function ResultCard({ result }: { result: SearchResult }) {
  const displayTitle = result.english_title || result.title;
  return (
    <Link className="result-card" to={titleHref(result)}>
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
          {result.publisher && <span>{result.publisher}</span>}
          {result.status && <span>{result.status}</span>}
          {result.total_count != null && (
            <span>
              {result.total_count} {result.media_type === "manga" ? "chapters" : "issues"}
            </span>
          )}
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

export default function Discover() {
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [mediaType, setMediaType] = useState<"all" | "manga" | "comic">("all");

  const { data, isFetching } = useQuery({
    queryKey: ["search", query, mediaType],
    queryFn: () =>
      api.get<SearchResponse>(
        `/search?q=${encodeURIComponent(query)}&media_type=${mediaType}`,
      ),
    enabled: query.length > 0,
  });

  const search = (e: React.FormEvent) => {
    e.preventDefault();
    setQuery(input.trim());
  };

  return (
    <>
      <Toolbar title="Discover" />
      <div className="content">
        <form className="search-bar" onSubmit={search}>
          <input
            placeholder="Search manga and comics…"
            value={input}
            autoFocus
            onChange={(e) => setInput(e.target.value)}
          />
          <div className="seg">
            {(["all", "manga", "comic"] as const).map((t) => (
              <button
                type="button"
                key={t}
                className={mediaType === t ? "active" : ""}
                onClick={() => setMediaType(t)}
              >
                {t === "all" ? "All" : t === "manga" ? "Manga" : "Comics"}
              </button>
            ))}
          </div>
          <button className="btn primary" type="submit" disabled={!input.trim()}>
            Search
          </button>
        </form>

        {Object.entries(data?.errors ?? {}).map(([app, message]) => (
          <div className="error-banner" key={app} style={{ marginBottom: 12 }}>
            {app}: {message}
          </div>
        ))}

        {isFetching && <Spinner />}
        {!isFetching && query && data && data.results.length === 0 && (
          <EmptyState icon={<SearchIcon size={40} />} title="No results" hint="Try another title or spelling." />
        )}
        {!query && <Recommendations />}
        {!isFetching && data && data.results.length > 0 && (
          <div className="results-grid">
            {data.results.map((r) => (
              <ResultCard key={`${r.media_type}-${r.provider_id}`} result={r} />
            ))}
          </div>
        )}
      </div>
    </>
  );
}
