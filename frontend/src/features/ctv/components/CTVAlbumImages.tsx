"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import Image from "next/image";
import {
  ArrowDown, ArrowLeft, ArrowUp, ChevronLeft, ChevronRight,
  GripVertical, ImageIcon, RefreshCw, Trash2, Upload,
} from "lucide-react";
import {
  deleteAlbumImage, listAlbumImages, moveAlbumImage, uploadAlbumImages,
  type Album, type AlbumImage, type AlbumImageMove, type PageResult,
} from "@/features/albums/api/albums";

const message = (cause: unknown) => cause instanceof Error ? cause.message : "Có lỗi xảy ra.";

export default function CTVAlbumImages({
  pipelineId, album, onBack, onChanged,
}: {
  pipelineId: string;
  album: Album;
  onBack: () => void;
  onChanged: () => void;
}) {
  const [page, setPage] = useState(1);
  const [version, setVersion] = useState(0);
  const [result, setResult] = useState<PageResult<AlbumImage> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const dragId = useRef<string | null>(null);

  const refresh = () => setVersion((v) => v + 1);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    listAlbumImages(pipelineId, album.id, page, controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return;
        setResult(value);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setResult(null);
        setError(message(cause));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [pipelineId, album.id, page, version]);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !album.is_enabled || files.length < 1 || files.length > 5) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const uploaded = await uploadAlbumImages(pipelineId, album.id, files);
      setNotice(`Đã upload ${uploaded.length} ảnh lên R2.`);
      setFiles([]);
      if (fileRef.current) fileRef.current.value = "";
      onChanged();
      const total = (result?.pagination.total ?? 0) + uploaded.length;
      const finalPage = Math.max(1, Math.ceil(total / 20));
      if (page !== finalPage) setPage(finalPage);
      else refresh();
    } catch (cause) { setError(message(cause)); }
    finally { setBusy(false); }
  }

  async function remove(image: AlbumImage) {
    if (busy) return;
    if (!window.confirm(`Xóa ảnh "${image.original_filename}" khỏi Album và R2? Không thể hoàn tác.`)) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await deleteAlbumImage(pipelineId, album.id, image.id);
      setNotice("Đã xóa ảnh khỏi Album và R2.");
      onChanged();
      if (page > 1 && result?.data.length === 1) setPage(page - 1);
      else refresh();
    } catch (cause) {
      setError(`${message(cause)}. Hãy tải lại, nếu ảnh ở trạng thái deleting thì có thể thử xóa lại.`);
      refresh(); onChanged();
    } finally { setBusy(false); }
  }

  async function move(payload: AlbumImageMove) {
    if (busy) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await moveAlbumImage(pipelineId, album.id, payload);
      setNotice("Đã lưu thứ tự ảnh.");
    } catch (cause) { setError(message(cause)); }
    finally { dragId.current = null; setBusy(false); refresh(); }
  }

  function drop(target: AlbumImage) {
    const id = dragId.current;
    dragId.current = null;
    if (!id || id === target.id || target.upload_status !== "ready") return;
    const current = result?.data ?? [];
    const sourceIndex = current.findIndex((image) => image.id === id);
    const targetIndex = current.findIndex((image) => image.id === target.id);
    if (sourceIndex < 0 || targetIndex < 0) return;
    void move({ image_id: id, target_id: target.id,
      placement: sourceIndex < targetIndex ? "after" : "before" });
  }

  const items = result?.data ?? [];
  const pagination = result?.pagination;

  return (
    <section className="space-y-4 rounded-lg border border-slate-200 bg-white p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <button type="button" onClick={onBack}
            className="mb-2 inline-flex items-center gap-1 text-xs text-blue-700">
            <ArrowLeft size={15} /> Trở về bảng Album
          </button>
          <h2 className="text-lg font-bold text-slate-900">{album.name}</h2>
          <p className="mt-1 whitespace-pre-wrap text-xs text-slate-500">{album.description || "Quản lý ảnh trong Album."}</p>
        </div>
        <button type="button" onClick={refresh} disabled={busy}
          className="inline-flex items-center gap-2 rounded-md border border-slate-200 px-3 py-2 text-xs disabled:opacity-50">
          <RefreshCw size={15} /> Làm mới ảnh
        </button>
      </div>
      {notice && <p role="status" className="rounded-md bg-blue-50 p-3 text-xs text-blue-800">{notice}</p>}
      {error && <p role="alert" className="rounded-md bg-red-50 p-3 text-xs text-red-700">{error}</p>}
      <form onSubmit={upload} className="space-y-3 rounded-lg bg-slate-50 p-4">
        <label htmlFor="ctv-album-upload" className="block text-xs font-semibold">Upload ảnh lên Cloudflare R2</label>
        <input id="ctv-album-upload" ref={fileRef} type="file" multiple
          accept="image/jpeg,image/png,image/webp"
          disabled={busy || !album.is_enabled}
          onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
          className="block w-full text-xs" />
        <p className="text-xs text-slate-500">JPEG, PNG, WebP · 1–5 ảnh/lần · tối đa 10 MB/ảnh.</p>
        {!album.is_enabled && <p className="text-xs text-amber-700">Album đang tắt. Hãy bật Album trước khi upload.</p>}
        <button type="submit" disabled={busy || !album.is_enabled || !files.length || files.length > 5}
          className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2.5 text-xs font-semibold text-white disabled:opacity-40">
          <Upload size={16} /> {busy ? "Đang xử lý..." : `Upload ${files.length ? files.length + " ảnh" : "ảnh"}`}
        </button>
      </form>
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">Hình ảnh ({pagination?.total ?? "—"})</h3>
          <p className="mt-1 text-xs text-slate-500">Máy tính: kéo thả. Điện thoại: nút lên/xuống.</p>
        </div>
      </div>
      {loading ? <p role="status" className="p-8 text-center text-xs text-slate-500">Đang tải ảnh...</p> :
        !error && items.length === 0 ? <p className="p-8 text-center text-xs text-slate-500">Album chưa có ảnh.</p> :
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {items.map((image, index) => (
            <div key={image.id}
              draggable={image.upload_status === "ready" && !busy}
              onDragStart={(event) => {
                if (busy || image.upload_status !== "ready") { event.preventDefault(); return; }
                dragId.current = image.id;
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/plain", image.id);
              }}
              onDragOver={(event) => {
                if (dragId.current && image.upload_status === "ready") event.preventDefault();
              }}
              onDrop={(event) => { event.preventDefault(); drop(image); }}
              onDragEnd={() => { dragId.current = null; }}
              className="overflow-hidden rounded-lg border border-slate-200">
              {image.content_url ?
                <Image src={image.content_url} alt={image.original_filename} width={400} height={300}
                  unoptimized className="aspect-square w-full object-cover" /> :
                <div className="flex aspect-square items-center justify-center bg-slate-100"><ImageIcon size={28} className="text-slate-400" /></div>}
              <div className="space-y-2 p-2">
                <div className="flex items-center justify-between gap-1 text-xs">
                  <span className="inline-flex items-center gap-1"><GripVertical size={13} /> #{image.position}</span>
                  {image.upload_status === "ready" &&
                    <div className="flex items-center gap-1">
                      <button type="button" aria-label={`Đưa ${image.original_filename} lên`}
                        disabled={busy || (page === 1 && index === 0)}
                        onClick={() => void move({ image_id: image.id, direction: "up" })}
                        className="rounded border border-slate-200 p-1.5 disabled:opacity-30"><ArrowUp size={15} /></button>
                      <button type="button" aria-label={`Đưa ${image.original_filename} xuống`}
                        disabled={busy || (!pagination?.has_next && index === items.length - 1)}
                        onClick={() => void move({ image_id: image.id, direction: "down" })}
                        className="rounded border border-slate-200 p-1.5 disabled:opacity-30"><ArrowDown size={15} /></button>
                    </div>}
                </div>
                <p title={image.original_filename} className="truncate text-xs font-medium">{image.original_filename}</p>
                <p className="text-[11px] text-slate-500">{(image.file_size / 1024 / 1024).toFixed(2)} MB</p>
                {image.upload_status !== "ready" && <p className="text-[11px] text-amber-700">{image.upload_status}</p>}
                {(image.upload_status === "ready" || image.upload_status === "deleting") &&
                  <button type="button" disabled={busy} onClick={() => void remove(image)}
                    className="inline-flex w-full items-center justify-center gap-1 rounded border border-red-200 px-2 py-2 text-xs text-red-700 disabled:opacity-40">
                    <Trash2 size={13} /> {image.upload_status === "deleting" ? "Thử xóa lại" : "Xóa ảnh"}
                  </button>}
              </div>
            </div>
          ))}
        </div>}
      <div className="flex items-center justify-between border-t border-slate-100 pt-3 text-xs text-slate-500">
        <span>{pagination?.total ?? "—"} ảnh</span>
        <div className="flex items-center gap-3">
          <button type="button" aria-label="Trang ảnh trước" disabled={busy || loading || !pagination?.has_previous}
            onClick={() => setPage((v) => Math.max(1, v - 1))} className="rounded border border-slate-200 p-2 disabled:opacity-30"><ChevronLeft size={16} /></button>
          <span>{pagination ? `${pagination.page}/${pagination.total_pages}` : "—"}</span>
          <button type="button" aria-label="Trang ảnh sau" disabled={busy || loading || !pagination?.has_next}
            onClick={() => setPage((v) => v + 1)} className="rounded border border-slate-200 p-2 disabled:opacity-30"><ChevronRight size={16} /></button>
        </div>
      </div>
    </section>
  );
}
