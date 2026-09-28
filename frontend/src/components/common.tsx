import type { ReactNode } from "react";
import type { RequestStatus } from "../api/types";
import { XIcon } from "./icons";

export function Toolbar({
  title,
  className = "",
  children,
}: {
  title?: string;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <div className={`toolbar${className ? ` ${className}` : ""}`}>
      {title && <h1>{title}</h1>}
      {children}
    </div>
  );
}

export function Spinner() {
  return (
    <div className="center">
      <div className="spinner" />
    </div>
  );
}

export function LoadError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <div className="content">
      <div className="error-banner" role="alert">
        Could not load this page: {error instanceof Error ? error.message : "Unknown error"}
      </div>
      <button className="btn" onClick={onRetry}>Retry</button>
    </div>
  );
}

export function EmptyState({ icon, title, hint }: { icon: ReactNode; title: string; hint?: string }) {
  return (
    <div className="empty-state">
      <div className="big">{icon}</div>
      <h3>{title}</h3>
      {hint && <p style={{ marginTop: 8 }}>{hint}</p>}
    </div>
  );
}

export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          {title}
          <button onClick={onClose} style={{ color: "var(--text-dim)", display: "inline-flex" }} aria-label="Close">
            <XIcon />
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

/** Ask before an action that cannot be undone. */
export function ConfirmModal({
  title,
  children,
  confirmLabel,
  busyLabel,
  busy = false,
  error,
  onConfirm,
  onClose,
}: {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  busyLabel?: string;
  busy?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Modal title={title} onClose={() => { if (!busy) onClose(); }}>
      {children}
      {error && <div className="error-banner" role="alert" style={{ marginTop: 12 }}>{error}</div>}
      <div className="modal-actions">
        <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
        <button className="btn danger" onClick={onConfirm} disabled={busy}>
          {busy ? busyLabel ?? confirmLabel : confirmLabel}
        </button>
      </div>
    </Modal>
  );
}

export function Toggle({
  on,
  onChange,
  disabled = false,
  label,
}: {
  on: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  label?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      className={`toggle${on ? " on" : ""}`}
      disabled={disabled}
      onClick={() => onChange(!on)}
    />
  );
}

const STATUS_META: Record<RequestStatus, { label: string; color: string }> = {
  pending: { label: "Pending", color: "orange" },
  denied: { label: "Denied", color: "red" },
  processing: { label: "Processing", color: "blue" },
  partially_available: { label: "Partially Available", color: "orange" },
  available: { label: "Available", color: "green" },
  failed: { label: "Failed", color: "red" },
};

export function StatusPill({ status }: { status: RequestStatus }) {
  const meta = STATUS_META[status] ?? { label: status, color: "gray" };
  return <span className={`pill ${meta.color}`}>{meta.label}</span>;
}

export function MediaBadge({ mediaType }: { mediaType: "manga" | "comic" }) {
  return (
    <span className={`media-badge ${mediaType}`}>{mediaType === "manga" ? "Manga" : "Comic"}</span>
  );
}
