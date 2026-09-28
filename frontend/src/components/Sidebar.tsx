import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink } from "react-router-dom";
import { api, appVersion } from "../api/client";
import { pushEndpointForLogout } from "../api/push";
import type { AuthStatus, RequestSummary, User } from "../api/types";
import { InboxIcon, KeyIcon, LogOutIcon, SearchIcon, SettingsIcon, UserIcon, UsersIcon } from "./icons";
import { ChangePasswordModal } from "./password";
import { Modal } from "./common";

export default function Sidebar({ me }: { me: User }) {
  const queryClient = useQueryClient();
  const [changingPassword, setChangingPassword] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [signOutError, setSignOutError] = useState("");
  const { data: authStatus } = useQuery({
    queryKey: ["authStatus"],
    queryFn: () => api.get<AuthStatus>("/auth/status"),
  });
  // pending-approval badge for admins; a count, not the whole request list
  const { data: pending } = useQuery({
    queryKey: ["requests", "summary"],
    queryFn: () => api.get<RequestSummary>("/requests/summary"),
    enabled: me.is_admin,
    refetchInterval: 15000,
    select: (summary) => summary.needs_approval + summary.open_issues,
  });

  const items = [
    { to: "/", label: "Discover", icon: <SearchIcon /> },
    { to: "/requests", label: "Requests", icon: <InboxIcon /> },
    ...(me.is_admin
      ? [
          { to: "/users", label: "Users", icon: <UsersIcon /> },
          { to: "/settings", label: "Settings", icon: <SettingsIcon /> },
        ]
      : []),
  ];

  const logout = async () => {
    setSigningOut(true);
    setSignOutError("");
    try {
      const pushEndpoint = await pushEndpointForLogout().catch(() => "");
      await api.post("/auth/logout", { push_endpoint: pushEndpoint });
      queryClient.clear();
      window.location.href = authStatus?.sso_enabled ? "/cdn-cgi/access/logout" : "/";
    } catch (error) {
      setSignOutError((error as Error).message);
      setSigningOut(false);
    }
  };

  return (
    <div className="sidebar">
      <div className="sidebar-logo">
        <img className="logo-mark" src="/nextpanel-icon.svg" alt="" />
        NextPanel
      </div>
      <nav>
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
          >
            <span className="icon">{item.icon}</span>
            <span className="nav-label">{item.label}</span>
            {item.to === "/requests" && me.is_admin && !!pending && (
              <span className="nav-badge">{pending}</span>
            )}
          </NavLink>
        ))}
        <button className="nav-item mobile-account" onClick={() => setAccountOpen(true)}>
          <span className="icon"><UserIcon /></span>
          <span className="nav-label">Account</span>
        </button>
      </nav>
      <div className="sidebar-footer">
        <div style={{ marginBottom: 6, display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
            {me.username}
            {me.is_admin && <span style={{ color: "var(--text-faint)" }}> · admin</span>}
          </span>
          {authStatus?.local_login_enabled && !me.sso_only && (
            <button
              onClick={() => setChangingPassword(true)}
              title="Change password"
              aria-label="Change password"
              style={{ color: "var(--text-dim)", display: "inline-flex", marginLeft: "auto" }}
            >
              <KeyIcon size={15} />
            </button>
          )}
          <button
            onClick={logout}
            disabled={signingOut}
            title="Sign out"
            aria-label="Sign out"
            style={{ color: "var(--accent-hover)", display: "inline-flex" }}
          >
            <LogOutIcon size={15} />
          </button>
        </div>
        {signOutError && <div role="alert" style={{ color: "var(--danger)" }}>{signOutError}</div>}
        v{appVersion()}
      </div>
      {accountOpen && (
        <Modal title="Account" onClose={() => setAccountOpen(false)}>
          <p style={{ marginBottom: 16 }}>{me.username}{me.is_admin ? " · admin" : ""}</p>
          {signOutError && <div className="error-banner" role="alert">{signOutError}</div>}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
            {authStatus?.local_login_enabled && !me.sso_only && (
              <button className="btn" onClick={() => { setAccountOpen(false); setChangingPassword(true); }}>
                <KeyIcon size={15} /> Change password
              </button>
            )}
            <button className="btn" onClick={logout} disabled={signingOut}>
              <LogOutIcon size={15} /> {signingOut ? "Signing out…" : "Sign out"}
            </button>
          </div>
        </Modal>
      )}
      {changingPassword && <ChangePasswordModal onClose={() => setChangingPassword(false)} />}
    </div>
  );
}
