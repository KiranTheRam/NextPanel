import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type {
  AuthStatus,
  ConnectionTest,
  RootFolder,
  Settings as SettingsType,
} from "../api/types";
import { LoadError, Spinner, Toggle, Toolbar } from "../components/common";

function AppConnection({
  app,
  label,
  hint,
  form,
  setForm,
  saved,
}: {
  app: "mangarr" | "pullarr";
  label: string;
  hint: string;
  form: SettingsType;
  setForm: (f: SettingsType) => void;
  saved: SettingsType;
}) {
  const [test, setTest] = useState<{ ok: boolean; text: string } | null>(null);
  const runTest = useMutation({
    mutationFn: () =>
      api.post<ConnectionTest>(`/settings/test/${app}`, {
        url: form[`${app}_url`],
        api_key: form[`${app}_api_key`],
      }),
    onSuccess: (d) =>
      setTest(
        d.ok
          ? { ok: true, text: `Connected — ${label} ${d.version}` }
          : { ok: false, text: d.message },
      ),
    onError: (e) => setTest({ ok: false, text: (e as Error).message }),
  });

  // root folders can only be fetched with the *saved* connection
  const connectionSaved = !!saved[`${app}_url`] && !!saved[`${app}_api_key`];
  const { data: folders } = useQuery({
    queryKey: ["rootfolders", app, saved[`${app}_url`]],
    queryFn: () => api.get<RootFolder[]>(`/settings/rootfolders/${app}`),
    enabled: connectionSaved,
    retry: false,
  });

  const set = (key: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm({ ...form, [key]: e.target.value });

  return (
    <div className="settings-section">
      <h3>{label}</h3>
      <p className="section-hint">{hint}</p>
      <div className="form-row">
        <label>URL</label>
        <input type="text" value={form[`${app}_url`] ?? ""} onChange={set(`${app}_url`)} />
      </div>
      <div className="form-row">
        <label>API key</label>
        <input
          type="password"
          value={form[`${app}_api_key`] ?? ""}
          onChange={set(`${app}_api_key`)}
        />
      </div>
      <p className="section-hint">
        Shown by GET {"<"}url{">"}/initialize.json, or in the app's data dir under api_key.
      </p>
      <div className="form-row">
        <label>Default root folder</label>
        {folders ? (
          <select
            value={form[`${app}_root_folder_id`] ?? ""}
            onChange={set(`${app}_root_folder_id`)}
          >
            <option value="">— choose —</option>
            {folders.map((f) => (
              <option key={f.id} value={String(f.id)}>
                {f.path}
              </option>
            ))}
          </select>
        ) : (
          <span style={{ color: "var(--text-faint)", fontSize: 13 }}>
            {connectionSaved
              ? "Could not load root folders — check the connection."
              : "Save a working URL + API key first."}
          </span>
        )}
      </div>
      <div className="form-row">
        <label></label>
        <button className="btn" onClick={() => runTest.mutate()} disabled={runTest.isPending}>
          Test Connection
        </button>
        {test && (
          <span style={{ fontSize: 13, color: test.ok ? "var(--success)" : "var(--danger)" }}>
            {test.text}
          </span>
        )}
      </div>
    </div>
  );
}

function NtfySettings({
  form,
  setForm,
}: {
  form: SettingsType;
  setForm: (f: SettingsType) => void;
}) {
  const set = (key: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [key]: e.target.value });
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const test = useMutation({
    mutationFn: () =>
      api.post<ConnectionTest>("/settings/test/ntfy", {
        ntfy_url: form.ntfy_url ?? "",
        ntfy_token: form.ntfy_token ?? "",
        public_url: form.public_url ?? "",
      }),
    onSuccess: (d) => setResult({ ok: d.ok, text: d.message }),
    onError: (e) => setResult({ ok: false, text: (e as Error).message }),
  });
  return (
    <div className="settings-section">
      <h3>ntfy</h3>
      <p className="section-hint">
        Sends admin notifications (new requests waiting for approval, failed automatic approvals
        and problem reports) to an ntfy topic, for the ntfy app on your phone or desktop. This is
        in addition to browser notifications.
      </p>
      <div className="form-row">
        <label>Topic URL</label>
        <input
          type="url"
          placeholder="https://ntfy.sh/your-topic"
          value={form.ntfy_url ?? ""}
          onChange={set("ntfy_url")}
          style={{ minWidth: 300 }}
        />
      </div>
      <div className="form-row">
        <label>Access token</label>
        <input
          type="password"
          placeholder="Only for protected topics"
          value={form.ntfy_token ?? ""}
          onChange={set("ntfy_token")}
        />
      </div>
      <div className="form-row">
        <label>NextPanel address</label>
        <input
          type="url"
          placeholder={window.location.origin}
          value={form.public_url ?? ""}
          onChange={set("public_url")}
          style={{ minWidth: 300 }}
        />
        <button
          className="btn"
          type="button"
          onClick={() => setForm({ ...form, public_url: window.location.origin })}
        >
          Use this address
        </button>
      </div>
      <p className="section-hint">
        Tapping a notification opens this address. Leave it empty for notifications without a link.
      </p>
      <div className="form-row">
        <label>Completed requests</label>
        <Toggle
          label="Also announce completed requests"
          on={form.ntfy_notify_available === "true"}
          onChange={(v) => setForm({ ...form, ntfy_notify_available: v ? "true" : "false" })}
        />
        <span style={{ color: "var(--text-faint)", fontSize: 13 }}>
          Also send a message when a request finishes downloading.
        </span>
      </div>
      <div className="form-row">
        <label></label>
        <button className="btn" type="button" onClick={() => test.mutate()} disabled={test.isPending}>
          {test.isPending ? "Sending…" : "Send Test"}
        </button>
        {result && (
          <span style={{ fontSize: 13, color: result.ok ? "var(--success)" : "var(--danger)" }}>
            {result.text}
          </span>
        )}
      </div>
    </div>
  );
}

function randomSecret(): string {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export default function Settings() {
  const queryClient = useQueryClient();
  const { data: saved, isLoading, error: loadError, refetch } = useQuery({
    queryKey: ["settings"],
    queryFn: () => api.get<SettingsType>("/settings"),
  });
  const { data: authStatus } = useQuery({
    queryKey: ["authStatus"],
    queryFn: () => api.get<AuthStatus>("/auth/status"),
  });

  const [form, setForm] = useState<SettingsType>({});
  useEffect(() => {
    if (saved) setForm(saved);
  }, [saved]);

  const save = useMutation({
    mutationFn: () => api.put<SettingsType>("/settings", form),
    onSuccess: (data) => {
      queryClient.setQueryData(["settings"], data);
      setForm(data);
      queryClient.invalidateQueries({ queryKey: ["rootfolders"] });
    },
  });

  if (isLoading) {
    return (
      <>
        <Toolbar title="Settings" />
        <Spinner />
      </>
    );
  }
  if (!saved) {
    return <><Toolbar title="Settings" /><LoadError error={loadError} onRetry={() => refetch()} /></>;
  }

  const set = (key: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [key]: e.target.value });
  const setBool = (key: string) => (v: boolean) => setForm({ ...form, [key]: v ? "true" : "false" });

  return (
    <>
      <Toolbar title="Settings">
        {save.isError && (
          <span style={{ color: "var(--danger)", fontSize: 13 }}>
            {(save.error as Error).message}
          </span>
        )}
        {save.isSuccess && <span style={{ color: "var(--success)", fontSize: 13 }}>Saved</span>}
        <button className="btn primary" onClick={() => save.mutate()} disabled={save.isPending}>
          Save Changes
        </button>
      </Toolbar>
      <div className="content">
        <AppConnection
          app="mangarr"
          label="Mangarr (manga)"
          hint="Approved manga requests are added here, monitored, and searched immediately."
          form={form}
          setForm={setForm}
          saved={saved}
        />
        <AppConnection
          app="pullarr"
          label="Pullarr (comics)"
          hint="Approved comic requests are added here, monitored, and searched immediately."
          form={form}
          setForm={setForm}
          saved={saved}
        />

        <div className="settings-section">
          <h3>Webhooks</h3>
          <p className="section-hint">
            Mangarr and pullarr push an event here whenever they import files, so request status
            updates instantly. In each app's Settings, enable the webhook, set the URL to
            {" "}{window.location.origin}/api/v1/webhooks/mangarr (or /pullarr) and paste this same
            secret. Requests are also re-checked on a schedule as a fallback.
          </p>
          <div className="form-row">
            <label>Webhook secret</label>
            <input
              type="text"
              value={form.webhook_secret ?? ""}
              onChange={set("webhook_secret")}
              style={{ minWidth: 340 }}
            />
            <button
              className="btn"
              onClick={() => setForm({ ...form, webhook_secret: randomSecret() })}
            >
              Generate
            </button>
          </div>
          <div className="form-row">
            <label>Poll interval (minutes)</label>
            <input
              type="text"
              value={form.poll_interval_minutes ?? ""}
              onChange={set("poll_interval_minutes")}
            />
          </div>
        </div>

        <NtfySettings form={form} setForm={setForm} />

        <div className="settings-section">
          <h3>Requests</h3>
          <p className="section-hint">
            Admins' own requests, and those of users marked Auto-approve on the Users page, go
            straight to Mangarr or Pullarr. Everyone else's wait for approval.
          </p>
          <div className="form-row">
            <label>Pending limit per user</label>
            <input
              type="number"
              min={0}
              inputMode="numeric"
              value={form.max_pending_requests ?? ""}
              onChange={set("max_pending_requests")}
              style={{ width: 90 }}
            />
            <span style={{ color: "var(--text-faint)", fontSize: 13 }}>
              How many undecided requests one person may have at a time. 0 = no limit.
            </span>
          </div>
        </div>

        <div className="settings-section">
          <h3>Access</h3>
          <p className="section-hint">
            Cloudflare Access SSO is {authStatus?.sso_enabled ? "enabled" : "not configured"}.
            Configure its team domain and application audience with container environment
            variables. Local login is {authStatus?.local_login_enabled ? "enabled" : "disabled"}.
          </p>
          <div className="form-row">
            <label>Open registration</label>
            <Toggle
              label="Open registration"
              on={!!authStatus?.local_login_enabled && form.registration_enabled === "true"}
              onChange={setBool("registration_enabled")}
              disabled={!authStatus?.local_login_enabled}
            />
            <span style={{ color: "var(--text-faint)", fontSize: 13 }}>
              Let anyone who can reach this page create an account. Off = admins create users.
            </span>
          </div>
        </div>
      </div>
    </>
  );
}
