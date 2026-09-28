import { useLocation, useNavigate } from "react-router-dom";
import { ChevronLeftIcon } from "./icons";

/**
 * Back to wherever you came from — search results, a discover row, or the
 * requests list — rather than always to the Discover home. Opening a title
 * from a cold link has nothing to go back to, so that case falls through to
 * Discover instead of leaving the app.
 */
export default function BackButton() {
  const navigate = useNavigate();
  const location = useLocation();
  // react-router stamps an index onto history entries it created; index 0 (or
  // a missing one) means this entry is the first of the session
  const historyIndex = (window.history.state as { idx?: number } | null)?.idx ?? 0;
  const canGoBack = historyIndex > 0 && location.key !== "default";

  return (
    <button className="btn" onClick={() => (canGoBack ? navigate(-1) : navigate("/"))}>
      <ChevronLeftIcon size={15} />
      Back
    </button>
  );
}
