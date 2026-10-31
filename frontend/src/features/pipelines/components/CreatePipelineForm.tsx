"use client";

import { useState, type FormEvent } from "react";
import {
  CheckCircle2,
  Eye,
  EyeOff,
  Loader2,
  Plus,
} from "lucide-react";

import {
  createPipeline,
  PipelineApiError,
} from "../api/create-pipeline";
import type {
  CreatePipelineInput,
  PipelineResult,
} from "../types/pipeline";

const initialForm: CreatePipelineInput = {
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

export default function CreatePipelineForm() {
  const [form, setForm] = useState<CreatePipelineInput>({
    ...initialForm,
  });
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [created, setCreated] = useState<PipelineResult | null>(
    null,
  );

  function update<K extends keyof CreatePipelineInput>(
    key: K,
    value: CreatePipelineInput[K],
  ) {
    setForm((previous) => ({
      ...previous,
      [key]: value,
    }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (loading) return;

    setError("");
    setCreated(null);

    if (form.ctv_password !== form.ctv_password_confirm) {
      setError("Mật khẩu xác nhận không khớp.");
      return;
    }

    setLoading(true);

    try {
      const result = await createPipeline({
        ...form,
        name: form.name.trim(),
        ctv_username: form.ctv_username.trim(),
        ctv_email: form.ctv_email.trim(),
      });

      setCreated(result);
      setForm({ ...initialForm });
    } catch (unknownError) {
      if (unknownError instanceof PipelineApiError) {
        if (unknownError.status === 401 ||
            unknownError.status === 403) {
          setError(
            "Phiên đăng nhập không hợp lệ hoặc không đủ quyền. " +
            "Vui lòng đăng nhập lại.",
          );
          return;
        }

        setError(unknownError.message);
        return;
      }

      setError("Không thể kết nối máy chủ. Vui lòng thử lại.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      {created && (
        <div
          role="status"
          className="rounded-xl border border-green-200 bg-green-50 p-5"
        >
          <div className="flex items-center gap-2 font-semibold text-green-800">
            <CheckCircle2 size={20} />
            Tạo CTV và Pipeline thành công
          </div>

          <div className="mt-3 space-y-1 text-sm text-green-900">
            <p>CTV: {created.name}</p>
            <p>CTV: {created.ctv.username}</p>
            <p>Trạng thái: {created.status}</p>
          </div>
        </div>
      )}

      <form
        onSubmit={handleSubmit}
        className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
      >
        <div className="border-b border-slate-100 px-6 py-5">
          <h2 className="text-lg font-semibold text-slate-900">
            Thông tin CTV
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            Mỗi CTV được gắn với đúng một Pipeline.
          </p>
        </div>

        <div className="space-y-5 p-6">
          <div>
            <label htmlFor="pipeline-name" className={labelClass}>
              Tên CTV
            </label>
            <input
              id="pipeline-name"
              className={inputClass}
              placeholder="Ví dụ: CTV Marketing 01"
              value={form.name}
              maxLength={150}
              required
              disabled={loading}
              onChange={(event) =>
                update("name", event.target.value)
              }
            />
          </div>

          <div>
            <label htmlFor="pipeline-status" className={labelClass}>
              Trạng thái
            </label>
            <select
              id="pipeline-status"
              className={inputClass}
              value={form.status}
              disabled={loading}
              onChange={(event) =>
                update(
                  "status",
                  event.target.value as CreatePipelineInput["status"],
                )
              }
            >
              <option value="active">Hoạt động</option>
              <option value="disabled">Tạm khóa</option>
            </select>
          </div>
        </div>

        <div className="border-y border-slate-100 bg-slate-50 px-6 py-4">
          <h3 className="font-semibold text-slate-900">
            Tài khoản cộng tác viên
          </h3>
          <p className="mt-1 text-xs text-slate-500">
            Tài khoản được tạo tự động khi lưu CTV.
          </p>
        </div>

        <div className="space-y-5 p-6">
          <div className="grid gap-5 sm:grid-cols-2">
            <div>
              <label htmlFor="ctv-username" className={labelClass}>
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
              <label htmlFor="ctv-email" className={labelClass}>
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
              <label htmlFor="ctv-password" className={labelClass}>
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
                  aria-label={showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
                  onClick={() => setShowPassword((value) => !value)}
                >
                  {showPassword ? <EyeOff size={19} /> : <Eye size={19} />}
                </button>
              </div>
            </div>

            <div>
              <label htmlFor="ctv-confirm" className={labelClass}>
                Xác nhận mật khẩu
              </label>
              <input
                id="ctv-confirm"
                type={showPassword ? "text" : "password"}
                className={inputClass}
                value={form.ctv_password_confirm}
                autoComplete="new-password"
                required
                disabled={loading}
                onChange={(event) =>
                  update("ctv_password_confirm", event.target.value)
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

        <div className="flex justify-end border-t border-slate-100 bg-slate-50 p-5">
          <button
            type="submit"
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-3 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {loading ? (
              <Loader2 size={18} className="animate-spin" />
            ) : (
              <Plus size={18} />
            )}
            {loading ? "Đang tạo..." : "Tạo CTV + Pipeline"}
          </button>
        </div>
      </form>
    </div>
  );
}
