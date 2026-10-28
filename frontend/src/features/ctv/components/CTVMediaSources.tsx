"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ArrowDown, ArrowUp, ChevronLeft, ChevronRight, GripVertical,
  RefreshCw, Save, Search, SlidersHorizontal, X,
} from "lucide-react";

import { listCTVAlbums, type CTVAlbumList } from "../api/albums";
import {
  getPipelineMediaPolicy,
  savePipelineMediaPolicy,
  type MediaPolicyWrite,
  type MediaSelectionMode,
  type MediaReusePolicy,
  type PipelineMediaPolicy,
} from "../api/media-policy";
import type { Album } from "@/features/albums/api/albums";

type EnabledFilter = "all" | "true" | "false";

type DraftSource = {
  album_id: string;
  album_name: string;
  album_is_enabled: boolean;
  ready_image_count: number | null;
  total_image_count: number | null;
  is_enabled: boolean;
};

type Draft = {
  is_enabled: boolean;
  album_selection: MediaSelectionMode;
  image_selection: MediaSelectionMode;
  reuse_policy: MediaReusePolicy;
  images_per_post: number;
  sources: DraftSource[];
};

const inputClass = "rounded-md border border-slate-200 bg-white px-3 py-2.5 text-xs text-slate-800 outline-none focus:border-blue-500";
const err = (reason: unknown) => reason instanceof Error ? reason.message : "Không thể xử lý yêu cầu.";

function fromServer(data: PipelineMediaPolicy): Draft {
  return {
    is_enabled: data.is_enabled,
    album_selection: data.album_selection,
    image_selection: data.image_selection,
    reuse_policy: data.reuse_policy,
    images_per_post: data.images_per_post,
    sources: data.sources.map((source) => ({
      album_id: source.album_id,
      album_name: source.album_name,
      album_is_enabled: source.album_is_enabled,
      ready_image_count: source.ready_image_count,
      total_image_count: null,
      is_enabled: source.is_enabled,
    })),
  };
}

function toWrite(draft: Draft, version: string | null): MediaPolicyWrite {
  return {
    version,
    is_enabled: draft.is_enabled,
    album_selection: draft.album_selection,
    image_selection: draft.image_selection,
    reuse_policy: draft.reuse_policy,
    images_per_post: draft.images_per_post,
    sources: draft.sources.map((source) => ({
      album_id: source.album_id,
      is_enabled: source.is_enabled,
    })),
  };
}

function sourceFromAlbum(album: Album): DraftSource {
  return {
    album_id: album.id,
    album_name: album.name,
    album_is_enabled: album.is_enabled,
    ready_image_count: null,
    total_image_count: album.image_count,
    is_enabled: album.is_enabled,
  };
}

export default function CTVMediaSources({
  pipelineId, onDirtyChange,
}: {
  pipelineId: string;
  onDirtyChange?: (isDirty: boolean) => void;
}) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [version, setVersion] = useState<string | null>(null);
  const [baseline, setBaseline] = useState("");
  const [loadingPolicy, setLoadingPolicy] = useState(true);
  const [policyError, setPolicyError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [policyRevision, setPolicyRevision] = useState(0);

  const [albums, setAlbums] = useState<CTVAlbumList | null>(null);
  const [loadingAlbums, setLoadingAlbums] = useState(true);
  const [albumError, setAlbumError] = useState("");
  const [page, setPage] = useState(1);
  const [searchText, setSearchText] = useState("");
  const [search, setSearch] = useState("");
  const [enabledFilter, setEnabledFilter] = useState<EnabledFilter>("all");
  const [albumsRevision, setAlbumsRevision] = useState(0);
  const dragId = useRef<string | null>(null);

  const serialized = draft ? JSON.stringify(toWrite(draft, version)) : "";
  const dirty = draft !== null && serialized !== baseline;
  const activeSources = draft?.sources.filter((source) => source.is_enabled) ?? [];
  const inactiveAlbumSources = activeSources.filter((source) => !source.album_is_enabled);
  const knownReady = activeSources.reduce((sum, source) => sum + (source.ready_image_count ?? 0), 0);
  const hasUnknownReady = activeSources.some((source) => source.ready_image_count === null);

  useEffect(() => {
    const controller = new AbortController();
    setLoadingPolicy(true);
    setPolicyError("");
    getPipelineMediaPolicy(pipelineId, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        const next = fromServer(result);
        setVersion(result.version);
        setDraft(next);
        setBaseline(JSON.stringify(toWrite(next, result.version)));
        setSaveError("");
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setDraft(null);
        setBaseline("");
        setPolicyError(err(reason));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingPolicy(false);
      });
    return () => controller.abort();
  }, [pipelineId, policyRevision]);

  useEffect(() => {
    const controller = new AbortController();
    setLoadingAlbums(true);
    setAlbumError("");
    listCTVAlbums(
      pipelineId,
      { page, pageSize: 20, search, enabled: enabledFilter },
      controller.signal,
    )
      .then((result) => {
        if (!controller.signal.aborted) setAlbums(result);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setAlbums(null);
        setAlbumError(err(reason));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingAlbums(false);
      });
    return () => controller.abort();
  }, [pipelineId, page, search, enabledFilter, albumsRevision]);

  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);

  useEffect(() => {
    if (!dirty) return;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [dirty]);

  function updateDraft(transform: (previous: Draft) => Draft) {
    setDraft((previous) => previous ? transform(previous) : previous);
    setSaveError("");
    setNotice("");
  }

  function selectAlbum(album: Album, checked: boolean) {
    updateDraft((current) => {
      if (!checked) {
        return { ...current, sources: current.sources.filter((row) => row.album_id !== album.id) };
      }
      if (current.sources.some((row) => row.album_id === album.id)) return current;
      if (current.sources.length >= 50) return current;
      return { ...current, sources: [...current.sources, sourceFromAlbum(album)] };
    });
    if (checked && (draft?.sources.length ?? 0) >= 50) {
      setSaveError("Chỉ được chọn tối đa 50 Album nguồn.");
    }
  }

  function moveSource(id: string, destination: number) {
    updateDraft((current) => {
      const sourceIndex = current.sources.findIndex((row) => row.album_id === id);
      if (sourceIndex < 0 || destination < 0 || destination >= current.sources.length || sourceIndex === destination) return current;
      const next = [...current.sources];
      const [source] = next.splice(sourceIndex, 1);
      next.splice(destination, 0, source);
      return { ...current, sources: next };
    });
  }

  function dropSource(id: string) {
    const dragged = dragId.current;
    dragId.current = null;
    if (!dragged || dragged === id || !draft) return;
    const index = draft.sources.findIndex((row) => row.album_id === id);
    moveSource(dragged, index);
  }

  function reloadPolicy() {
    if (saving || loadingPolicy) return;
    if (dirty && !window.confirm("Có thay đổi chưa lưu. Tải lại sẽ bỏ các thay đổi đó. Tiếp tục?")) return;
    setNotice("");
    setPolicyRevision((value) => value + 1);
    setAlbumsRevision((value) => value + 1);
  }

  function searchSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPage(1);
    setSearch(searchText.trim());
  }

  async function save() {
    if (!draft || saving || loadingPolicy || !dirty) return;
    if (!Number.isInteger(draft.images_per_post) || draft.images_per_post < 1 || draft.images_per_post > 10) {
      setSaveError("Số ảnh mỗi bài phải từ 1 đến 10.");
      return;
    }
    if (draft.sources.length > 50) {
      setSaveError("Chỉ được chọn tối đa 50 Album nguồn.");
      return;
    }
    if (draft.is_enabled && activeSources.length === 0) {
      setSaveError("Cần ít nhất một nguồn Album đang bật.");
      return;
    }
    if (draft.is_enabled && inactiveAlbumSources.length > 0) {
      setSaveError("Có Album nguồn đang bị tắt trong Thư viện. Hãy bật Album ở mục Quản lý Album ảnh trước.");
      return;
    }

    setSaving(true);
    setSaveError("");
    setNotice("");
    try {
      const result = await savePipelineMediaPolicy(pipelineId, toWrite(draft, version));
      const next = fromServer(result);
      setVersion(result.version);
      setDraft(next);
      setBaseline(JSON.stringify(toWrite(next, result.version)));
      setNotice("Đã lưu cấu hình Album nguồn vào Pipeline.");
      setAlbumsRevision((value) => value + 1);
    } catch (reason) {
      setSaveError(err(reason));
    } finally {
      setSaving(false);
    }
  }

  const selectable = albums?.data ?? [];
  const allSelectedInPage = selectable.length > 0 && selectable.every((album) =>
    draft?.sources.some((row) => row.album_id === album.id));
  const pagination = albums?.pagination;

  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Cấu hình Album nguồn</h1>
          <p className="mt-1 text-xs text-slate-500">Chọn Album và xác định quy tắc lấy ảnh cho Pipeline đang đăng nhập.</p>
        </div>
        <button type="button" onClick={reloadPolicy} disabled={loadingPolicy || saving}
          className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2.5 text-xs disabled:opacity-40">
          <RefreshCw size={15} /> Tải lại cấu hình
        </button>
      </div>

      {policyError && <p role="alert" className="rounded-md bg-red-50 p-3 text-xs text-red-700">{policyError}</p>}
      {notice && <p role="status" className="rounded-md bg-blue-50 p-3 text-xs text-blue-800">{notice}</p>}
      {saveError && <p role="alert" className="rounded-md bg-red-50 p-3 text-xs text-red-700">{saveError}</p>}
      {loadingPolicy && <p role="status" className="rounded-md bg-white p-5 text-xs text-slate-500">Đang tải cấu hình nguồn ảnh...</p>}

      {draft && !loadingPolicy && (
        <div className="space-y-5">
          <div className="rounded-lg border border-slate-200 bg-white p-4 sm:p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="inline-flex items-center gap-2 text-sm font-semibold text-slate-900">
                <SlidersHorizontal size={17} /> Chính sách sử dụng ảnh
              </h2>
              <label className="flex items-center gap-2 text-xs font-medium">
                <input type="checkbox" checked={draft.is_enabled} disabled={saving}
                  onChange={(event) => updateDraft((value) => ({ ...value, is_enabled: event.target.checked }))}
                  className="size-4 accent-blue-600" />
                {draft.is_enabled ? "Đang bật" : "Đang tắt"}
              </label>
            </div>
            <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <label className="space-y-1 text-xs">
                <span className="font-medium">Thứ tự chọn Album</span>
                <select value={draft.album_selection} disabled={saving} className={`${inputClass} w-full`}
                  onChange={(event) => updateDraft((value) => ({ ...value, album_selection: event.target.value as MediaSelectionMode }))}>
                  <option value="in_order">Theo thứ tự ưu tiên</option><option value="random">Ngẫu nhiên</option>
                </select>
              </label>
              <label className="space-y-1 text-xs">
                <span className="font-medium">Cách chọn ảnh</span>
                <select value={draft.image_selection} disabled={saving} className={`${inputClass} w-full`}
                  onChange={(event) => updateDraft((value) => ({ ...value, image_selection: event.target.value as MediaSelectionMode }))}>
                  <option value="in_order">Theo thứ tự ảnh</option><option value="random">Ngẫu nhiên</option>
                </select>
              </label>
              <label className="space-y-1 text-xs">
                <span className="font-medium">Sử dụng lại ảnh</span>
                <select value={draft.reuse_policy} disabled={saving} className={`${inputClass} w-full`}
                  onChange={(event) => updateDraft((value) => ({ ...value, reuse_policy: event.target.value as MediaReusePolicy }))}>
                  <option value="no_repeat">Không lặp</option><option value="cycle">Quay vòng</option>
                </select>
              </label>
              <label className="space-y-1 text-xs">
                <span className="font-medium">Số ảnh mỗi bài đăng</span>
                <input type="number" min={1} max={10} step={1} required value={draft.images_per_post} disabled={saving}
                  onChange={(event) => updateDraft((value) => ({ ...value, images_per_post: Number(event.target.value) }))}
                  className={`${inputClass} w-full`} />
              </label>
            </div>
            <p className="mt-3 text-xs text-slate-500">Đây chỉ là cấu hình. Bộ lập lịch/Publishing Engine chưa thực thi chọn ảnh hoặc đăng Facebook ở bước này.</p>
          </div>

          <div className="rounded-lg border border-slate-200 bg-white p-4 sm:p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 className="text-sm font-semibold text-slate-900">Nguồn Album được chọn</h2>
                <p className="mt-1 text-xs text-slate-500">{draft.sources.length}/50 nguồn · {activeSources.length} đang bật</p>
              </div>
              <span className="text-xs text-slate-500">Kéo thả hoặc dùng nút mũi tên để đổi ưu tiên</span>
            </div>
            {draft.sources.length === 0 ? (
              <p className="mt-4 rounded-md bg-slate-50 p-5 text-xs text-slate-500">Chưa chọn Album nguồn. Chọn ở danh sách bên dưới.</p>
            ) : (
              <div className="mt-4 space-y-2">
                {draft.sources.map((row, index) => (
                  <div key={row.album_id} draggable={!saving}
                    onDragStart={(event) => { dragId.current = row.album_id; event.dataTransfer.effectAllowed = "move"; }}
                    onDragOver={(event) => { if (dragId.current) event.preventDefault(); }}
                    onDrop={(event) => { event.preventDefault(); dropSource(row.album_id); }}
                    onDragEnd={() => { dragId.current = null; }}
                    className="flex flex-wrap items-center gap-3 rounded-md border border-slate-200 bg-slate-50 p-3">
                    <GripVertical size={16} className="text-slate-400" />
                    <span className="w-7 shrink-0 text-xs font-bold text-slate-500">{index + 1}</span>
                    <div className="min-w-[140px] flex-1">
                      <p className="break-words text-xs font-semibold text-slate-900">{row.album_name}</p>
                      <p className="mt-1 text-[11px] text-slate-500">
                        {row.ready_image_count !== null
                          ? `${row.ready_image_count} ảnh sẵn sàng`
                          : `${row.total_image_count ?? "—"} ảnh tổng cộng · chưa kiểm tra trạng thái ready`}
                      </p>
                      {!row.album_is_enabled && <p className="mt-1 text-[11px] text-amber-700">Album đang tắt trong thư viện</p>}
                    </div>
                    <label className="flex items-center gap-1.5 text-xs">
                      <input type="checkbox" checked={row.is_enabled} disabled={saving}
                        onChange={(event) => updateDraft((current) => ({ ...current, sources: current.sources.map((item) =>
                          item.album_id === row.album_id ? { ...item, is_enabled: event.target.checked } : item) }))}
                        className="size-4 accent-blue-600" /> Bật nguồn
                    </label>
                    <div className="flex items-center gap-1">
                      <button type="button" onClick={() => moveSource(row.album_id, index - 1)}
                        disabled={index === 0 || saving} aria-label={`Ưu tiên ${row.album_name} lên`}
                        className="rounded border border-slate-200 bg-white p-2 disabled:opacity-30"><ArrowUp size={15} /></button>
                      <button type="button" onClick={() => moveSource(row.album_id, index + 1)}
                        disabled={index === draft.sources.length - 1 || saving} aria-label={`Ưu tiên ${row.album_name} xuống`}
                        className="rounded border border-slate-200 bg-white p-2 disabled:opacity-30"><ArrowDown size={15} /></button>
                      <button type="button" onClick={() => updateDraft((current) => ({ ...current, sources: current.sources.filter((item) => item.album_id !== row.album_id) }))}
                        disabled={saving} aria-label={`Bỏ Album ${row.album_name}`}
                        className="rounded border border-red-200 bg-white p-2 text-red-600 disabled:opacity-30"><X size={15} /></button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {draft.is_enabled && inactiveAlbumSources.length > 0 && (
              <p className="mt-3 text-xs text-amber-700">Có nguồn đang bật nhưng Album thư viện đang tắt. Cần bật Album trước khi lưu cấu hình hoạt động.</p>
            )}
            {draft.is_enabled && !hasUnknownReady && knownReady < draft.images_per_post && (
              <p className="mt-3 text-xs text-amber-700">Hiện có {knownReady} ảnh ready, chưa đủ cho {draft.images_per_post} ảnh/bài.</p>
            )}
          </div>

          <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 p-4">
              <h2 className="text-sm font-semibold text-slate-900">Danh sách Album có thể chọn</h2>
              <span className="text-xs text-slate-500">{albums?.summary.total ?? "—"} Album trong Pipeline</span>
            </div>
            <div className="flex flex-wrap gap-2 border-b border-slate-100 p-3">
              <form onSubmit={searchSubmit} className="flex min-w-[190px] flex-1 gap-2">
                <div className="relative min-w-0 flex-1">
                  <Search size={15} className="absolute left-3 top-3 text-slate-400" />
                  <input value={searchText} maxLength={100} onChange={(event) => setSearchText(event.target.value)}
                    placeholder="Tìm tên Album..." className={`${inputClass} w-full pl-9`} />
                </div>
                <button type="submit" className="rounded border border-slate-200 px-3 text-xs">Tìm</button>
              </form>
              <select value={enabledFilter} onChange={(event) => { setEnabledFilter(event.target.value as EnabledFilter); setPage(1); }}
                aria-label="Lọc trạng thái Album" className={inputClass}>
                <option value="all">Tất cả Album</option><option value="true">Album đang bật</option><option value="false">Album đã tắt</option>
              </select>
              <button type="button" onClick={() => setAlbumsRevision((value) => value + 1)}
                aria-label="Làm mới danh sách Album" className="rounded border border-slate-200 p-2"><RefreshCw size={16} /></button>
            </div>
            {albumError && <p role="alert" className="m-3 rounded bg-red-50 p-3 text-xs text-red-700">{albumError}</p>}
            <div className="overflow-x-auto">
              <table className="w-full min-w-[680px] text-left text-xs">
                <thead className="bg-slate-50 text-slate-600"><tr className="border-b border-slate-200">
                  <th className="w-12 px-3 py-3">Chọn</th><th className="px-3 py-3">Tên Album</th>
                  <th className="px-3 py-3">Số ảnh</th><th className="px-3 py-3">Trạng thái</th>
                </tr></thead>
                <tbody className="divide-y divide-slate-100">
                  {loadingAlbums ? <tr><td colSpan={4} className="p-8 text-center text-slate-500">Đang tải Album...</td></tr> :
                    albumError ? null : selectable.length === 0 ? <tr><td colSpan={4} className="p-8 text-center text-slate-500">Không có Album phù hợp.</td></tr> :
                    selectable.map((album) => {
                      const checked = Boolean(draft.sources.some((row) => row.album_id === album.id));
                      return <tr key={album.id} className={checked ? "bg-blue-50" : "hover:bg-slate-50"}>
                        <td className="px-3 py-3"><input type="checkbox" checked={checked} disabled={saving || (!checked && draft.sources.length >= 50)}
                          onChange={(event) => selectAlbum(album, event.target.checked)} aria-label={`Chọn Album ${album.name}`}
                          className="size-4 accent-blue-600" /></td>
                        <td className="px-3 py-3"><p className="font-semibold text-slate-800">{album.name}</p>
                          <p className="mt-1 max-w-96 truncate text-[11px] text-slate-500" title={album.description}>{album.description || "—"}</p></td>
                        <td className="px-3 py-3">{album.image_count}</td>
                        <td className="px-3 py-3">{album.is_enabled ? "Đang bật" : "Đã tắt"}</td>
                      </tr>;
                    })}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-between border-t border-slate-100 p-3 text-xs text-slate-500">
              <span>{pagination?.total ?? "—"} Album phù hợp</span>
              <div className="flex items-center gap-3">
                <button type="button" disabled={loadingAlbums || !pagination?.has_previous}
                  onClick={() => setPage((current) => Math.max(1, current - 1))} aria-label="Trang Album trước"
                  className="rounded border border-slate-200 p-2 disabled:opacity-30"><ChevronLeft size={16} /></button>
                <span>{pagination ? `${pagination.page}/${pagination.total_pages}` : "—"}</span>
                <button type="button" disabled={loadingAlbums || !pagination?.has_next}
                  onClick={() => setPage((current) => current + 1)} aria-label="Trang Album tiếp theo"
                  className="rounded border border-slate-200 p-2 disabled:opacity-30"><ChevronRight size={16} /></button>
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white p-4">
            <div>
              <p className="text-xs font-medium text-slate-900">{dirty ? "Có thay đổi chưa lưu" : "Cấu hình đã đồng bộ"}</p>
              <p className="mt-1 text-[11px] text-slate-500">Lưu cấu hình không khởi động lịch đăng bài. Server sẽ kiểm tra ảnh ready khi bật.</p>
            </div>
            <button type="button" onClick={() => void save()} disabled={saving || !dirty || loadingPolicy}
              className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-5 py-2.5 text-xs font-semibold text-white disabled:opacity-40">
              <Save size={16} /> {saving ? "Đang lưu..." : "Lưu cấu hình"}
            </button>
          </div>
        </div>
      )}
      {!allSelectedInPage && !loadingAlbums && draft && draft.sources.length >= 50 && (
        <p className="text-xs text-amber-700">Đã đạt giới hạn 50 nguồn Album. Bỏ bớt nguồn trước khi chọn thêm.</p>
      )}
    </section>
  );
}
