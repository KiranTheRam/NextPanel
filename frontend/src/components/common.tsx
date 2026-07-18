import type { ReactNode } from "react";
import type { RequestStatus } from "../api/types";

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

export function EmptyState({ icon, title, hint }: { icon: string; title: string; hint?: string }) {
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
          <button onClick={onClose} style={{ fontSize: 18, color: "var(--text-dim)" }}>
            ✕
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

export function Toggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return <button type="button" className={`toggle${on ? " on" : ""}`} onClick={() => onChange(!on)} />;
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
