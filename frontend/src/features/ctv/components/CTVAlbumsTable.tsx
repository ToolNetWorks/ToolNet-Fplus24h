"use client";

import { useEffect, useState, type FormEvent } from "react";
import {
  ChevronLeft, ChevronRight, FolderOpen, Pencil, Plus, RefreshCw, Search, X,
} from "lucide-react";
import {
  createAlbum, updateAlbum, type Album, type AlbumInput,
} from "@/features/albums/api/albums";
import { bulkUpdateAlbums, listCTVAlbums, type CTVAlbumList } from "../api/albums";
import CTVAlbumImages from "./CTVAlbumImages";

type EnabledFilter = "all" | "true" | "false";
type FormMode = "create" | "edit" | null;
const emptyForm: AlbumInput = { name: "", description: "", is_enabled: true };
const inputClass = "w-full rounded-md border border-slate-200 bg-white px-3 py-2.5 text-xs text-slate-800 outline-none focus:border-blue-500";
const message = (cause: unknown) => cause instanceof Error ? cause.message : "Không thể thực hiện yêu cầu.";

export default function CTVAlbumsTable({ pipelineId }: { pipelineId: string }) {
  const [result, setResult] = useState<CTVAlbumList | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [enabled, setEnabled] = useState<EnabledFilter>("all");
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [selectedAlbum, setSelectedAlbum] = useState<Album | null>(null);
  const [formMode, setFormMode] = useState<FormMode>(null);
  const [editing, setEditing] = useState<Album | null>(null);
  const [draft, setDraft] = useState<AlbumInput>({ ...emptyForm });

  const refresh = () => setRevision((v) => v + 1);
  const items = result?.data ?? [];
  const pagination = result?.pagination;
  const summary = result?.summary;
  const allSelected = items.length > 0 && items.every((x) => selectedIds.includes(x.id));

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError("");
    listCTVAlbums(pipelineId, { page, pageSize, search, enabled }, controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return;
        setResult(value);
        setSelectedIds([]);
        setSelectedAlbum((current) => {
          if (!current) return null;
          return value.data.find((a) => a.id === current.id) ?? current;
        });
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setResult(null); setSelectedIds([]); setError(message(cause));
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [pipelineId, page, pageSize, search, enabled, revision]);

  function changeOne(id: string, checked: boolean) {
    setSelectedIds((current) => checked ? Array.from(new Set([...current, id])) : current.filter((v) => v !== id));
  }
  function openForm(album?: Album) {
    setEditing(album ?? null);
    setDraft(album ? { name: album.name, description: album.description, is_enabled: album.is_enabled } : { ...emptyForm });
    setFormMode(album ? "edit" : "create"); setError("");
  }

  async function saveForm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !formMode || !draft.name.trim()) return;
    setBusy(true); setError(""); setNotice("");
    try {
      if (formMode === "edit" && editing) {
        const saved = await updateAlbum(pipelineId, editing.id, { ...draft, name: draft.name.trim() });
        if (selectedAlbum?.id === saved.id) setSelectedAlbum({ ...selectedAlbum, ...saved });
        setNotice("Đã cập nhật Album.");
      } else {
        const created = await createAlbum(pipelineId, { ...draft, name: draft.name.trim() });
        setSelectedAlbum(created);
        setPage(1); setEnabled("all"); setSearch(""); setSearchInput("");
        setNotice(`Đã tạo Album "${created.name}".`);
      }
      setFormMode(null); setEditing(null); setDraft({ ...emptyForm });
      refresh();
    } catch (cause) { setError(message(cause)); }
    finally { setBusy(false); }
  }

  async function toggle(album: Album) {
    if (busy) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const updated = await updateAlbum(pipelineId, album.id, { is_enabled: !album.is_enabled });
      if (selectedAlbum?.id === updated.id) setSelectedAlbum({ ...selectedAlbum, ...updated });
      setNotice(updated.is_enabled ? "Đã bật Album." : "Đã tắt Album.");
      refresh();
    } catch (cause) { setError(message(cause)); }
    finally { setBusy(false); }
  }

  async function bulk(enabledValue: boolean) {
    if (busy || selectedIds.length === 0) return;
    if (!window.confirm(`${enabledValue ? "Bật" : "Tắt"} ${selectedIds.length} Album đã chọn?`)) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const data = await bulkUpdateAlbums(pipelineId, selectedIds, enabledValue);
      if (selectedAlbum && selectedIds.includes(selectedAlbum.id)) {
        setSelectedAlbum({ ...selectedAlbum, is_enabled: enabledValue });
      }
      setNotice(`Đã xử lý ${data.selected_count} Album; ${data.updated_count} Album đổi trạng thái.`);
      setSelectedIds([]); setPage(1); refresh();
    } catch (cause) { setError(message(cause)); refresh(); }
    finally { setBusy(false); }
  }

  function searchSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPage(1); setSelectedIds([]); setSearch(searchInput.trim());
  }

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h1 className="text-xl font-bold text-slate-900">Thư viện Album ảnh</h1>
          <p className="mt-1 text-xs text-slate-500">Album và hình ảnh thuộc Pipeline CTV hiện tại.</p></div>
        <button type="button" disabled={busy} onClick={() => openForm()}
          className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2.5 text-xs font-semibold text-white disabled:opacity-40">
          <Plus size={16} /> Tạo Album
        </button>
      </div>
      {notice && <p role="status" className="rounded-md bg-blue-50 p-3 text-xs text-blue-800">{notice}</p>}
      {error && <p role="alert" className="rounded-md bg-red-50 p-3 text-xs text-red-700">{error}</p>}

      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <div className="flex flex-wrap gap-x-5 gap-y-2 border-b border-slate-100 p-4 text-xs">
          <span>Tổng: <strong>{summary?.total ?? "—"}</strong></span>
          <span className="text-green-700">Đang bật: <strong>{summary?.enabled ?? "—"}</strong></span>
          <span className="text-slate-500">Đã tắt: <strong>{summary?.disabled ?? "—"}</strong></span>
          <span className="font-semibold text-blue-700">Đã chọn trên trang: {selectedIds.length}</span>
        </div>
        <div className="flex flex-wrap gap-2 border-b border-slate-100 p-3">
          <form onSubmit={searchSubmit} className="flex min-w-[180px] flex-1 gap-2">
            <div className="relative min-w-0 flex-1"><Search size={15} className="absolute left-3 top-3 text-slate-400" />
              <input value={searchInput} onChange={(event) => setSearchInput(event.target.value)}
                maxLength={100} placeholder="Tìm tên, mô tả Album..." className={`${inputClass} pl-9`} /></div>
            <button type="submit" className="rounded-md border border-slate-200 px-3 text-xs">Tìm</button>
          </form>
          <select aria-label="Lọc trạng thái Album" value={enabled}
            onChange={(event) => { setEnabled(event.target.value as EnabledFilter); setSelectedIds([]); setPage(1); }}
            className={`${inputClass} w-auto`}>
            <option value="all">Tất cả trạng thái</option>
            <option value="true">Đang bật</option>
            <option value="false">Đã tắt</option>
          </select>
          <select aria-label="Số Album mỗi trang" value={pageSize}
            onChange={(event) => { setPageSize(Number(event.target.value)); setSelectedIds([]); setPage(1); }}
            className={`${inputClass} w-auto`}>
            <option value={10}>10 dòng</option><option value={25}>25 dòng</option><option value={50}>50 dòng</option>
          </select>
          <button type="button" disabled={busy} onClick={refresh} aria-label="Làm mới Album"
            className="rounded-md border border-slate-200 p-2 disabled:opacity-40"><RefreshCw size={16} /></button>
        </div>
        {selectedIds.length > 0 && <div className="flex flex-wrap gap-2 border-b border-blue-100 bg-blue-50/50 p-3">
          <button type="button" disabled={busy || loading} onClick={() => void bulk(true)}
            className="rounded-md border border-green-200 bg-white px-3 py-2 text-xs font-semibold text-green-700 disabled:opacity-40">Bật {selectedIds.length} Album</button>
          <button type="button" disabled={busy || loading} onClick={() => void bulk(false)}
            className="rounded-md border border-red-200 bg-white px-3 py-2 text-xs font-semibold text-red-700 disabled:opacity-40">Tắt {selectedIds.length} Album</button>
          <button type="button" disabled={busy} onClick={() => setSelectedIds([])} className="px-3 py-2 text-xs text-slate-600">Bỏ chọn</button>
        </div>}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[850px] text-left text-xs">
            <thead className="bg-slate-50 text-slate-600"><tr className="border-b border-slate-200">
              <th className="w-10 px-3 py-3"><input type="checkbox" aria-label="Chọn tất cả Album trên trang"
                checked={allSelected} disabled={loading || busy || items.length === 0}
                onChange={(event) => setSelectedIds(event.target.checked ? items.map((a) => a.id) : [])}
                className="size-4 accent-blue-600" /></th>
              <th className="px-3 py-3">STT</th><th className="px-3 py-3">Tên Album</th>
              <th className="px-3 py-3">Số ảnh</th><th className="px-3 py-3">Trạng thái</th>
              <th className="px-3 py-3">Ngày tạo</th><th className="px-3 py-3">Thao tác</th>
            </tr></thead>
            <tbody className="divide-y divide-slate-100">
              {loading ? <tr><td colSpan={7} className="p-10 text-center text-slate-500">Đang tải Album...</td></tr> :
                result === null ? <tr><td colSpan={7} className="p-10 text-center text-slate-500">Không tải được danh sách.</td></tr> :
                items.length === 0 ? <tr><td colSpan={7} className="p-10 text-center text-slate-500">Chưa có Album phù hợp.</td></tr> :
                items.map((album, index) => <tr key={album.id}
                  className={selectedIds.includes(album.id) ? "bg-blue-50" : "hover:bg-slate-50"}>
                  <td className="px-3 py-3"><input type="checkbox" checked={selectedIds.includes(album.id)}
                    disabled={busy} onChange={(event) => changeOne(album.id, event.target.checked)}
                    aria-label={`Chọn ${album.name}`} className="size-4 accent-blue-600" /></td>
                  <td className="px-3 py-3 text-slate-500">{(page - 1) * pageSize + index + 1}</td>
                  <td className="max-w-72 px-3 py-3"><p className="truncate font-semibold text-slate-800" title={album.name}>{album.name}</p>
                    <p className="mt-1 max-w-72 truncate text-[11px] text-slate-500" title={album.description}>{album.description || "Chưa có mô tả"}</p></td>
                  <td className="px-3 py-3 font-semibold">{album.image_count}</td>
                  <td className="px-3 py-3"><span className={`rounded-full px-3 py-1 text-[11px] font-semibold ${album.is_enabled ? "bg-green-50 text-green-700" : "bg-slate-100 text-slate-600"}`}>{album.is_enabled ? "Đang bật" : "Đã tắt"}</span></td>
                  <td className="px-3 py-3 text-slate-500">{new Date(album.created_at).toLocaleDateString("vi-VN")}</td>
                  <td className="px-3 py-3"><div className="flex items-center gap-2">
                    <button type="button" disabled={busy} onClick={() => setSelectedAlbum(album)}
                      className="inline-flex items-center gap-1 rounded border border-blue-200 px-2 py-1.5 text-blue-700 disabled:opacity-40"><FolderOpen size={14} /> Quản lý ảnh</button>
                    <button type="button" disabled={busy} onClick={() => openForm(album)}
                      className="inline-flex items-center gap-1 rounded border border-slate-200 px-2 py-1.5 disabled:opacity-40"><Pencil size={13} /> Sửa</button>
                    <button type="button" disabled={busy} onClick={() => void toggle(album)}
                      className="rounded border border-slate-200 px-2 py-1.5 disabled:opacity-40">{album.is_enabled ? "Tắt" : "Bật"}</button>
                  </div></td>
                </tr>)}
            </tbody>
          </table>
        </div>
        <div className="flex items-center justify-between gap-3 border-t border-slate-100 p-4 text-xs text-slate-500">
          <span>{pagination?.total ?? "—"} Album phù hợp</span>
          <div className="flex items-center gap-3">
            <button type="button" aria-label="Trang Album trước" disabled={busy || loading || !pagination?.has_previous}
              onClick={() => setPage((v) => Math.max(1, v - 1))} className="rounded border border-slate-200 p-2 disabled:opacity-30"><ChevronLeft size={16} /></button>
            <span>{pagination ? `${pagination.page}/${pagination.total_pages}` : "—"}</span>
            <button type="button" aria-label="Trang Album tiếp theo" disabled={busy || loading || !pagination?.has_next}
              onClick={() => setPage((v) => v + 1)} className="rounded border border-slate-200 p-2 disabled:opacity-30"><ChevronRight size={16} /></button>
          </div>
        </div>
      </div>

      {selectedAlbum && <CTVAlbumImages key={selectedAlbum.id} pipelineId={pipelineId} album={selectedAlbum}
        onBack={() => setSelectedAlbum(null)} onChanged={refresh} />}

      {formMode && <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-3">
        <form onSubmit={saveForm} role="dialog" aria-modal="true" aria-label="Tạo hoặc chỉnh sửa Album"
          className="max-h-[90dvh] w-full max-w-lg space-y-4 overflow-y-auto rounded-xl bg-white p-5 shadow-xl">
          <div className="flex items-center justify-between"><h2 className="text-lg font-bold">{formMode === "create" ? "Tạo Album" : "Chỉnh sửa Album"}</h2>
            <button type="button" aria-label="Đóng" disabled={busy} onClick={() => setFormMode(null)} className="rounded p-2"><X size={18} /></button></div>
          <label className="block space-y-1"><span className="text-xs font-medium">Tên Album</span>
            <input required maxLength={200} value={draft.name} onChange={(e) => setDraft((v) => ({ ...v, name: e.target.value }))} className={inputClass} /></label>
          <label className="block space-y-1"><span className="text-xs font-medium">Mô tả</span>
            <textarea rows={4} maxLength={5000} value={draft.description} onChange={(e) => setDraft((v) => ({ ...v, description: e.target.value }))} className={inputClass} /></label>
          <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={draft.is_enabled}
            onChange={(e) => setDraft((v) => ({ ...v, is_enabled: e.target.checked }))} className="size-4 accent-blue-600" />Bật Album</label>
          {error && <p role="alert" className="rounded bg-red-50 p-2 text-xs text-red-700">{error}</p>}
          <div className="flex justify-end gap-2"><button type="button" disabled={busy} onClick={() => setFormMode(null)}
            className="rounded border border-slate-200 px-4 py-2 text-xs">Hủy</button>
            <button type="submit" disabled={busy || !draft.name.trim()}
              className="rounded bg-blue-600 px-4 py-2 text-xs font-semibold text-white disabled:opacity-40">{busy ? "Đang lưu..." : "Lưu Album"}</button></div>
        </form>
      </div>}
    </section>
  );
}
