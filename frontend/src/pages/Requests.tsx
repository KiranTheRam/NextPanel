import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { invalidateRequestViews } from "../api/cache";
import { titleHref } from "../api/paths";
import type { Issue, MediaRequest, MediaType, RequestStatus, RequestSummary, User } from "../api/types";
import { ConfirmModal, EmptyState, MediaBadge, Spinner, StatusPill, Toolbar } from "../components/common";
import { CheckIcon, InboxIcon, RefreshIcon, XIcon } from "../components/icons";
import NotificationsButton from "../components/NotificationsButton";
import { IssueActions, IssueStatusPill, issueKindLabel } from "../components/Issues";
import { ApprovalButtons } from "../components/RequestActions";

function Progress({ request }: { request: MediaRequest }) {
  if (!request.total_count) return null;
  return (
    <span style={{ color: "var(--text-faint)", fontSize: 12 }}>
      {request.downloaded_count}/{request.total_count}
    </span>
  );
}

type View = "pending" | "all" | "issues";

/** Problem reports: every user's for admins, your own otherwise. */
function IssuesView({ me }: { me: User }) {
  const [status, setStatus] = useState<"open" | "resolved" | "all">("open");
  const scope = me.is_admin ? "all" : "mine";
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["issues", "list", scope, status],
    queryFn: () => api.get<Issue[]>(`/issues?scope=${scope}&status=${status}`),
    refetchInterval: 30000,
  });
  return (
    <>
      <div className="request-filters">
        <select aria-label="Filter by report status" value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
          <option value="open">Open</option>
          <option value="resolved">Resolved</option>
          <option value="all">All reports</option>
        </select>
      </div>
      {isLoading && <Spinner />}
      {error && (
        <div className="error-banner" role="alert">
          Could not load reports: {(error as Error).message}{" "}
          <button className="btn" onClick={() => refetch()}>Retry</button>
        </div>
      )}
      {data && data.length === 0 && (
        <EmptyState
          icon={<CheckIcon size={40} />}
          title={status === "open" ? "No open problems" : "No reports"}
          hint={me.is_admin
            ? "Problems your users report on a title's page show up here."
            : "If something in the library is missing or wrong, report it from the title's page."}
        />
      )}
      {data && data.length > 0 && (
        <div className="table-wrap">
          <table className="data-table card-table issue-table">
            <thead>
              <tr>
                <th></th>
                <th>Title</th>
                <th>Problem</th>
                {me.is_admin && <th>Reported By</th>}
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data.map((issue) => (
                <tr key={issue.id}>
                  <td className="cell-cover">
                    {issue.cover_url ? (
                      <img className="request-cover" src={issue.cover_url} alt="" loading="lazy" />
                    ) : (
                      <div className="request-cover" />
                    )}
                  </td>
                  <td className="cell-rqtitle">
                    <Link className="request-title-link" to={titleHref(issue)}>{issue.title}</Link>
                    <div className="issue-meta">{new Date(issue.created_at).toLocaleDateString()}</div>
                  </td>
                  <td className="cell-problem">
                    <strong>{issueKindLabel(issue.kind)}</strong>
                    {issue.message && <div className="issue-message">{issue.message}</div>}
                    {issue.resolution && (
                      <div className="issue-resolution">
                        {issue.resolved_by_username || "Admin"}: {issue.resolution}
                      </div>
                    )}
                  </td>
                  {me.is_admin && <td className="cell-user">{issue.username}</td>}
                  <td className="cell-status"><IssueStatusPill issue={issue} /></td>
                  <td className="cell-actions"><IssueActions issue={issue} me={me} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export default function Requests({ me }: { me: User }) {
  // the tab lives in the URL so a notification can open Problems directly
  const [params, setParams] = useSearchParams();
  const defaultView: View = me.is_admin ? "pending" : "all";
  const view = (params.get("view") as View | null) ?? defaultView;
  const setView = (next: View) => setParams(next === defaultView ? {} : { view: next }, { replace: true });
  const { data: summary } = useQuery({
    queryKey: ["requests", "summary"],
    queryFn: () => api.get<RequestSummary>("/requests/summary"),
    refetchInterval: 15000,
  });

  const tabs: [View, string][] = me.is_admin
    ? [
        ["pending", `Needs Approval${summary?.needs_approval ? ` (${summary.needs_approval})` : ""}`],
        ["all", "All Requests"],
        ["issues", `Problems${summary?.open_issues ? ` (${summary.open_issues})` : ""}`],
      ]
    : [["all", "My Requests"], ["issues", "My Problem Reports"]];

  return (
    <>
      <Toolbar title={me.is_admin ? "Requests" : "My Requests"}>
        <NotificationsButton />
      </Toolbar>
      <div className="content">
        <div className="seg" role="tablist" style={{ display: "inline-flex", marginBottom: 16 }}>
          {tabs.map(([key, label]) => (
            <button
              key={key}
              role="tab"
              aria-selected={view === key}
              className={view === key ? "active" : ""}
              onClick={() => setView(key)}
            >
              {label}
            </button>
          ))}
        </div>
        {view === "issues" ? <IssuesView me={me} /> : <RequestsView me={me} view={view} />}
      </div>
    </>
  );
}

function RequestsView({ me, view }: { me: User; view: "pending" | "all" }) {
  const queryClient = useQueryClient();
  const scope = me.is_admin ? "all" : "mine";
  const [search, setSearch] = useState("");
  const [requester, setRequester] = useState("");
  const [mediaFilter, setMediaFilter] = useState<"all" | MediaType>("all");
  const [statusFilter, setStatusFilter] = useState<"all" | RequestStatus>("all");
  const { data, isLoading, error: loadError, refetch } = useQuery({
    queryKey: ["requests", scope],
    queryFn: () => api.get<MediaRequest[]>(`/requests?scope=${scope}`),
    refetchInterval: 15000,
  });
  const [removing, setRemoving] = useState<MediaRequest | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const invalidate = () => {
    invalidateRequestViews(queryClient);
    setActionError(null);
  };
  const onError = (e: unknown) => setActionError((e as Error).message);

  const withdraw = useMutation({
    mutationFn: (id: number) => api.del(`/requests/${id}`),
    onSuccess: () => {
      invalidate();
      setRemoving(null);
    },
  });
  const refresh = useMutation({
    mutationFn: (id: number) => api.post(`/requests/${id}/refresh`),
    onSuccess: invalidate,
    onError,
  });

  if (isLoading) return <Spinner />;
  if (!data) {
    return (
      <div className="error-banner" role="alert">
        Could not load requests: {loadError instanceof Error ? loadError.message : "Unknown error"}{" "}
        <button className="btn" onClick={() => refetch()}>Retry</button>
      </div>
    );
  }

  const rows = me.is_admin && view === "pending"
    ? data.filter((r) => r.status === "pending" || r.status === "failed")
    : data;
  const filteredRows = rows.filter((r) => {
    const needle = search.trim().toLowerCase();
    if (needle && !`${r.title} ${r.english_title}`.toLowerCase().includes(needle)) return false;
    if (me.is_admin && requester.trim() && !r.username.toLowerCase().includes(requester.trim().toLowerCase())) return false;
    if (mediaFilter !== "all" && r.media_type !== mediaFilter) return false;
    if (view === "all" && statusFilter !== "all" && r.status !== statusFilter) return false;
    return true;
  });

  return (
    <>
        <div className="request-filters">
          <input
            aria-label="Search request titles"
            placeholder="Search titles…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {me.is_admin && (
            <input
              aria-label="Filter by requester"
              placeholder="Requested by…"
              value={requester}
              onChange={(e) => setRequester(e.target.value)}
            />
          )}
          <select aria-label="Filter by media type" value={mediaFilter} onChange={(e) => setMediaFilter(e.target.value as "all" | MediaType)}>
            <option value="all">All types</option>
            <option value="manga">Manga</option>
            <option value="comic">Comics</option>
          </select>
          {view === "all" && (
            <select aria-label="Filter by status" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as "all" | RequestStatus)}>
              <option value="all">All statuses</option>
              <option value="pending">Pending</option>
              <option value="failed">Failed</option>
              <option value="processing">Processing</option>
              <option value="partially_available">Partially available</option>
              <option value="available">Available</option>
              <option value="denied">Denied</option>
            </select>
          )}
        </div>
        {actionError && (
          <div className="error-banner" style={{ marginBottom: 12 }}>
            {actionError}
          </div>
        )}
        {filteredRows.length === 0 ? (
          rows.length > 0 ? (
            <EmptyState icon={<InboxIcon size={40} />} title="No matching requests" hint="Try changing the search or filters." />
          ) : me.is_admin && view === "pending" ? (
            <EmptyState
              icon={<CheckIcon size={40} />}
              title="Nothing waiting for approval"
              hint="New requests from your users will show up here."
            />
          ) : (
            <EmptyState
              icon={<InboxIcon size={40} />}
              title="No requests yet"
              hint="Find something on the Discover page and request it."
            />
          )
        ) : (
          <div className="table-wrap">
            <table className="data-table card-table request-table">
              <thead>
                <tr>
                  <th></th>
                  <th>Title</th>
                  <th>Type</th>
                  {me.is_admin && <th>Requested By</th>}
                  <th>Status</th>
                  <th>Progress</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((r) => (
                  <tr key={r.id}>
                    <td className="cell-cover">
                      {r.cover_url ? (
                        <img className="request-cover" src={r.cover_url} alt="" loading="lazy" />
                      ) : (
                        <div className="request-cover" />
                      )}
                    </td>
                    <td className="cell-rqtitle">
                      <Link className="request-title-link" to={titleHref(r)}>
                        {r.english_title || r.title}
                        {r.year ? (
                          <span style={{ color: "var(--text-faint)", fontWeight: 400 }}> ({r.year})</span>
                        ) : null}
                      </Link>
                      {r.note && (
                        <div style={{ color: "var(--text-faint)", fontSize: 12 }}>{r.note}</div>
                      )}
                    </td>
                    <td className="cell-type">
                      <MediaBadge mediaType={r.media_type} />
                    </td>
                    {me.is_admin && <td className="cell-user">{r.username}</td>}
                    <td className="cell-status">
                      <StatusPill status={r.status} />
                    </td>
                    <td className="cell-progress">
                      <Progress request={r} />
                    </td>
                    <td className="cell-actions">
                      <div className="request-actions">
                        {me.is_admin && (
                          <ApprovalButtons
                            requestId={r.id}
                            status={r.status}
                            title={r.english_title || r.title}
                          />
                        )}
                        {(r.status === "processing" || r.status === "partially_available" || r.status === "available") && (
                          <button
                            className="btn icon-btn"
                            title="Refresh status"
                            aria-label="Refresh status"
                            disabled={refresh.isPending}
                            onClick={() => refresh.mutate(r.id)}
                          >
                            <RefreshIcon size={14} />
                          </button>
                        )}
                        {(me.is_admin || r.status === "pending") && (
                          <button
                            className="btn icon-btn"
                            title={me.is_admin ? "Remove request" : "Withdraw request"}
                            aria-label={me.is_admin ? "Remove request" : "Withdraw request"}
                            onClick={() => {
                              withdraw.reset();
                              setRemoving(r);
                            }}
                          >
                            <XIcon size={14} />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      {removing && (
        <ConfirmModal
          title={me.is_admin ? "Remove request?" : "Withdraw request?"}
          confirmLabel={me.is_admin ? "Remove request" : "Withdraw request"}
          busyLabel={me.is_admin ? "Removing…" : "Withdrawing…"}
          busy={withdraw.isPending}
          error={withdraw.isError ? (withdraw.error as Error).message : null}
          onConfirm={() => withdraw.mutate(removing.id)}
          onClose={() => setRemoving(null)}
        >
          <p>
            {me.is_admin && removing.username !== me.username
              ? `This deletes ${removing.username}'s request for `
              : "This deletes your request for "}
            <strong>{removing.english_title || removing.title}</strong>.
            {removing.remote_series_id != null
              ? " The series stays in your library; remove it there if you no longer want it."
              : ""}
          </p>
        </ConfirmModal>
      )}
    </>
  );
}
