import { useMutation, useQueryClient } from "@tanstack/react-query";
import { invalidateRequestViews } from "../api/cache";
import { api } from "../api/client";
import type { MediaType, RequestStatus } from "../api/types";
import { StatusPill } from "./common";

export interface RequestPayload {
  media_type: MediaType;
  provider: string;
  provider_id: number;
  title: string;
  english_title?: string;
  alt_titles?: string[];
  year?: number | null;
  cover_url?: string;
  description?: string;
}

/**
 * The one control every title surface shows: already shelved, already asked
 * for, or a button to ask. Keeping the three states in one place is what
 * makes a discover card, a search result and the detail page agree.
 */
export default function RequestButton({
  payload,
  inLibrary,
  requestStatus,
  size = "md",
  onRequested,
}: {
  payload: RequestPayload;
  inLibrary: boolean;
  requestStatus: RequestStatus | null;
  size?: "sm" | "md";
  onRequested?: () => void;
}) {
  const queryClient = useQueryClient();
  const request = useMutation({
    mutationFn: () => api.post("/requests", payload),
    onSuccess: () => {
      onRequested?.();
      invalidateRequestViews(queryClient);
    },
  });

  if (inLibrary) return <span className="pill green">In Library</span>;
  if (requestStatus && requestStatus !== "denied") return <StatusPill status={requestStatus} />;
  return (
    <>
      {requestStatus === "denied" && <StatusPill status="denied" />}
      <button
        className={`btn primary${size === "sm" ? " sm" : ""}`}
        disabled={request.isPending}
        onClick={(e) => {
          // cards are links; requesting must not also navigate
          e.preventDefault();
          e.stopPropagation();
          request.mutate();
        }}
      >
        {request.isPending ? "Requesting…" : requestStatus === "denied" ? "Request Again" : "Request"}
      </button>
      {request.isError && (
        <span className="request-error">{(request.error as Error).message}</span>
      )}
    </>
  );
}
