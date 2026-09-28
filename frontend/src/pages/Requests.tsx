import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { invalidateRequestViews } from "../api/cache";
import { titleHref } from "../api/paths";
import type { MediaRequest, MediaType, RequestStatus, User } from "../api/types";
import { ConfirmModal, EmptyState, LoadError, MediaBadge, Spinner, StatusPill, Toolbar } from "../components/common";
import { CheckIcon, InboxIcon, RefreshIcon, XIcon } from "../components/icons";
import NotificationsButton from "../components/NotificationsButton";
import { ApprovalButtons } from "../components/RequestActions";

function Progress({ request }: { request: MediaRequest }) {
  if (!request.total_count) return null;
  return (
    <span style={{ color: "var(--text-faint)", fontSize: 12 }}>
      {request.downloaded_count}/{request.total_count}
    </span>
  );
}

export default function Requests({ me }: { me: User }) {
  const queryClient = useQueryClient();
  const scope = me.is_admin ? "all" : "mine";
  // admins land on the approval queue; switch to All for history
  const [view, setView] = useState<"pending" | "all">(me.is_admin ? "pending" : "all");
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

  if (isLoading) {
    return (
      <>
        <Toolbar title="Requests" />
        <Spinner />
      </>
    );
  }
  if (!data) {
    return <><Toolbar title="Requests" /><LoadError error={loadError} onRetry={() => refetch()} /></>;
  }

  const pendingCount = data.filter((r) => r.status === "pending" || r.status === "failed").length;
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
      <Toolbar title={me.is_admin ? "Requests" : "My Requests"}>
        <NotificationsButton />
      </Toolbar>
      <div className="content">
        {me.is_admin && (
          <div className="seg" style={{ display: "inline-flex", marginBottom: 16 }}>
            <button
              className={view === "pending" ? "active" : ""}
              onClick={() => setView("pending")}
            >
              Needs Approval{pendingCount ? ` (${pendingCount})` : ""}
            </button>
            <button className={view === "all" ? "active" : ""} onClick={() => setView("all")}>
              All Requests
            </button>
          </div>
        )}
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
      </div>
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
