import { useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink } from "react-router-dom";
import { api, appVersion } from "../api/client";
import type { MediaRequest, User } from "../api/types";

export default function Sidebar({ me }: { me: User }) {
  const queryClient = useQueryClient();
  // pending-approval badge for admins
  const { data: pending } = useQuery({
    queryKey: ["requests", "all"],
    queryFn: () => api.get<MediaRequest[]>("/requests?scope=all"),
    enabled: me.is_admin,
    refetchInterval: 15000,
    select: (rows) => rows.filter((r) => r.status === "pending").length,
  });

  const items = [
    { to: "/", label: "Discover", icon: "⌕" },
    { to: "/requests", label: "Requests", icon: "≡" },
    ...(me.is_admin
      ? [
          { to: "/users", label: "Users", icon: "☺" },
          { to: "/settings", label: "Settings", icon: "⚙" },
        ]
      : []),
  ];

  const logout = async () => {
    await api.post("/auth/logout");
    queryClient.clear();
    window.location.href = "/";
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
            {item.label}
            {item.to === "/requests" && me.is_admin && !!pending && (
              <span className="nav-badge">{pending}</span>
            )}
          </NavLink>
        ))}
      </nav>
      <div className="sidebar-footer">
        <div style={{ marginBottom: 6 }}>
          {me.username}
          {me.is_admin && <span style={{ color: "var(--text-faint)" }}> · admin</span>}
          {" — "}
          <button onClick={logout} style={{ color: "var(--accent-hover)" }}>
            sign out
          </button>
        </div>
        v{appVersion()}
      </div>
    </div>
  );
}
