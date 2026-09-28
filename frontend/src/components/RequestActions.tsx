import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { invalidateRequestViews } from "../api/cache";
import { api } from "../api/client";
import type { RequestStatus } from "../api/types";
import { Modal } from "./common";

export function DenyModal({
  requestId,
  title,
  onClose,
}: {
  requestId: number;
  title: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const deny = useMutation({
    mutationFn: () => api.post(`/requests/${requestId}/deny`, { reason }),
    onSuccess: () => {
      invalidateRequestViews(queryClient);
      onClose();
    },
  });
  return (
    <Modal title={`Deny "${title}"`} onClose={onClose}>
      <div className="form-row">
        <label>Reason (optional)</label>
        <input value={reason} onChange={(e) => setReason(e.target.value)} style={{ flex: 1 }} />
      </div>
      {deny.isError && <div className="error-banner">{(deny.error as Error).message}</div>}
      <div className="modal-actions">
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

/** An admin's decision on one waiting request, wherever it is shown. */
export function ApprovalButtons({
  requestId,
  status,
  title,
}: {
  requestId: number;
  status: RequestStatus;
  title: string;
}) {
  const queryClient = useQueryClient();
  const [denying, setDenying] = useState(false);
  const approve = useMutation({
    mutationFn: () => api.post(`/requests/${requestId}/approve`, {}),
    onSuccess: () => invalidateRequestViews(queryClient),
  });
  if (status !== "pending" && status !== "failed") return null;
  return (
    <>
      <button className="btn primary" disabled={approve.isPending} onClick={() => approve.mutate()}>
        {approve.isPending ? "Approving…" : status === "failed" ? "Retry" : "Approve"}
      </button>
      {status === "pending" && (
        <button className="btn" onClick={() => setDenying(true)}>
          Deny
        </button>
      )}
      {approve.isError && <span className="request-error">{(approve.error as Error).message}</span>}
      {denying && <DenyModal requestId={requestId} title={title} onClose={() => setDenying(false)} />}
    </>
  );
}
