"use client";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import Link from "next/link";
import Image from "next/image";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  FolderPlus,
  ImageIcon,
  LoaderCircle,
  Pencil,
  RefreshCw,
  Upload,
  X,
} from "lucide-react";
import {
  createAlbum,
  listAlbums,
  listAlbumImages,
  updateAlbum,
  uploadAlbumImages,
  type Album,
  type AlbumImage,
  type PageResult,
} from "../api/albums";
const inputStyle =
  "w-full rounded-lg border border-slate-200 bg-white " +
  "px-3 py-3 text-sm outline-none focus:border-blue-500 " +
  "focus:ring-2 focus:ring-blue-100";
function displayError(cause: unknown): string {
  return cause instanceof Error
    ? cause.message
    : "Có lỗi xảy ra. Vui lòng thử lại.";
}
function formatSize(bytes: number): string {
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}
export default function AlbumLibrary({
  pipelineId,
  backHref = "/pipelines/",
}: {
  pipelineId: string;
  backHref?: string | null;
}) {
  const [albumResult, setAlbumResult] =
    useState<PageResult<Album> | null>(null);
  const [imageResult, setImageResult] =
    useState<PageResult<AlbumImage> | null>(null);
  const [albumPage, setAlbumPage] = useState(1);
  const [imagePage, setImagePage] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [albumVersion, setAlbumVersion] = useState(0);
  const [imageVersion, setImageVersion] = useState(0);
  const [loadingAlbums, setLoadingAlbums] = useState(true);
  const [loadingImages, setLoadingImages] = useState(false);
  const [error, setError] = useState("");
  const [imageError, setImageError] = useState("");
  const [mutationError, setMutationError] = useState("");
  const [success, setSuccess] = useState("");
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [editing, setEditing] = useState<Album | null>(null);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const activeAlbum = albumResult?.data.find(
    (album) => album.id === selectedId,
  );
  function refreshAlbums() {
    setAlbumVersion((value) => value + 1);
  }
  function refreshImages() {
    setImageVersion((value) => value + 1);
  }
  useEffect(() => {
    const controller = new AbortController();
    setLoadingAlbums(true);
    setError("");
    listAlbums(pipelineId, albumPage, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setAlbumResult(result);
        setSelectedId((previous) => {
          if (result.data.some((album) => album.id === previous)) {
            return previous;
          }
          return result.data[0]?.id ?? null;
        });
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(displayError(cause));
        setAlbumResult(null);
        setSelectedId(null);
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoadingAlbums(false);
        }
      });
    return () => controller.abort();
  }, [pipelineId, albumPage, albumVersion]);
  useEffect(() => {
    const controller = new AbortController();
    if (!selectedId) {
      setImageResult(null);
      setImageError("");
      setLoadingImages(false);
      return () => controller.abort();
    }
    setLoadingImages(true);
    setImageError("");
    listAlbumImages(
      pipelineId,
      selectedId,
      imagePage,
      controller.signal,
    )
      .then((result) => {
        if (!controller.signal.aborted) {
          setImageResult(result);
        }
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setImageResult(null);
        setImageError(displayError(cause));
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoadingImages(false);
        }
      });
    return () => controller.abort();
  }, [pipelineId, selectedId, imagePage, imageVersion]);
  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setMutationError("");
    setSuccess("");
    try {
      const album = await createAlbum(pipelineId, {
        name: newName.trim(),
        description: newDescription.trim(),
        is_enabled: true,
      });
      setCreating(false);
      setNewName("");
      setNewDescription("");
      setSuccess(`Đã tạo Album "${album.name}".`);
      setAlbumPage(1);
      refreshAlbums();
    } catch (cause) {
      setMutationError(displayError(cause));
    } finally {
      setBusy(false);
    }
  }
  function startEdit(album: Album) {
    setEditing(album);
    setEditName(album.name);
    setEditDescription(album.description);
    setMutationError("");
    setSuccess("");
  }
  async function handleEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editing || busy) return;
    setBusy(true);
    setMutationError("");
    try {
      await updateAlbum(pipelineId, editing.id, {
        name: editName.trim(),
        description: editDescription.trim(),
      });
      setEditing(null);
      setSuccess("Đã cập nhật Album.");
      refreshAlbums();
    } catch (cause) {
      setMutationError(displayError(cause));
    } finally {
      setBusy(false);
    }
  }
  async function handleToggle(album: Album) {
    if (busy) return;
    setBusy(true);
    setMutationError("");
    setSuccess("");
    try {
      await updateAlbum(pipelineId, album.id, {
        is_enabled: !album.is_enabled,
      });
      setSuccess(
        album.is_enabled
          ? "Đã tắt Album."
          : "Đã bật Album.",
      );
      refreshAlbums();
    } catch (cause) {
      setMutationError(displayError(cause));
    } finally {
      setBusy(false);
    }
  }
  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedId || uploading || busy || !activeAlbum?.is_enabled) {
      return;
    }
    setUploading(true);
    setMutationError("");
    setSuccess("");
    try {
      const uploaded = await uploadAlbumImages(
        pipelineId,
        selectedId,
        files,
      );
      setSuccess(`Đã upload thành công ${uploaded.length} ảnh.`);
      setFiles([]);
      if (inputRef.current) {
        inputRef.current.value = "";
      }
      const total = (imageResult?.pagination.total ?? 0)
        + uploaded.length;
      setImagePage(Math.max(1, Math.ceil(total / 20)));
      refreshAlbums();
      refreshImages();
    } catch (cause) {
      setMutationError(displayError(cause));
    } finally {
      setUploading(false);
    }
  }
  const albumPagination = albumResult?.pagination;
  const imagePagination = imageResult?.pagination;
  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-2">
          {backHref && (
            <Link
              href={backHref}
              className="inline-flex items-center gap-2 text-sm text-slate-500"
            >
              <ArrowLeft size={17} />
              Quay lại Pipeline
            </Link>
          )}
          <h2 className="text-2xl font-bold text-slate-900">
            Album Library
          </h2>
          <p className="text-sm text-slate-500">
            Thư viện hình ảnh riêng của Pipeline.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            setCreating((value) => !value);
            setMutationError("");
          }}
          className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-3 text-sm font-semibold text-white"
        >
          <FolderPlus size={18} />
          Tạo Album
        </button>
      </div>
      {error && (
        <p role="alert" className="rounded-lg bg-red-50 p-4 text-sm text-red-700">
          {error}
        </p>
      )}
      {success && (
        <p role="status" className="rounded-lg bg-green-50 p-4 text-sm text-green-800">
          {success}
        </p>
      )}
      {mutationError && (
        <p role="alert" className="rounded-lg bg-red-50 p-4 text-sm text-red-700">
          {mutationError}
        </p>
      )}
      {creating && (
        <form
          onSubmit={handleCreate}
          className="space-y-4 rounded-xl border border-blue-200 bg-white p-5"
        >
          <h3 className="font-semibold">Tạo Album mới</h3>
          <input
            required
            maxLength={200}
            placeholder="Tên Album"
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
            className={inputStyle}
          />
          <textarea
            rows={3}
            maxLength={5000}
            placeholder="Mô tả Album (không bắt buộc)"
            value={newDescription}
            onChange={(event) => setNewDescription(event.target.value)}
            className={inputStyle}
          />
          <button
            type="submit"
            disabled={busy || !newName.trim()}
            className="rounded-lg bg-blue-600 px-5 py-3 text-sm font-semibold text-white disabled:opacity-50"
          >
            {busy ? "Đang lưu..." : "Lưu Album"}
          </button>
        </form>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-lg font-semibold text-slate-900">
          Danh sách Album
        </h3>
        <button
          type="button"
          onClick={refreshAlbums}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
        >
          <RefreshCw size={16} />
          Làm mới
        </button>
      </div>
      {loadingAlbums ? (
        <p role="status" className="text-sm text-slate-500">
          Đang tải Album...
        </p>
      ) : !error && albumResult?.data.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-200 bg-white p-10 text-center">
          <ImageIcon className="mx-auto text-slate-400" size={34} />
          <p className="mt-3 text-sm text-slate-500">
            Pipeline chưa có Album. Hãy tạo Album đầu tiên.
          </p>
        </div>
      ) : !error ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {albumResult?.data.map((album) => (
            <article
              key={album.id}
              className={
                "rounded-xl border bg-white p-4 " +
                (selectedId === album.id
                  ? "border-blue-400 ring-2 ring-blue-100"
                  : "border-slate-200")
              }
            >
              <button
                type="button"
                onClick={() => {
                  setSelectedId(album.id);
                  setImagePage(1);
                  setFiles([]);
                }}
                className="w-full text-left"
              >
                <div className="mb-3 flex h-24 items-center justify-center rounded-lg bg-slate-100">
                  <ImageIcon size={30} className="text-slate-400" />
                </div>
                <h4 className="break-words font-semibold text-slate-900">
                  {album.name}
                </h4>
                <p className="mt-1 text-xs text-slate-500">
                  {album.image_count} ảnh
                </p>
                <p className={
                  "mt-2 text-xs font-medium " +
                  (album.is_enabled
                    ? "text-green-700"
                    : "text-red-600")
                }>
                  {album.is_enabled ? "Đang bật" : "Đã tắt"}
                </p>
              </button>
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={busy || uploading}
                  onClick={() => startEdit(album)}
                  className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-2 text-xs disabled:opacity-50"
                >
                  <Pencil size={14} />
                  Sửa
                </button>
                <button
                  type="button"
                  disabled={busy || uploading}
                  onClick={() => handleToggle(album)}
                  className="rounded-lg border border-slate-200 px-3 py-2 text-xs disabled:opacity-50"
                >
                  {album.is_enabled ? "Tắt" : "Bật"}
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : null}
      {albumPagination && albumPagination.total_pages > 1 && (
        <div className="flex items-center justify-center gap-4">
          <button
            type="button"
            disabled={!albumPagination.has_previous || loadingAlbums}
            onClick={() => setAlbumPage((value) => Math.max(1, value - 1))}
            className="rounded-lg border border-slate-200 p-2 disabled:opacity-30"
          >
            <ChevronLeft size={18} />
          </button>
          <span className="text-sm">
            {albumPagination.page} / {albumPagination.total_pages}
          </span>
          <button
            type="button"
            disabled={!albumPagination.has_next || loadingAlbums}
            onClick={() => setAlbumPage((value) => value + 1)}
            className="rounded-lg border border-slate-200 p-2 disabled:opacity-30"
          >
            <ChevronRight size={18} />
          </button>
        </div>
      )}
      {activeAlbum && (
        <div className="space-y-5 rounded-xl border border-slate-200 bg-white p-4 sm:p-6">
          <div>
            <h3 className="text-xl font-bold text-slate-900">
              {activeAlbum.name}
            </h3>
            <p className="mt-1 whitespace-pre-wrap text-sm text-slate-500">
              {activeAlbum.description || "Chưa có mô tả."}
            </p>
          </div>
          <form onSubmit={handleUpload} className="space-y-3">
            <label className="block text-sm font-medium">
              Upload ảnh vào Album
            </label>
            <input
              ref={inputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              multiple
              disabled={!activeAlbum.is_enabled || uploading || busy}
              onChange={(event) =>
                setFiles(Array.from(event.target.files ?? []))
              }
              className="block w-full rounded-lg border border-dashed border-slate-300 p-4 text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-slate-100 file:px-3 file:py-2"
            />
            <p className="text-xs text-slate-500">
              JPEG, PNG, WebP · tối đa 5 ảnh/lần · mỗi ảnh tối đa 10 MB.
            </p>
            {files.length > 0 && (
              <p className="break-words text-xs text-slate-600">
                Đã chọn {files.length} ảnh —{" "}
                {files.map((file) => file.name).join(", ")}
              </p>
            )}
            {!activeAlbum.is_enabled && (
              <p className="text-sm text-amber-700">
                Album đang tắt. Bật Album để upload.
              </p>
            )}
            <button
              type="submit"
              disabled={
                uploading ||
                busy ||
                !activeAlbum.is_enabled ||
                files.length < 1 ||
                files.length > 5
              }
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-5 py-3 text-sm font-semibold text-white disabled:opacity-50 sm:w-auto"
            >
              {uploading ? (
                <LoaderCircle size={18} className="animate-spin" />
              ) : (
                <Upload size={18} />
              )}
              {uploading ? "Đang upload..." : "Upload ảnh"}
            </button>
          </form>
          <div className="border-t border-slate-100 pt-5">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
              <h4 className="font-semibold">
                Hình ảnh ({imagePagination?.total ?? 0})
              </h4>
              <button
                type="button"
                onClick={refreshImages}
                className="rounded-lg border border-slate-200 px-3 py-2 text-xs"
              >
                Làm mới ảnh
              </button>
            </div>
            {imageError && (
              <p role="alert" className="mb-4 text-sm text-red-600">
                {imageError}
              </p>
            )}
            {loadingImages ? (
              <p role="status" className="text-sm text-slate-500">
                Đang tải ảnh...
              </p>
            ) : !imageError && imageResult?.data.length === 0 ? (
              <p className="rounded-lg bg-slate-50 p-8 text-center text-sm text-slate-500">
                Album chưa có ảnh.
              </p>
            ) : (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                {imageResult?.data.map((image) => (
                  <div
                    key={image.id}
                    className="overflow-hidden rounded-lg border border-slate-200"
                  >
                    {image.content_url ? (
                      <Image
                        src={image.content_url}
                        alt={image.original_filename}
                        width={400}
                        height={300}
                        unoptimized
                        className="aspect-square w-full object-cover"
                      />
                    ) : (
                      <div className="flex aspect-square items-center justify-center bg-slate-100">
                        <ImageIcon className="text-slate-400" />
                      </div>
                    )}
                    <div className="space-y-1 p-2">
                      <p
                        title={image.original_filename}
                        className="truncate text-xs font-medium"
                      >
                        {image.original_filename}
                      </p>
                      <p className="text-xs text-slate-500">
                        {formatSize(image.file_size)}
                      </p>
                      {image.upload_status !== "ready" && (
                        <p className="text-xs text-amber-700">
                          {image.upload_status}
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
            {imagePagination && imagePagination.total_pages > 1 && (
              <div className="mt-5 flex items-center justify-center gap-4">
                <button
                  type="button"
                  disabled={!imagePagination.has_previous || loadingImages}
                  onClick={() =>
                    setImagePage((value) => Math.max(1, value - 1))
                  }
                  className="rounded-lg border border-slate-200 p-2 disabled:opacity-30"
                >
                  <ChevronLeft size={18} />
                </button>
                <span className="text-sm">
                  {imagePagination.page} / {imagePagination.total_pages}
                </span>
                <button
                  type="button"
                  disabled={!imagePagination.has_next || loadingImages}
                  onClick={() => setImagePage((value) => value + 1)}
                  className="rounded-lg border border-slate-200 p-2 disabled:opacity-30"
                >
                  <ChevronRight size={18} />
                </button>
              </div>
            )}
          </div>
        </div>
      )}
      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/60 p-4">
          <form
            onSubmit={handleEdit}
            className="my-auto w-full max-w-lg space-y-4 rounded-xl bg-white p-5"
          >
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-bold">Chỉnh sửa Album</h3>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setEditing(null);
                  setMutationError("");
                }}
                aria-label="Đóng"
              >
                <X size={20} />
              </button>
            </div>
            <label className="block space-y-2">
              <span className="text-sm">Tên Album</span>
              <input
                required
                maxLength={200}
                value={editName}
                onChange={(event) => setEditName(event.target.value)}
                className={inputStyle}
              />
            </label>
            <label className="block space-y-2">
              <span className="text-sm">Mô tả</span>
              <textarea
                rows={4}
                maxLength={5000}
                value={editDescription}
                onChange={(event) => setEditDescription(event.target.value)}
                className={inputStyle}
              />
            </label>
            {mutationError && (
              <p role="alert" className="text-sm text-red-600">
                {mutationError}
              </p>
            )}
            <button
              type="submit"
              disabled={busy || !editName.trim()}
              className="w-full rounded-lg bg-blue-600 px-5 py-3 text-sm font-semibold text-white disabled:opacity-50"
            >
              {busy ? "Đang lưu..." : "Lưu thay đổi"}
            </button>
          </form>
        </div>
      )}
    </section>
  );
}
