import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { titleHref } from "../api/paths";
import type { DiscoverItem } from "../api/types";
import RequestButton from "./RequestButton";

export function TitleCard({ item }: { item: DiscoverItem }) {
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
          <span className="poster-flag orange">{item.request_status === "denied" ? "Denied" : "Requested"}</span>
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

/** A titled, horizontally scrolling row of cards. */
export function TitleRow({
  title,
  items,
  action,
}: {
  title: string;
  items: DiscoverItem[];
  action?: ReactNode;
}) {
  if (items.length === 0) return null;
  return (
    <section className="discover-section">
      <div className="section-header">
        <h3>{title}</h3>
        {action}
      </div>
      <div className="discover-row">
        {items.map((item) => (
          <TitleCard key={`${item.provider}-${item.provider_id}`} item={item} />
        ))}
      </div>
    </section>
  );
}
