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
  LoaderCircle,
  UserPlus,
  X,
} from "lucide-react";

import {
  createCTV,
  CTVManagementError,
} from "../api/ctv-management";
import type { CreateCTVInput } from "../types/ctv-management";

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

const initialForm: CreateCTVInput = {
  name: "",
  status: "active",
  ctv_username: "",
  ctv_email: "",
  ctv_password: "",
  ctv_password_confirm: "",
};

const inputClass =
  "w-full rounded-lg border border-slate-200 bg-white px-3 py-3 " +
  "text-sm text-slate-900 outline-none transition " +
  "focus:border-blue-500 focus:ring-2 focus:ring-blue-100";

const labelClass =
  "mb-2 block text-sm font-medium text-slate-700";

export default function CreateCTVDialog({
  open,
  onClose,
  onCreated,
}: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [form, setForm] = useState<CreateCTVInput>({
    ...initialForm,
  });
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
    setForm({ ...initialForm });
    setShowPassword(false);
    setError("");
  }

  function update<K extends keyof CreateCTVInput>(
    key: K,
    value: CreateCTVInput[K],
  ) {
    setForm((previous) => ({
      ...previous,
      [key]: value,
    }));
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

    if (loading) return;

    setError("");

    if (form.ctv_password !== form.ctv_password_confirm) {
      setError("Mật khẩu xác nhận không khớp.");
      return;
    }

    setLoading(true);

    try {
      await createCTV({
        ...form,
        name: form.name.trim(),
        ctv_username: form.ctv_username.trim(),
        ctv_email: form.ctv_email.trim(),
      });

      resetState();
      onCreated();
    } catch (cause) {
      setError(
        cause instanceof CTVManagementError
          ? cause.message
          : "Không thể tạo CTV. Vui lòng thử lại.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <dialog
      ref={dialogRef}
      onCancel={handleCancel}
      aria-labelledby="create-ctv-title"
      className="m-auto max-h-[92vh] w-[calc(100%-2rem)] max-w-2xl overflow-y-auto rounded-2xl border border-slate-200 bg-white p-0 text-slate-900 shadow-2xl backdrop:bg-slate-950/60"
    >
      <form onSubmit={handleSubmit}>
        <div className="flex items-start justify-between gap-3 border-b border-slate-100 p-5 sm:p-6">
          <div>
            <h2
              id="create-ctv-title"
              className="text-lg font-bold text-slate-900"
            >
              Tạo CTV và Pipeline
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              Mỗi CTV được tạo cùng đúng một Pipeline.
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

        <div className="space-y-5 p-5 sm:p-6">
          <div>
            <label htmlFor="ctv-pipeline-name" className={labelClass}>
              Tên Pipeline
            </label>
            <input
              id="ctv-pipeline-name"
              className={inputClass}
              value={form.name}
              maxLength={150}
              placeholder="Ví dụ: Pipeline Marketing 01"
              required
              disabled={loading}
              onChange={(event) =>
                update("name", event.target.value)
              }
            />
          </div>

          <div>
            <label
              htmlFor="ctv-pipeline-status"
              className={labelClass}
            >
              Trạng thái ban đầu
            </label>
            <select
              id="ctv-pipeline-status"
              className={inputClass}
              value={form.status}
              disabled={loading}
              onChange={(event) =>
                update(
                  "status",
                  event.target.value as CreateCTVInput["status"],
                )
              }
            >
              <option value="active">Hoạt động</option>
              <option value="disabled">Khóa</option>
            </select>
          </div>

          <div className="grid gap-5 sm:grid-cols-2">
            <div>
              <label
                htmlFor="ctv-username"
                className={labelClass}
              >
                Username CTV
              </label>
              <input
                id="ctv-username"
                className={inputClass}
                value={form.ctv_username}
                maxLength={150}
                autoComplete="off"
                placeholder="ctv01"
                required
                disabled={loading}
                onChange={(event) =>
                  update("ctv_username", event.target.value)
                }
              />
            </div>

            <div>
              <label
                htmlFor="ctv-email"
                className={labelClass}
              >
                Email CTV
              </label>
              <input
                id="ctv-email"
                type="email"
                className={inputClass}
                value={form.ctv_email}
                maxLength={254}
                placeholder="ctv@example.com"
                required
                disabled={loading}
                onChange={(event) =>
                  update("ctv_email", event.target.value)
                }
              />
            </div>
          </div>

          <div className="grid gap-5 sm:grid-cols-2">
            <div>
              <label
                htmlFor="ctv-password"
                className={labelClass}
              >
                Mật khẩu CTV
              </label>
              <div className="relative">
                <input
                  id="ctv-password"
                  type={showPassword ? "text" : "password"}
                  className={`${inputClass} pr-11`}
                  value={form.ctv_password}
                  autoComplete="new-password"
                  required
                  disabled={loading}
                  onChange={(event) =>
                    update("ctv_password", event.target.value)
                  }
                />
                <button
                  type="button"
                  className="absolute right-3 top-3 text-slate-500"
                  aria-label={
                    showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"
                  }
                  onClick={() =>
                    setShowPassword((value) => !value)
                  }
                >
                  {showPassword ? (
                    <EyeOff size={19} />
                  ) : (
                    <Eye size={19} />
                  )}
                </button>
              </div>
            </div>

            <div>
              <label
                htmlFor="ctv-password-confirm"
                className={labelClass}
              >
                Xác nhận mật khẩu
              </label>
              <input
                id="ctv-password-confirm"
                type={showPassword ? "text" : "password"}
                className={inputClass}
                value={form.ctv_password_confirm}
                autoComplete="new-password"
                required
                disabled={loading}
                onChange={(event) =>
                  update(
                    "ctv_password_confirm",
                    event.target.value,
                  )
                }
              />
            </div>
          </div>

          {error && (
            <div
              role="alert"
              className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
            >
              {error}
            </div>
          )}
        </div>

        <div className="flex flex-wrap justify-end gap-3 border-t border-slate-100 bg-slate-50 p-5">
          <button
            type="button"
            onClick={closeDialog}
            disabled={loading}
            className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm font-semibold text-slate-700 disabled:opacity-50"
          >
            Hủy
          </button>

          <button
            type="submit"
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-3 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {loading ? (
              <LoaderCircle size={18} className="animate-spin" />
            ) : (
              <UserPlus size={18} />
            )}
            {loading ? "Đang tạo..." : "Tạo CTV + Pipeline"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
