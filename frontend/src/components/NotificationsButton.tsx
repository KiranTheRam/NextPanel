import { useEffect, useState } from "react";
import { currentSubscription, disablePush, enablePush, pushSupported } from "../api/push";
import { BellIcon, BellOffIcon } from "./icons";

/** Toggle web-push notifications for this device. Hidden when the browser
 * can't do push (e.g. iOS Safari outside an installed PWA). */
export default function NotificationsButton() {
  const [state, setState] = useState<"unsupported" | "off" | "on" | "busy">("unsupported");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!pushSupported()) return;
    currentSubscription()
      .then((sub) => setState(sub ? "on" : "off"))
      .catch(() => setState("off"));
  }, []);

  if (state === "unsupported") return null;

  const toggle = async () => {
    setError(null);
    setState("busy");
    try {
      if (state === "on") {
        await disablePush();
        setState("off");
      } else {
        await enablePush();
        setState("on");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setState(state);
    }
  };

  return (
    <>
      {error && <span style={{ color: "var(--danger)", fontSize: 12 }}>{error}</span>}
      <button
        className="btn"
        onClick={toggle}
        disabled={state === "busy"}
        title={state === "on" ? "Notifications are on — tap to turn off" : "Turn on notifications"}
      >
        {state === "on" ? <BellIcon size={15} /> : <BellOffIcon size={15} />}
        <span className="btn-label">{state === "on" ? "Notifications on" : "Notifications"}</span>
      </button>
    </>
  );
}
