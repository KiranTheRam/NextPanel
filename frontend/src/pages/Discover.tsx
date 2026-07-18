import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { SearchResponse, SearchResult } from "../api/types";
import { EmptyState, MediaBadge, Spinner, StatusPill, Toolbar } from "../components/common";

function ResultCard({ result }: { result: SearchResult }) {
  const queryClient = useQueryClient();
  const request = useMutation({
    mutationFn: () =>
      api.post("/requests", {
        media_type: result.media_type,
        provider: result.provider,
        provider_id: result.provider_id,
        title: result.title,
        english_title: result.english_title,
        alt_titles: result.alt_titles,
        year: result.year,
        cover_url: result.cover_url,
        description: result.description,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["search"] });
      queryClient.invalidateQueries({ queryKey: ["requests"] });
    },
  });

  const displayTitle = result.english_title || result.title;
  return (
    <div className="result-card">
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
          {result.request_status ? (
            <StatusPill status={result.request_status} />
          ) : result.in_library ? (
            <span className="pill green">In Library</span>
          ) : (
            <button
              className="btn primary"
              disabled={request.isPending}
              onClick={() => request.mutate()}
            >
              Request
            </button>
          )}
          {request.isError && (
            <span style={{ color: "var(--danger)", fontSize: 12 }}>
              {(request.error as Error).message}
            </span>
          )}
        </div>
      </div>
    </div>
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
          <EmptyState icon="⌕" title="No results" hint="Try another title or spelling." />
        )}
        {!query && (
          <EmptyState
            icon="⌕"
            title="Search for something to request"
            hint="Manga results come from mangarr (MangaUpdates); comics from pullarr (ComicVine)."
          />
        )}
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
