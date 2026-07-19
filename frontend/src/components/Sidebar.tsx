import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink } from "react-router-dom";
import { api, appVersion } from "../api/client";
import type { AuthStatus, MediaRequest, User } from "../api/types";
import { InboxIcon, KeyIcon, LogOutIcon, SearchIcon, SettingsIcon, UsersIcon } from "./icons";
import { ChangePasswordModal } from "./password";

export default function Sidebar({ me }: { me: User }) {
  const queryClient = useQueryClient();
  const [changingPassword, setChangingPassword] = useState(false);
  const { data: authStatus } = useQuery({
    queryKey: ["authStatus"],
    queryFn: () => api.get<AuthStatus>("/auth/status"),
  });
  // pending-approval badge for admins
  const { data: pending } = useQuery({
    queryKey: ["requests", "all"],
    queryFn: () => api.get<MediaRequest[]>("/requests?scope=all"),
    enabled: me.is_admin,
    refetchInterval: 15000,
    select: (rows) => rows.filter((r) => r.status === "pending").length,
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
    await api.post("/auth/logout");
    queryClient.clear();
    window.location.href = authStatus?.sso_enabled ? "/cdn-cgi/access/logout" : "/";
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
      </nav>
      <div className="sidebar-footer">
        <div style={{ marginBottom: 6, display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
            {me.username}
            {me.is_admin && <span style={{ color: "var(--text-faint)" }}> · admin</span>}
          </span>
          {authStatus?.local_login_enabled && (
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
            title="Sign out"
            aria-label="Sign out"
            style={{ color: "var(--accent-hover)", display: "inline-flex" }}
          >
            <LogOutIcon size={15} />
          </button>
        </div>
        v{appVersion()}
      </div>
      {changingPassword && <ChangePasswordModal onClose={() => setChangingPassword(false)} />}
    </div>
  );
}
