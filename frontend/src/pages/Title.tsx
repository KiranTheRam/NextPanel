import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { countOf } from "../api/paths";
import type { Chapter, Issue, TitleDetail, User } from "../api/types";
import { EmptyState, MediaBadge, Spinner, Toolbar } from "../components/common";
import BackButton from "../components/BackButton";
import { CheckIcon, SearchIcon } from "../components/icons";
import RequestButton from "../components/RequestButton";
import { ApprovalButtons } from "../components/RequestActions";
import { IssueActions, IssueStatusPill, ReportIssueModal, issueKindLabel } from "../components/Issues";
import { TitleRow } from "../components/TitleCard";

const SERIES_STATUS: Record<string, { label: string; color: string }> = {
  releasing: { label: "Releasing", color: "green" },
  ongoing: { label: "Releasing", color: "green" },
  finished: { label: "Finished", color: "blue" },
  ended: { label: "Finished", color: "blue" },
  completed: { label: "Finished", color: "blue" },
  hiatus: { label: "Hiatus", color: "orange" },
  cancelled: { label: "Cancelled", color: "red" },
  not_yet_released: { label: "Not Yet Released", color: "gray" },
};

function SeriesStatusPill({ status }: { status: string }) {
  // MangaUpdates reports "unknown" for plenty of series — say nothing rather
  // than show a pill that carries no information
  if (!status || status === "unknown") return null;
  const meta = SERIES_STATUS[status] ?? {
    label: status.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    color: "gray",
  };
  return <span className={`pill ${meta.color}`}>{meta.label}</span>;
}

function ChapterRow({ chapter, unit }: { chapter: Chapter; unit: string }) {
  return (
    <div className={`chapter-row${chapter.downloaded ? " downloaded" : ""}`}>
      <span className="chapter-number">
        {unit} {chapter.label || chapter.number}
      </span>
      <span className="chapter-title">{chapter.title || <em>Untitled</em>}</span>
      {chapter.volume != null && <span className="chapter-volume">Vol. {chapter.volume}</span>}
      <span className="chapter-state">
        {chapter.downloaded ? (
          <span className="downloaded-mark" title="Downloaded">
            <CheckIcon size={15} />
          </span>
        ) : (
          <span className="pill gray">Missing</span>
        )}
      </span>
    </div>
  );
}

function ChapterList({ detail }: { detail: TitleDetail }) {
  const unit = detail.media_type === "manga" ? "Ch." : "#";
  const [filter, setFilter] = useState("");
  const [missingOnly, setMissingOnly] = useState(false);

  const shown = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return detail.chapters.filter((c) => {
      if (missingOnly && c.downloaded) return false;
      if (!needle) return true;
      return `${c.label} ${c.number ?? ""} ${c.title}`.toLowerCase().includes(needle);
    });
  }, [detail.chapters, filter, missingOnly]);

  if (!detail.chapters_available) {
    return (
      <div className="panel-note">
        {detail.total_count
          ? `${countOf(detail.total_count, detail.media_type)} known to the metadata provider. `
          : ""}
        The full list appears once the series is in your library.
      </div>
    );
  }

  return (
    <>
      <div className="chapter-tools">
        <input
          className="chapter-filter"
          placeholder={`Filter ${detail.media_type === "manga" ? "chapters" : "issues"}…`}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <label className="chapter-toggle">
          <input
            type="checkbox"
            checked={missingOnly}
            onChange={(e) => setMissingOnly(e.target.checked)}
          />
          Missing only
        </label>
        <span className="chapter-count">
          {detail.downloaded_count} of {detail.chapters.length} downloaded
        </span>
      </div>
      <div className="chapter-list">
        {shown.map((c, i) => (
          <ChapterRow key={`${c.label}-${c.number}-${i}`} chapter={c} unit={unit} />
        ))}
        {shown.length === 0 && <div className="panel-note">Nothing matches that filter.</div>}
      </div>
    </>
  );
}

/** Open problem reports about this title: all of them for admins, your own
 * otherwise. */
function TitleIssues({ detail, me }: { detail: TitleDetail; me: User }) {
  const params = new URLSearchParams({
    scope: me.is_admin ? "all" : "mine",
    status: "open",
    media_type: detail.media_type,
    provider: detail.provider,
    provider_id: String(detail.provider_id),
  });
  const { data } = useQuery({
    queryKey: ["issues", "title", params.toString()],
    queryFn: () => api.get<Issue[]>(`/issues?${params}`),
  });
  if (!data?.length) return null;
  return (
    <div className="panel">
      <h3>Reported problems</h3>
      <ul className="issue-list">
        {data.map((issue) => (
          <li key={issue.id}>
            <div className="issue-head">
              <IssueStatusPill issue={issue} />
              <strong>{issueKindLabel(issue.kind)}</strong>
              <span className="issue-meta">
                {me.is_admin ? `${issue.username} · ` : ""}
                {new Date(issue.created_at).toLocaleDateString()}
              </span>
            </div>
            {issue.message && <p className="issue-message">{issue.message}</p>}
            <IssueActions issue={issue} me={me} />
          </li>
        ))}
      </ul>
    </div>
  );
}

const REPORTABLE = new Set(["processing", "partially_available", "available"]);

export default function Title({ me }: { me: User }) {
  const { mediaType, provider, providerId } = useParams();
  const [params] = useSearchParams();
  const titleHint = params.get("title") ?? "";

  const { data, isLoading, error } = useQuery({
    queryKey: ["detail", mediaType, provider, providerId, titleHint],
    queryFn: () =>
      api.get<TitleDetail>(
        `/detail/${mediaType}/${provider}/${providerId}?title=${encodeURIComponent(titleHint)}`,
      ),
    retry: false,
  });
  const [reporting, setReporting] = useState(false);

  if (isLoading) return <Spinner />;
  if (!data) {
    const message =
      error instanceof ApiError && error.status === 404
        ? "No metadata could be found for this title."
        : (error as Error)?.message;
    return (
      <>
        <Toolbar>
          <BackButton />
        </Toolbar>
        <div className="content">
          <EmptyState icon={<SearchIcon size={40} />} title="Not found" hint={message} />
        </div>
      </>
    );
  }

  const displayTitle = data.english_title || data.title;
  const canReport = data.in_library || REPORTABLE.has(data.request_status ?? "");
  const altTitle = data.english_title && data.title !== data.english_title ? data.title : data.native_title;
  const years = data.year
    ? `${data.year}${data.end_year && data.end_year !== data.year ? `–${data.end_year}` : ""}`
    : "";

  return (
    <>
      <Toolbar>
        <BackButton />
      </Toolbar>
      <div className="content title-page">
        {data.banner_url && (
          <div className="title-banner" style={{ backgroundImage: `url(${data.banner_url})` }} />
        )}
        <div className="title-header">
          {data.cover_url ? (
            <img className="title-cover" src={data.cover_url} alt="" />
          ) : (
            <div className="title-cover no-cover">{displayTitle}</div>
          )}
          <div className="title-info">
            <h2>{displayTitle}</h2>
            {altTitle && <div className="title-alt">{altTitle}</div>}
            <div className="title-meta">
              <MediaBadge mediaType={data.media_type} />
              <SeriesStatusPill status={data.status} />
              {years && <span>{years}</span>}
              {data.publisher && <span>{data.publisher}</span>}
              {data.score != null && <span className="discover-score">{data.score}%</span>}
              {data.total_count != null && (
                <span>
                  {countOf(data.total_count, data.media_type)}
                </span>
              )}
              {data.volumes != null && (
                <span>{data.volumes} volume{data.volumes === 1 ? "" : "s"}</span>
              )}
            </div>
            {data.genres.length > 0 && (
              <div className="genre-row">
                {data.genres.map((g) => (
                  <span className="genre-chip" key={g}>{g}</span>
                ))}
              </div>
            )}
            <div className="title-actions">
              <RequestButton
                payload={{
                  media_type: data.media_type,
                  provider: data.provider,
                  provider_id: data.provider_id,
                  title: data.title,
                  english_title: data.english_title,
                  year: data.year,
                  cover_url: data.cover_url,
                  description: data.description,
                }}
                inLibrary={data.in_library}
                requestStatus={data.request_status}
              />
              {me.is_admin && data.request_id != null && data.request_status && (
                <ApprovalButtons
                  requestId={data.request_id}
                  status={data.request_status}
                  title={displayTitle}
                />
              )}
              {canReport && (
                <button className="btn" onClick={() => setReporting(true)}>
                  Report a problem
                </button>
              )}
            </div>
            {data.staff.length > 0 && (
              <div className="title-staff">
                {data.staff.map((s) => (
                  <span key={`${s.name}-${s.role}`}>
                    <strong>{s.name}</strong>
                    {s.role ? ` — ${s.role}` : ""}
                  </span>
                ))}
              </div>
            )}
            {data.links.length > 0 && (
              <div className="title-links" aria-label="Elsewhere">
                {data.links.map((link) => (
                  <a
                    key={link.url}
                    className="btn sm"
                    href={link.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {link.label} ↗
                  </a>
                ))}
              </div>
            )}
          </div>
        </div>

        {data.description && (
          <div className="panel">
            <h3>Overview</h3>
            <p className="title-description">{data.description}</p>
          </div>
        )}

        <TitleIssues detail={data} me={me} />

        <div className="panel">
          <h3>{data.media_type === "manga" ? "Chapters" : "Issues"}</h3>
          <ChapterList detail={data} />
        </div>

        <TitleRow title="Related" items={data.related} />
        <TitleRow title="You might also like" items={data.recommendations} />
      </div>
      {reporting && (
        <ReportIssueModal
          subject={{
            media_type: data.media_type,
            provider: data.provider,
            provider_id: data.provider_id,
            title: displayTitle,
            cover_url: data.cover_url,
          }}
          displayTitle={displayTitle}
          onClose={() => setReporting(false)}
        />
      )}
    </>
  );
}
