import { useState } from "react";
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

  const submit = useMutation({
    mutationFn: (path: string) => api.post(`/auth/${path}`, { username, password }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["me"] }),
  });

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
      <form className="login-card" onSubmit={onSubmit}>
        <div className="login-logo">
          <img src="/nextpanel-icon.svg" alt="" />
          NextPanel
        </div>
        <p style={{ color: "var(--text-dim)", fontSize: 13, textAlign: "center" }}>
          {effectiveMode === "setup"
            ? "First run — this account will approve requests and manage settings."
            : "Request manga and comics for the library."}
        </p>
        <h3 style={{ fontSize: 15 }}>{titles[effectiveMode]}</h3>
        <input
          placeholder="Username"
          value={username}
          autoFocus
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
            No account? <button type="button" onClick={() => setMode("register")}>Register</button>
          </div>
        )}
        {effectiveMode === "register" && (
          <div className="login-switch">
            Have an account? <button type="button" onClick={() => setMode("login")}>Sign in</button>
          </div>
        )}
      </form>
    </div>
  );
}
