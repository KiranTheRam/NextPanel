import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { MediaRequest, User } from "../api/types";
import { EmptyState, MediaBadge, Modal, Spinner, StatusPill, Toolbar } from "../components/common";

function Progress({ request }: { request: MediaRequest }) {
  if (!request.total_count) return null;
  return (
    <span style={{ color: "var(--text-faint)", fontSize: 12 }}>
      {request.downloaded_count}/{request.total_count}
    </span>
  );
}

function DenyModal({
  request,
  onClose,
}: {
  request: MediaRequest;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const deny = useMutation({
    mutationFn: () => api.post(`/requests/${request.id}/deny`, { reason }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["requests"] });
      onClose();
    },
  });
  return (
    <Modal title={`Deny "${request.title}"`} onClose={onClose}>
      <div className="form-row">
        <label>Reason (optional)</label>
        <input value={reason} onChange={(e) => setReason(e.target.value)} style={{ flex: 1 }} />
      </div>
      {deny.isError && <div className="error-banner">{(deny.error as Error).message}</div>}
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 12 }}>
        <button className="btn" onClick={onClose}>
          Cancel
        </button>
        <button className="btn danger" onClick={() => deny.mutate()} disabled={deny.isPending}>
          Deny Request
        </button>
      </div>
    </Modal>
  );
}

export default function Requests({ me }: { me: User }) {
  const queryClient = useQueryClient();
  const scope = me.is_admin ? "all" : "mine";
  const { data, isLoading } = useQuery({
    queryKey: ["requests", scope],
    queryFn: () => api.get<MediaRequest[]>(`/requests?scope=${scope}`),
    refetchInterval: 15000,
  });
  const [denying, setDenying] = useState<MediaRequest | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["requests"] });
    setActionError(null);
  };
  const onError = (e: unknown) => setActionError((e as Error).message);

  const approve = useMutation({
    mutationFn: (id: number) => api.post(`/requests/${id}/approve`, {}),
    onSuccess: invalidate,
    onError,
  });
  const withdraw = useMutation({
    mutationFn: (id: number) => api.del(`/requests/${id}`),
    onSuccess: invalidate,
    onError,
  });
  const refresh = useMutation({
    mutationFn: (id: number) => api.post(`/requests/${id}/refresh`),
    onSuccess: invalidate,
    onError,
  });

  if (isLoading || !data) {
    return (
      <>
        <Toolbar title="Requests" />
        <Spinner />
      </>
    );
  }

  return (
    <>
      <Toolbar title={me.is_admin ? "All Requests" : "My Requests"} />
      <div className="content">
        {actionError && (
          <div className="error-banner" style={{ marginBottom: 12 }}>
            {actionError}
          </div>
        )}
        {data.length === 0 ? (
          <EmptyState
            icon="≡"
            title="No requests yet"
            hint="Find something on the Discover page and request it."
          />
        ) : (
          <table className="data-table">
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
              {data.map((r) => (
                <tr key={r.id}>
                  <td style={{ width: 54 }}>
                    {r.cover_url ? (
                      <img className="request-cover" src={r.cover_url} alt="" loading="lazy" />
                    ) : (
                      <div className="request-cover" />
                    )}
                  </td>
                  <td>
                    <div style={{ fontWeight: 500 }}>
                      {r.english_title || r.title}
                      {r.year ? (
                        <span style={{ color: "var(--text-faint)", fontWeight: 400 }}> ({r.year})</span>
                      ) : null}
                    </div>
                    {r.note && (
                      <div style={{ color: "var(--text-faint)", fontSize: 12 }}>{r.note}</div>
                    )}
                  </td>
                  <td>
                    <MediaBadge mediaType={r.media_type} />
                  </td>
                  {me.is_admin && <td>{r.username}</td>}
                  <td>
                    <StatusPill status={r.status} />
                  </td>
                  <td>
                    <Progress request={r} />
                  </td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    {me.is_admin && (r.status === "pending" || r.status === "failed") && (
                      <>
                        <button
                          className="btn primary"
                          style={{ marginRight: 6 }}
                          disabled={approve.isPending}
                          onClick={() => approve.mutate(r.id)}
                        >
                          {r.status === "failed" ? "Retry" : "Approve"}
                        </button>
                        {r.status === "pending" && (
                          <button className="btn" onClick={() => setDenying(r)}>
                            Deny
                          </button>
                        )}
                      </>
                    )}
                    {(r.status === "processing" || r.status === "partially_available") && (
                      <button
                        className="btn icon-btn"
                        title="Refresh status"
                        disabled={refresh.isPending}
                        onClick={() => refresh.mutate(r.id)}
                      >
                        ⟳
                      </button>
                    )}
                    {(me.is_admin || r.status === "pending") && (
                      <button
                        className="btn icon-btn"
                        title={me.is_admin ? "Remove request" : "Withdraw request"}
                        disabled={withdraw.isPending}
                        onClick={() => withdraw.mutate(r.id)}
                        style={{ marginLeft: 6 }}
                      >
                        ✕
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {denying && <DenyModal request={denying} onClose={() => setDenying(null)} />}
    </>
  );
}
