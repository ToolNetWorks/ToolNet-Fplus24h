"use client";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type SyntheticEvent,
} from "react";
import {
  LoaderCircle,
  Pencil,
  Save,
  X,
} from "lucide-react";
import { updatePipeline } from "../api/update-pipeline";
import type { PipelineListItem } from "../types/list";
interface Props {
  item: PipelineListItem;
  onChanged: () => void;
  triggerClassName?: string;
}
const inputClass =
  "w-full rounded-lg border border-slate-200 " +
  "bg-white px-3 py-3 text-sm text-slate-900 " +
  "outline-none focus:border-blue-500 " +
  "focus:ring-2 focus:ring-blue-100";
const labelClass =
  "mb-2 block text-sm font-medium text-slate-700";
export default function PipelineEditButton({
  item,
  onChanged,
  triggerClassName,
}: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [name, setName] = useState(item.name);
  const [username, setUsername] = useState(
    item.ctv.username,
  );
  const [email, setEmail] = useState(item.ctv.email);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
      return;
    }
    if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);
  function openDialog() {
    if (loading) return;
    setName(item.name);
    setUsername(item.ctv.username);
    setEmail(item.ctv.email);
    setError("");
    setSuccess("");
    setOpen(true);
  }
  function closeDialog() {
    if (loading) return;
    setOpen(false);
    setError("");
  }
  function handleCancel(
    event: SyntheticEvent<HTMLDialogElement>,
  ) {
    if (loading) {
      event.preventDefault();
      return;
    }
    setOpen(false);
  }
  async function handleSubmit(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();
    if (loading) return;
    setError("");
    setSuccess("");
    const changes = {
      name: name.trim(),
      ctv_username: username.trim(),
      ctv_email: email.trim(),
    };
    if (
      changes.name === item.name &&
      changes.ctv_username === item.ctv.username &&
      changes.ctv_email === item.ctv.email
    ) {
      setOpen(false);
      return;
    }
    setLoading(true);
    try {
      await updatePipeline(item.id, changes);
      setSuccess("Đã cập nhật thành công.");
      setOpen(false);
      onChanged();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Cập nhật thất bại.",
      );
    } finally {
      setLoading(false);
    }
  }
  return (
    <>
      <button
        type="button"
        onClick={openDialog}
        className={
          triggerClassName ||
          "inline-flex min-h-10 items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-4 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-100"
        }
      >
        <Pencil size={15} />
        <span>Chỉnh sửa</span>
      </button>
      {success && !triggerClassName && (
        <p
          role="status"
          className="text-xs text-green-700"
        >
          {success}
        </p>
      )}
      <dialog
        ref={dialogRef}
        onCancel={handleCancel}
        onClose={() => setOpen(false)}
        aria-labelledby={`edit-title-${item.id}`}
        className="m-auto w-[calc(100%-2rem)] max-w-lg rounded-2xl border border-slate-200 bg-white p-0 text-slate-900 shadow-2xl backdrop:bg-slate-950/60"
      >
        <form
          onSubmit={handleSubmit}
          className="space-y-5 p-5 sm:p-6"
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2
                id={`edit-title-${item.id}`}
                className="text-lg font-bold text-slate-900"
              >
                Chỉnh sửa Pipeline
              </h2>
              <p className="mt-1 text-sm text-slate-500">
                Cập nhật thông tin Pipeline và CTV.
              </p>
            </div>
            <button
              type="button"
              disabled={loading}
              onClick={closeDialog}
              aria-label="Đóng hộp thoại"
              className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 disabled:opacity-50"
            >
              <X size={20} />
            </button>
          </div>
          <div>
            <label
              htmlFor={`edit-name-${item.id}`}
              className={labelClass}
            >
              Tên Pipeline
            </label>
            <input
              id={`edit-name-${item.id}`}
              className={inputClass}
              value={name}
              onChange={(event) =>
                setName(event.target.value)
              }
              maxLength={150}
              autoFocus
              required
              disabled={loading}
            />
          </div>
          <div className="border-t border-slate-100 pt-4">
            <h3 className="font-semibold text-slate-800">
              Thông tin CTV
            </h3>
            <p className="mt-1 text-xs text-slate-500">
              CTV vẫn thuộc Pipeline này sau khi chỉnh sửa.
            </p>
          </div>
          <div>
            <label
              htmlFor={`edit-username-${item.id}`}
              className={labelClass}
            >
              Username CTV
            </label>
            <input
              id={`edit-username-${item.id}`}
              className={inputClass}
              value={username}
              onChange={(event) =>
                setUsername(event.target.value)
              }
              maxLength={150}
              autoComplete="off"
              required
              disabled={loading}
            />
          </div>
          <div>
            <label
              htmlFor={`edit-email-${item.id}`}
              className={labelClass}
            >
              Email CTV
            </label>
            <input
              id={`edit-email-${item.id}`}
              type="email"
              className={inputClass}
              value={email}
              onChange={(event) =>
                setEmail(event.target.value)
              }
              maxLength={254}
              required
              disabled={loading}
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
                <LoaderCircle
                  size={17}
                  className="animate-spin"
                />
              ) : (
                <Save size={17} />
              )}
              {loading ? "Đang lưu..." : "Lưu thay đổi"}
            </button>
          </div>
        </form>
      </dialog>
    </>
  );
}
