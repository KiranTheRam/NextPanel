import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Issue, IssueKind, MediaType, User } from "../api/types";
import { ConfirmModal, Modal } from "./common";

export const ISSUE_KINDS: { value: IssueKind; label: string; hint: string }[] = [
  { value: "missing", label: "Missing chapters or issues", hint: "Some are not in the library" },
  { value: "wrong_series", label: "Wrong series", hint: "The library has a different title" },
  { value: "bad_files", label: "Bad files", hint: "Unreadable, wrong language or poor quality" },
  { value: "other", label: "Something else", hint: "" },
];

export function issueKindLabel(kind: IssueKind): string {
  return ISSUE_KINDS.find((k) => k.value === kind)?.label ?? kind;
}

export function invalidateIssues(queryClient: ReturnType<typeof useQueryClient>): void {
  void queryClient.invalidateQueries({ queryKey: ["issues"] });
  void queryClient.invalidateQueries({ queryKey: ["requests", "summary"] });
}

export interface IssueSubject {
  media_type: MediaType;
  provider: string;
  provider_id: number;
  title: string;
  cover_url: string;
}

export function ReportIssueModal({
  subject,
  displayTitle,
  onClose,
}: {
  subject: IssueSubject;
  displayTitle: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<IssueKind>("missing");
  const [message, setMessage] = useState("");
  const report = useMutation({
    mutationFn: () => api.post<Issue>("/issues", { ...subject, kind, message }),
    onSuccess: () => {
      invalidateIssues(queryClient);
      onClose();
    },
  });
  return (
    <Modal title={`Report a problem with "${displayTitle}"`} onClose={onClose}>
      <fieldset className="issue-kinds">
        <legend>What is wrong?</legend>
        {ISSUE_KINDS.map((k) => (
          <label key={k.value} className="issue-kind">
            <input
              type="radio"
              name="issue-kind"
              value={k.value}
              checked={kind === k.value}
              onChange={() => setKind(k.value)}
            />
            <span>
              {k.label}
              {k.hint && <small>{k.hint}</small>}
            </span>
          </label>
        ))}
      </fieldset>
      <label className="field-label" htmlFor="issue-message">Details</label>
      <textarea
        id="issue-message"
        rows={4}
        maxLength={2000}
        placeholder={kind === "missing" ? "Which chapters or issues?" : "What should the admin know?"}
        value={message}
        onChange={(e) => setMessage(e.target.value)}
      />
      {report.isError && <div className="error-banner">{(report.error as Error).message}</div>}
      <div className="modal-actions">
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn primary" onClick={() => report.mutate()} disabled={report.isPending}>
          {report.isPending ? "Sending…" : "Send report"}
        </button>
      </div>
    </Modal>
  );
}

export function IssueStatusPill({ issue }: { issue: Issue }) {
  return issue.status === "open"
    ? <span className="pill orange">Open</span>
    : <span className="pill green">Resolved</span>;
}

function ResolveModal({ issue, onClose }: { issue: Issue; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [resolution, setResolution] = useState("");
  const resolve = useMutation({
    mutationFn: () => api.post(`/issues/${issue.id}/resolve`, { resolution }),
    onSuccess: () => {
      invalidateIssues(queryClient);
      onClose();
    },
  });
  return (
    <Modal title={`Resolve "${issue.title}"`} onClose={onClose}>
      <label className="field-label" htmlFor="issue-resolution">Note for {issue.username} (optional)</label>
      <textarea
        id="issue-resolution"
        rows={3}
        maxLength={2000}
        placeholder="e.g. Re-downloaded chapters 40-45"
        value={resolution}
        onChange={(e) => setResolution(e.target.value)}
      />
      {resolve.isError && <div className="error-banner">{(resolve.error as Error).message}</div>}
      <div className="modal-actions">
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn primary" onClick={() => resolve.mutate()} disabled={resolve.isPending}>
          Mark resolved
        </button>
      </div>
    </Modal>
  );
}

/** Resolve/reopen for admins; withdraw for the reporter while open. */
export function IssueActions({ issue, me }: { issue: Issue; me: User }) {
  const queryClient = useQueryClient();
  const [resolving, setResolving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const reopen = useMutation({
    mutationFn: () => api.post(`/issues/${issue.id}/reopen`),
    onSuccess: () => invalidateIssues(queryClient),
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/issues/${issue.id}`),
    onSuccess: () => {
      invalidateIssues(queryClient);
      setDeleting(false);
    },
  });
  const own = issue.username === me.username;
  const canDelete = me.is_admin || (own && issue.status === "open");
  return (
    <div className="request-actions">
      {me.is_admin && issue.status === "open" && (
        <button className="btn primary sm" onClick={() => setResolving(true)}>Resolve</button>
      )}
      {me.is_admin && issue.status === "resolved" && (
        <button className="btn sm" onClick={() => reopen.mutate()} disabled={reopen.isPending}>Reopen</button>
      )}
      {canDelete && (
        <button className="btn sm" onClick={() => { remove.reset(); setDeleting(true); }}>
          {me.is_admin ? "Delete" : "Withdraw"}
        </button>
      )}
      {resolving && <ResolveModal issue={issue} onClose={() => setResolving(false)} />}
      {deleting && (
        <ConfirmModal
          title={me.is_admin ? "Delete report?" : "Withdraw report?"}
          confirmLabel={me.is_admin ? "Delete report" : "Withdraw report"}
          busy={remove.isPending}
          error={remove.isError ? (remove.error as Error).message : null}
          onConfirm={() => remove.mutate()}
          onClose={() => setDeleting(false)}
        >
          <p>
            {own ? "Your" : `${issue.username}'s`} report about <strong>{issue.title}</strong>{" "}
            ({issueKindLabel(issue.kind).toLowerCase()}) will be removed.
          </p>
        </ConfirmModal>
      )}
    </div>
  );
}
