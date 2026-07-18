import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { User } from "../api/types";
import { Modal, Spinner, Toggle, Toolbar } from "../components/common";
import { KeyIcon, PlusIcon, XIcon } from "../components/icons";
import {
  ChangePasswordModal,
  MIN_PASSWORD_LENGTH,
  ResetPasswordModal,
} from "../components/password";

function CreateUserModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
  const create = useMutation({
    mutationFn: () => api.post("/users", { username, password, is_admin: isAdmin }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      onClose();
    },
  });
  return (
    <Modal title="New User" onClose={onClose}>
      <div className="form-row">
        <label>Username</label>
        <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
      </div>
      <div className="form-row">
        <label>Password</label>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </div>
      <div className="form-row">
        <label>Admin</label>
        <Toggle on={isAdmin} onChange={setIsAdmin} />
      </div>
      {create.isError && <div className="error-banner">{(create.error as Error).message}</div>}
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 12 }}>
        <button className="btn" onClick={onClose}>
          Cancel
        </button>
        <button
          className="btn primary"
          disabled={!username || password.length < MIN_PASSWORD_LENGTH || create.isPending}
          onClick={() => create.mutate()}
        >
          Create
        </button>
      </div>
    </Modal>
  );
}

export default function Users({ me }: { me: User }) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["users"],
    queryFn: () => api.get<User[]>("/users"),
  });
  const [creating, setCreating] = useState(false);
  const [resetting, setResetting] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["users"] });
    setError(null);
  };
  const onError = (e: unknown) => setError((e as Error).message);

  const setAdmin = useMutation({
    mutationFn: ({ id, isAdmin }: { id: number; isAdmin: boolean }) =>
      api.put(`/users/${id}`, { is_admin: isAdmin }),
    onSuccess: invalidate,
    onError,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.del(`/users/${id}`),
    onSuccess: invalidate,
    onError,
  });

  if (isLoading || !data) {
    return (
      <>
        <Toolbar title="Users" />
        <Spinner />
      </>
    );
  }

  return (
    <>
      <Toolbar title="Users">
        <button className="btn primary" onClick={() => setCreating(true)}>
          <PlusIcon size={14} /> New User
        </button>
      </Toolbar>
      <div className="content">
        {error && (
          <div className="error-banner" style={{ marginBottom: 12 }}>
            {error}
          </div>
        )}
        <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Username</th>
              <th>Requests</th>
              <th>Admin</th>
              <th>Joined</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {data.map((u) => (
              <tr key={u.id}>
                <td style={{ fontWeight: 500 }}>
                  {u.username}
                  {u.id === me.id && <span style={{ color: "var(--text-faint)" }}> (you)</span>}
                </td>
                <td>{u.request_count}</td>
                <td>
                  <Toggle
                    on={u.is_admin}
                    onChange={(v) =>
                      u.id !== me.id && setAdmin.mutate({ id: u.id, isAdmin: v })
                    }
                  />
                </td>
                <td style={{ color: "var(--text-dim)" }}>
                  {new Date(u.created_at).toLocaleDateString()}
                </td>
                <td style={{ textAlign: "right" }}>
                  <button
                    className="btn icon-btn"
                    title={u.id === me.id ? "Change your password" : `Reset ${u.username}'s password`}
                    aria-label="Reset password"
                    onClick={() => setResetting(u)}
                  >
                    <KeyIcon size={14} />
                  </button>
                  {u.id !== me.id && (
                    <button
                      className="btn icon-btn"
                      title="Delete user"
                      aria-label="Delete user"
                      onClick={() => remove.mutate(u.id)}
                    >
                      <XIcon size={14} />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>
      {creating && <CreateUserModal onClose={() => setCreating(false)} />}
      {resetting && resetting.id === me.id && (
        <ChangePasswordModal onClose={() => setResetting(null)} />
      )}
      {resetting && resetting.id !== me.id && (
        <ResetPasswordModal
          userId={resetting.id}
          username={resetting.username}
          onClose={() => setResetting(null)}
        />
      )}
    </>
  );
}
