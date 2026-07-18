import { useQuery } from "@tanstack/react-query";
import { Navigate, Route, Routes } from "react-router-dom";
import { api, ApiError } from "./api/client";
import type { User } from "./api/types";
import { Spinner } from "./components/common";
import Sidebar from "./components/Sidebar";
import Discover from "./pages/Discover";
import Login from "./pages/Login";
import Requests from "./pages/Requests";
import Settings from "./pages/Settings";
import Title from "./pages/Title";
import Users from "./pages/Users";

export default function App() {
  const { data: me, isLoading, error } = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<User>("/auth/me"),
    retry: false,
  });

  if (isLoading) {
    return (
      <div className="login-wrap">
        <Spinner />
      </div>
    );
  }

  if (!me) {
    if (error && !(error instanceof ApiError && error.status === 401)) {
      return (
        <div className="login-wrap">
          <div className="login-card">
            <h3>NextPanel backend unreachable</h3>
            <p style={{ color: "var(--text-dim)" }}>{(error as Error).message}</p>
          </div>
        </div>
      );
    }
    return <Login />;
  }

  return (
    <div className="app">
      <Sidebar me={me} />
      <div className="main">
        <Routes>
          <Route path="/" element={<Discover />} />
          <Route path="/title/:mediaType/:provider/:providerId" element={<Title />} />
          <Route path="/requests" element={<Requests me={me} />} />
          {me.is_admin && <Route path="/users" element={<Users me={me} />} />}
          {me.is_admin && <Route path="/settings" element={<Settings />} />}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </div>
  );
}
