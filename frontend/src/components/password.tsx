import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { Modal } from "./common";

export const MIN_PASSWORD_LENGTH = 8;

/** New password + confirmation, with the mismatch/too-short rules in one place. */
function NewPasswordFields({
  password,
  confirm,
  onPassword,
  onConfirm,
  autoFocus = false,
}: {
  password: string;
  confirm: string;
  onPassword: (v: string) => void;
  onConfirm: (v: string) => void;
  autoFocus?: boolean;
}) {
  return (
    <>
      <div className="form-row">
        <label>New password</label>
        <input
          type="password"
          value={password}
          autoFocus={autoFocus}
          autoComplete="new-password"
          onChange={(e) => onPassword(e.target.value)}
        />
      </div>
      <div className="form-row">
        <label>Confirm</label>
        <input
          type="password"
          value={confirm}
          autoComplete="new-password"
          onChange={(e) => onConfirm(e.target.value)}
        />
      </div>
    </>
  );
}

function validate(password: string, confirm: string): string | null {
  if (password.length < MIN_PASSWORD_LENGTH) {
    return `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
  }
  if (password !== confirm) return "The two passwords do not match.";
  return null;
}

/** Signed-in user changing their own password (proves the current one). */
export function ChangePasswordModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [done, setDone] = useState(false);

  const change = useMutation({
    mutationFn: () =>
      api.post("/auth/password", { current_password: current, new_password: password }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["me"] });
      setDone(true);
    },
  });

  const problem = validate(password, confirm);

  if (done) {
    return (
      <Modal title="Password Changed" onClose={onClose}>
        <p style={{ color: "var(--text-dim)" }}>
          Your password has been changed. Any other device that was signed in has been
          signed out; this one stays signed in.
        </p>
        <div className="modal-actions">
          <button className="btn primary" onClick={onClose}>Done</button>
        </div>
      </Modal>
    );
  }

  return (
    <Modal title="Change Password" onClose={onClose}>
      <div className="form-row">
        <label>Current password</label>
        <input
          type="password"
          value={current}
          autoFocus
          autoComplete="current-password"
          onChange={(e) => setCurrent(e.target.value)}
        />
      </div>
      <NewPasswordFields
        password={password}
        confirm={confirm}
        onPassword={setPassword}
        onConfirm={setConfirm}
      />
      <p className="section-hint">
        Changing your password signs out every other device.
      </p>
      {change.isError && <div className="error-banner">{(change.error as Error).message}</div>}
      {!change.isError && problem && confirm && <div className="form-hint">{problem}</div>}
      <div className="modal-actions">
        <button className="btn" onClick={onClose}>Cancel</button>
        <button
          className="btn primary"
          disabled={!current || problem !== null || change.isPending}
          onClick={() => change.mutate()}
        >
          {change.isPending ? "Changing…" : "Change Password"}
        </button>
      </div>
    </Modal>
  );
}

/** Admin resetting someone else's password (no current password needed). */
export function ResetPasswordModal({
  userId,
  username,
  onClose,
}: {
  userId: number;
  username: string;
  onClose: () => void;
}) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const reset = useMutation({
    mutationFn: () => api.put(`/users/${userId}`, { password }),
    onSuccess: onClose,
  });

  const problem = validate(password, confirm);

  return (
    <Modal title={`Reset Password — ${username}`} onClose={onClose}>
      <NewPasswordFields
        password={password}
        confirm={confirm}
        onPassword={setPassword}
        onConfirm={setConfirm}
        autoFocus
      />
      <p className="section-hint">
        {username} will be signed out everywhere and will need this new password to sign
        back in. Tell them out of band — it is not sent anywhere.
      </p>
      {reset.isError && <div className="error-banner">{(reset.error as Error).message}</div>}
      {!reset.isError && problem && confirm && <div className="form-hint">{problem}</div>}
      <div className="modal-actions">
        <button className="btn" onClick={onClose}>Cancel</button>
        <button
          className="btn primary"
          disabled={problem !== null || reset.isPending}
          onClick={() => reset.mutate()}
        >
          {reset.isPending ? "Resetting…" : "Reset Password"}
        </button>
      </div>
    </Modal>
  );
}
