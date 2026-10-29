"use client";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type MutableRefObject,
} from "react";
import {
  Eye,
  EyeOff,
  KeyRound,
  LoaderCircle,
  X,
} from "lucide-react";
import { changeCTVPassword } from "../api/change-ctv-password";
import type { PipelineListItem } from "../types/list";

export interface CTVPasswordActionHandle {
  open: () => void;
}

interface Props {
  item: PipelineListItem;
  actionRef?: MutableRefObject<CTVPasswordActionHandle | null>;
  hideTrigger?: boolean;
}

export default function CTVPasswordButton({
  item,
  actionRef,
  hideTrigger = false,
}: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

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

  useEffect(() => {
    if (actionRef) {
      actionRef.current = {
        open: () => {
          setError("");
          setSuccess("");
          setOpen(true);
        },
      };
    }
  });

  function closeDialog() {
    if (loading) return;
    setOpen(false);
    setPassword("");
    setConfirmPassword("");
    setShowPassword(false);
    setError("");
  }

  function handleCancel(event: React.SyntheticEvent<HTMLDialogElement>) {
    if (loading) {
      event.preventDefault();
      return;
    }
    setOpen(false);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (loading) return;
    setError("");
    setSuccess("");
    if (password !== confirmPassword) {
      setError("Mật khẩu xác nhận không khớp.");
      return;
    }
    setLoading(true);
    try {
      await changeCTVPassword(
        item.id,
        password,
        confirmPassword,
      );
      setSuccess(
        `Đã đổi mật khẩu CTV "${item.ctv.username}" thành công.`,
      );
      setOpen(false);
      setPassword("");
      setConfirmPassword("");
      setShowPassword(false);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Không thể đổi mật khẩu.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      {!hideTrigger && (
        <div className="space-y-2">
          <button
            type="button"
            onClick={() => {
              setError("");
              setSuccess("");
              setOpen(true);
            }}
            className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
          >
            <KeyRound size={16} />
            Đổi mật khẩu
          </button>
          {success && (
            <p role="status" className="max-w-64 text-xs text-green-700">
              {success}
            </p>
          )}
        </div>
      )}
      <dialog
        ref={dialogRef}
        onCancel={handleCancel}
        onClose={() => setOpen(false)}
        aria-labelledby={`password-title-${item.id}`}
        className="m-auto w-[calc(100%-2rem)] max-w-md rounded-2xl border border-slate-200 bg-white p-0 text-slate-900 shadow-2xl backdrop:bg-slate-950/60"
      >
        <form onSubmit={handleSubmit} className="space-y-5 p-5 sm:p-6">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2
                id={`password-title-${item.id}`}
                className="text-lg font-bold text-slate-900"
              >
                Đổi mật khẩu CTV
              </h2>
              <p className="mt-1 text-sm text-slate-500">
                Đặt mật khẩu mới cho tài khoản CTV &quot;{item.ctv.username}&quot;.
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
              htmlFor={`new-password-${item.id}`}
              className="mb-2 block text-sm font-medium text-slate-700"
            >
              Mật khẩu mới
            </label>
            <div className="relative">
              <input
                id={`new-password-${item.id}`}
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
                aria-label={showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
              >
                {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
          </div>
          <div>
            <label
              htmlFor={`confirm-password-${item.id}`}
              className="mb-2 block text-sm font-medium text-slate-700"
            >
              Xác nhận mật khẩu
            </label>
            <input
              id={`confirm-password-${item.id}`}
              type={showPassword ? "text" : "password"}
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
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
              {loading && <LoaderCircle size={17} className="animate-spin" />}
              {loading ? "Đang lưu..." : "Đổi mật khẩu"}
            </button>
          </div>
        </form>
      </dialog>
    </>
  );
}
