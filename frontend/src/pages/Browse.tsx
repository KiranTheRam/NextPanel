import { useInfiniteQuery } from "@tanstack/react-query";
import { useParams, useSearchParams } from "react-router";
import { api } from "../api/client";
import { useHideInLibrary } from "../api/preferences";
import type { BrowseResponse } from "../api/types";
import BackButton from "../components/BackButton";
import { EmptyState, LoadError, Spinner, Toolbar } from "../components/common";
import { SearchIcon } from "../components/icons";
import { TitleCard } from "../components/TitleCard";

type Origin = "all" | "manga" | "manhwa";

/**
 * A row's full listing ("See all") or a genre, paged. Manga sources can be
 * narrowed to manga or manhwa; comic rows are a single date window.
 */
export default function Browse() {
  const { source = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const genre = params.get("genre") ?? "";
  const origin = (params.get("origin") as Origin) || "all";
  const isComics = source.startsWith("comics_");
  const [hideInLibrary, setHideInLibrary] = useHideInLibrary();

  const listing = useInfiniteQuery({
    queryKey: ["discover", "browse", source, genre, origin],
    queryFn: ({ pageParam }) => {
      const query = new URLSearchParams({ source, origin, page: String(pageParam) });
      if (genre) query.set("genre", genre);
      return api.get<BrowseResponse>(`/discover/browse?${query}`);
    },
    initialPageParam: 1,
    getNextPageParam: (last, pages) => (last.has_more ? pages.length + 1 : undefined),
    staleTime: 30 * 60 * 1000,
  });

  const pages = listing.data?.pages ?? [];
  const title = pages[0]?.title ?? (genre || "Browse");
  // a title can sit on two AniList pages when popularity shifts between loads
  const seen = new Set<string>();
  const items = pages
    .flatMap((page) => page.items)
    .filter((item) => {
      const key = `${item.provider}-${item.provider_id}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return !(hideInLibrary && item.in_library);
    });
  const errors = pages.flatMap((page) => Object.values(page.errors));

  const setOrigin = (next: Origin) => {
    const updated = new URLSearchParams(params);
    if (next === "all") updated.delete("origin");
    else updated.set("origin", next);
    setParams(updated, { replace: true });
  };

  return (
    <>
      <Toolbar>
        <BackButton />
        <h1 className="toolbar-title">{title}</h1>
      </Toolbar>
      <div className="content">
        <div className="discover-options">
          {!isComics && (
            <div className="seg" role="group" aria-label="Origin">
              {(["all", "manga", "manhwa"] as const).map((o) => (
                <button
                  type="button"
                  key={o}
                  className={origin === o ? "active" : ""}
                  aria-pressed={origin === o}
                  onClick={() => setOrigin(o)}
                >
                  {o === "all" ? "All" : o === "manga" ? "Manga" : "Manhwa"}
                </button>
              ))}
            </div>
          )}
          <label className="check-option">
            <input
              type="checkbox"
              checked={hideInLibrary}
              onChange={(e) => setHideInLibrary(e.target.checked)}
            />
            Hide titles already in the library
          </label>
        </div>

        {listing.isPending && <Spinner />}
        {listing.isError && <LoadError error={listing.error} onRetry={() => listing.refetch()} />}
        {errors.length > 0 && (
          <div className="error-banner" role="alert" style={{ marginBottom: 12 }}>
            {errors[0]}{" "}
            <button className="btn" type="button" onClick={() => listing.refetch()}>Retry</button>
          </div>
        )}
        {listing.isSuccess && items.length === 0 && errors.length === 0 && (
          <EmptyState icon={<SearchIcon size={40} />} title="Nothing to show here" />
        )}
        {items.length > 0 && (
          <div className="browse-grid">
            {items.map((item) => (
              <TitleCard key={`${item.provider}-${item.provider_id}`} item={item} />
            ))}
          </div>
        )}
        {listing.hasNextPage && (
          <div className="load-more">
            <button
              className="btn"
              type="button"
              onClick={() => listing.fetchNextPage()}
              disabled={listing.isFetchingNextPage}
            >
              {listing.isFetchingNextPage ? "Loading…" : "Load more"}
            </button>
          </div>
        )}
      </div>
    </>
  );
}
