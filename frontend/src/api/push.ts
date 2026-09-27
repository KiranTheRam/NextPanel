import { api } from "./client";

export function pushSupported(): boolean {
  return (
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const raw = atob((base64 + padding).replace(/-/g, "+").replace(/_/g, "/"));
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null;
  const registration = await navigator.serviceWorker.ready;
  return registration.pushManager.getSubscription();
}

export async function pushEndpointForLogout(): Promise<string> {
  if (!pushSupported()) return "";
  // getRegistration resolves even when service-worker startup failed; waiting
  // for `ready` here could leave Sign out waiting forever.
  const registration = await navigator.serviceWorker.getRegistration();
  return (await registration?.pushManager.getSubscription())?.endpoint ?? "";
}

/** Re-register an existing browser subscription for the signed-in user.
 *
 * Browser subscriptions live longer than login sessions. Logout removes their
 * server-side association; a later login binds the endpoint to the new user.
 */
export async function syncPushSubscription(): Promise<PushSubscription | null> {
  const subscription = await currentSubscription();
  if (subscription) {
    await api.post("/push/subscribe", subscription.toJSON());
  }
  return subscription;
}

export async function enablePush(): Promise<void> {
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    throw new Error("Notifications were not allowed by the browser");
  }
  const registration = await navigator.serviceWorker.ready;
  const { key } = await api.get<{ key: string }>("/push/key");
  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(key),
  });
  await api.post("/push/subscribe", subscription.toJSON());
}

export async function disablePush(): Promise<void> {
  const subscription = await currentSubscription();
  if (subscription) {
    await api.post("/push/unsubscribe", subscription.toJSON());
    await subscription.unsubscribe();
  }
}
