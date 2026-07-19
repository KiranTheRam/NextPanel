import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { AuthStatus } from "../api/types";
import { Spinner } from "../components/common";

type Mode = "login" | "register" | "setup";

export default function Login() {
  const queryClient = useQueryClient();
  const { data: status } = useQuery({
    queryKey: ["authStatus"],
    queryFn: () => api.get<AuthStatus>("/auth/status"),
  });

  const [mode, setMode] = useState<Mode | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const attemptedSso = useRef(false);

  const submit = useMutation({
    mutationFn: (path: string) => api.post(`/auth/${path}`, { username, password }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["me"] }),
  });
  const sso = useMutation({
    mutationFn: () => api.post("/auth/sso"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["me"] }),
  });

  // A browser that reached NextPanel through Access already has a verified
  // Cloudflare session, so exchange it without making the user click twice.
  useEffect(() => {
    if (status?.sso_enabled && !attemptedSso.current) {
      attemptedSso.current = true;
      sso.mutate();
    }
  }, [status?.sso_enabled]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!status) {
    return (
      <div className="login-wrap">
        <Spinner />
      </div>
    );
  }

  const effectiveMode: Mode = status.setup_required ? "setup" : (mode ?? "login");
  const titles: Record<Mode, string> = {
    setup: "Create the admin account",
    register: "Create your account",
    login: "Sign in",
  };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    submit.mutate(effectiveMode);
  };

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div className="login-logo">
          <img src="/nextpanel-icon.svg" alt="" />
          NextPanel
        </div>
        <p style={{ color: "var(--text-dim)", fontSize: 13, textAlign: "center" }}>
          {effectiveMode === "setup"
            ? "First run — this account will approve requests and manage settings."
            : "Request manga and comics for the library."}
        </p>

        {status.sso_enabled && (
          <div style={{ display: "grid", gap: 10 }}>
            <button
              className="btn primary"
              type="button"
              disabled={sso.isPending}
              onClick={() => sso.mutate()}
            >
              {sso.isPending ? "Signing in with Cloudflare…" : "Sign in with Cloudflare Access"}
            </button>
            {sso.isError && (
              <div className="error-banner">
                {(sso.error as Error).message}. Open this site through its Cloudflare Access
                hostname and try again.
              </div>
            )}
          </div>
        )}

        {status.sso_enabled && status.local_login_enabled && (
          <div style={{ color: "var(--text-faint)", fontSize: 12, textAlign: "center" }}>
            or use a local account
          </div>
        )}

        {status.local_login_enabled && (
          <form onSubmit={onSubmit} style={{ display: "grid", gap: 12 }}>
            <h3 style={{ fontSize: 15 }}>{titles[effectiveMode]}</h3>
            <input
              placeholder="Username"
              value={username}
              autoFocus={!status.sso_enabled}
              autoComplete="username"
              onChange={(e) => setUsername(e.target.value)}
            />
            <input
              type="password"
              placeholder="Password"
              value={password}
              autoComplete={effectiveMode === "login" ? "current-password" : "new-password"}
              onChange={(e) => setPassword(e.target.value)}
            />
            {submit.isError && (
              <div className="error-banner">{(submit.error as Error).message}</div>
            )}
            <button
              className="btn primary"
              type="submit"
              disabled={!username || !password || submit.isPending}
            >
              {titles[effectiveMode]}
            </button>
            {effectiveMode === "login" && status.registration_enabled && (
              <div className="login-switch">
                No account?{" "}
                <button type="button" onClick={() => setMode("register")}>Register</button>
              </div>
            )}
            {effectiveMode === "register" && (
              <div className="login-switch">
                Have an account?{" "}
                <button type="button" onClick={() => setMode("login")}>Sign in</button>
              </div>
            )}
          </form>
        )}
      </div>
    </div>
  );
}
