"use client";
import {
  useRef,
  useState,
  type FormEvent,
  type SyntheticEvent,
} from "react";
import {
  AlertTriangle,
  LoaderCircle,
  Trash2,
  X,
} from "lucide-react";
import {
  deletePipeline,
  getPipelineDeletePreview,
  type PipelineDeletePreview,
} from "../api/delete-pipeline";
import type { PipelineListItem } from "../types/list";
interface Props {
  item: PipelineListItem;
  onDeleted: () => void;
}
export default function PipelineDeleteButton({
  item,
  onDeleted,
}: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [preview, setPreview] =
    useState<PipelineDeletePreview | null>(null);
  const [checking, setChecking] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmName, setConfirmName] = useState("");
  const [confirmUsername, setConfirmUsername] = useState("");
  const [error, setError] = useState("");
  const canConfirm =
    preview?.can_delete === true &&
    preview.blockers.length === 0 &&
    confirmName === preview.pipeline_name &&
    confirmUsername === preview.ctv_username &&
    !checking &&
    !deleting;
  async function openDialog() {
    if (checking || deleting) return;
    setPreview(null);
    setConfirmName("");
    setConfirmUsername("");
    setError("");
    setChecking(true);
    dialogRef.current?.showModal();
    try {
      const data = await getPipelineDeletePreview(item.id);
      if (!dialogRef.current?.open) return;
      setPreview(data);
    } catch (cause) {
      if (!dialogRef.current?.open) return;
      setError(
        cause instanceof Error
          ? cause.message
          : "Không thể kiểm tra Pipeline.",
      );
    } finally {
      setChecking(false);
    }
  }
  function closeDialog() {
    if (deleting) return;
    dialogRef.current?.close();
    setPreview(null);
    setConfirmName("");
    setConfirmUsername("");
    setError("");
  }
  function handleCancel(
    event: SyntheticEvent<HTMLDialogElement>,
  ) {
    if (!deleting) return;
    event.preventDefault();
  }
  async function handleDelete(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();
    if (!canConfirm || !preview) return;
    setDeleting(true);
    setError("");
    try {
      await deletePipeline(
        item.id,
        confirmName,
        confirmUsername,
      );
      closeAfterSuccess();
      onDeleted();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Không thể xóa Pipeline.",
      );
    } finally {
      setDeleting(false);
    }
  }
  function closeAfterSuccess() {
    dialogRef.current?.close();
    setPreview(null);
    setConfirmName("");
    setConfirmUsername("");
  }
  return (
    <>
      <button
        type="button"
        onClick={openDialog}
        className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm font-semibold text-red-700 hover:bg-red-100"
      >
        <Trash2 size={16} />
        Xóa
      </button>
      <dialog
        ref={dialogRef}
        onCancel={handleCancel}
        aria-labelledby={`delete-title-${item.id}`}
        className="m-auto w-[calc(100%-2rem)] max-w-lg rounded-2xl border border-red-200 bg-white p-0 text-slate-900 shadow-2xl backdrop:bg-slate-950/60"
      >
        <form
          onSubmit={handleDelete}
          className="space-y-5 p-5 sm:p-6"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3">
              <span className="rounded-xl bg-red-50 p-3 text-red-600">
                <AlertTriangle size={24} />
              </span>
              <div>
                <h2
                  id={`delete-title-${item.id}`}
                  className="text-lg font-bold"
                >
                  Xóa Pipeline
                </h2>
                <p className="text-sm text-slate-500">
                  Thao tác không thể hoàn tác.
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={closeDialog}
              disabled={deleting}
              aria-label="Đóng"
              className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 disabled:opacity-50"
            >
              <X size={20} />
            </button>
          </div>
          <div className="rounded-xl bg-red-50 p-4 text-sm text-red-800">
            Xóa Pipeline sẽ xóa cả tài khoản đăng nhập
            CTV tương ứng. Chỉ thực hiện đối với Pipeline
            không còn dữ liệu liên quan.
          </div>
          {checking && (
            <div
              role="status"
              className="flex items-center gap-2 text-sm text-slate-500"
            >
              <LoaderCircle
                size={17}
                className="animate-spin"
              />
              Đang kiểm tra dữ liệu liên quan...
            </div>
          )}
          {preview && (
            <>
              <div className="space-y-2 text-sm">
                <p>
                  Pipeline:
                  <strong className="ml-2">
                    {preview.pipeline_name}
                  </strong>
                </p>
                <p>
                  CTV:
                  <strong className="ml-2">
                    {preview.ctv_username}
                  </strong>
                </p>
              </div>
              {!preview.can_delete && (
                <div
                  role="alert"
                  className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800"
                >
                  <p className="font-semibold">
                    Không thể xóa Pipeline này.
                  </p>
                  <p className="mt-1">
                    Hệ thống phát hiện dữ liệu hoặc ràng buộc
                    cần được xử lý trước.
                  </p>
                  {preview.blockers.length > 0 && (
                    <ul className="mt-3 list-disc space-y-1 pl-5">
                      {preview.blockers.map((blocker) => (
                        <li key={blocker}>
                          {blocker}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
              {preview.can_delete && (
                <div className="space-y-4">
                  <div>
                    <label
                      htmlFor={`confirm-name-${item.id}`}
                      className="mb-2 block text-sm font-medium"
                    >
                      Nhập tên Pipeline để xác nhận
                    </label>
                    <p className="mb-2 break-all text-xs text-slate-500">
                      {preview.pipeline_name}
                    </p>
                    <input
                      id={`confirm-name-${item.id}`}
                      value={confirmName}
                      onChange={(event) =>
                        setConfirmName(event.target.value)
                      }
                      autoComplete="off"
                      disabled={deleting}
                      required
                      className="w-full rounded-lg border border-slate-200 px-3 py-3 text-sm outline-none focus:border-red-500"
                      placeholder="Nhập chính xác tên Pipeline"
                    />
                  </div>
                  <div>
                    <label
                      htmlFor={`confirm-ctv-${item.id}`}
                      className="mb-2 block text-sm font-medium"
                    >
                      Nhập username CTV để xác nhận
                    </label>
                    <p className="mb-2 break-all text-xs text-slate-500">
                      {preview.ctv_username}
                    </p>
                    <input
                      id={`confirm-ctv-${item.id}`}
                      value={confirmUsername}
                      onChange={(event) =>
                        setConfirmUsername(event.target.value)
                      }
                      autoComplete="off"
                      disabled={deleting}
                      required
                      className="w-full rounded-lg border border-slate-200 px-3 py-3 text-sm outline-none focus:border-red-500"
                      placeholder="Nhập chính xác username CTV"
                    />
                  </div>
                </div>
              )}
            </>
          )}
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
              disabled={deleting}
              className="rounded-lg border border-slate-200 px-4 py-3 text-sm font-semibold disabled:opacity-50"
            >
              Hủy
            </button>
            <button
              type="submit"
              disabled={!canConfirm}
              className="inline-flex items-center gap-2 rounded-lg bg-red-600 px-4 py-3 text-sm font-semibold text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {deleting ? (
                <LoaderCircle
                  size={17}
                  className="animate-spin"
                />
              ) : (
                <Trash2 size={17} />
              )}
              {deleting
                ? "Đang xóa..."
                : "Xóa Pipeline và CTV"}
            </button>
          </div>
        </form>
      </dialog>
    </>
  );
}
