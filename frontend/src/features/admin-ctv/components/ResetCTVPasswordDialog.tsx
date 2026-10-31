"use client";

import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  Eye,
  EyeOff,
  KeyRound,
  LoaderCircle,
  X,
} from "lucide-react";

import {
  CTVManagementError,
  resetCTVPassword,
} from "../api/ctv-management";
import type { CTVListItem } from "../types/ctv-management";

interface Props {
  item: CTVListItem | null;
  open: boolean;
  onClose: () => void;
  onReset: () => void;
}

export default function ResetCTVPasswordDialog({
  item,
  open,
  onClose,
  onReset,
}: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (open && !dialog.open) {
      dialog.showModal();
    }

    if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  function resetState() {
    setPassword("");
    setConfirmPassword("");
    setShowPassword(false);
    setError("");
  }

  function closeDialog() {
    if (loading) return;
    resetState();
    onClose();
  }

  function handleCancel(
    event: React.SyntheticEvent<HTMLDialogElement>,
  ) {
    if (loading) {
      event.preventDefault();
      return;
    }

    resetState();
    onClose();
  }

  async function handleSubmit(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();

    if (!item?.pipeline || loading) return;

    setError("");

    if (password !== confirmPassword) {
      setError("Mật khẩu xác nhận không khớp.");
      return;
    }

    setLoading(true);

    try {
      await resetCTVPassword(
        item.pipeline.id,
        password,
        confirmPassword,
      );

      resetState();
      onReset();
    } catch (cause) {
      setError(
        cause instanceof CTVManagementError
          ? cause.message
          : "Không thể đặt lại mật khẩu.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <dialog
      ref={dialogRef}
      onCancel={handleCancel}
      aria-labelledby="reset-ctv-password-title"
      className="m-auto w-[calc(100%-2rem)] max-w-md rounded-2xl border border-slate-200 bg-white p-0 text-slate-900 shadow-2xl backdrop:bg-slate-950/60"
    >
      <form onSubmit={handleSubmit} className="space-y-5 p-5 sm:p-6">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2
              id="reset-ctv-password-title"
              className="text-lg font-bold text-slate-900"
            >
              Đặt lại mật khẩu CTV
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              Đặt mật khẩu mới cho tài khoản CTV
              &quot;{item?.ctv.username ?? ""}&quot;.
            </p>
          </div>

          <button
            type="button"
            disabled={loading}
            onClick={closeDialog}
            aria-label="Đóng"
            className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 disabled:opacity-50"
          >
            <X size={20} />
          </button>
        </div>

        <div>
          <label
            htmlFor="reset-ctv-password"
            className="mb-2 block text-sm font-medium text-slate-700"
          >
            Mật khẩu mới
          </label>
          <div className="relative">
            <input
              id="reset-ctv-password"
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="new-password"
              required
              disabled={loading}
              className="w-full rounded-lg border border-slate-200 px-3 py-3 pr-10 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              placeholder="Tối thiểu 8 ký tự"
            />
            <button
              type="button"
              onClick={() => setShowPassword((value) => !value)}
              className="absolute right-3 top-3 text-slate-400 hover:text-slate-600"
              aria-label={
                showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"
              }
            >
              {showPassword ? (
                <EyeOff size={18} />
              ) : (
                <Eye size={18} />
              )}
            </button>
          </div>
        </div>

        <div>
          <label
            htmlFor="reset-ctv-password-confirm"
            className="mb-2 block text-sm font-medium text-slate-700"
          >
            Xác nhận mật khẩu
          </label>
          <input
            id="reset-ctv-password-confirm"
            type={showPassword ? "text" : "password"}
            value={confirmPassword}
            onChange={(event) =>
              setConfirmPassword(event.target.value)
            }
            autoComplete="new-password"
            required
            disabled={loading}
            className="w-full rounded-lg border border-slate-200 px-3 py-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            placeholder="Nhập lại mật khẩu mới"
          />
        </div>

        {error && (
          <div
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
          >
            {error}
          </div>
        )}

        <div className="flex flex-wrap justify-end gap-3 border-t border-slate-100 pt-5">
          <button
            type="button"
            onClick={closeDialog}
            disabled={loading}
            className="rounded-lg border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 disabled:opacity-50"
          >
            Hủy
          </button>

          <button
            type="submit"
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-3 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? (
              <LoaderCircle size={17} className="animate-spin" />
            ) : (
              <KeyRound size={17} />
            )}
            {loading ? "Đang lưu..." : "Đặt lại mật khẩu"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
