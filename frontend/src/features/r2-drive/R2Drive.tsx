'use client';

import { FormEvent, useEffect, useRef, useState } from 'react';
import { ArrowLeft, ChevronLeft, ChevronRight, Cloud, Folder, Grid2X2, List, Search, RefreshCw, ImageOff, FileImage, File, HardDrive, LoaderCircle, X } from 'lucide-react';
import ImageViewer from './ImageViewer';
import { DriveEntry, DriveLocation, DrivePage, driveUrl, formatBytes, formatDate, readDrive, statusLabel } from './api';
import styles from './R2Drive.module.css';

function Thumbnail({ entry }: { entry: DriveEntry }) {
  const [failed, setFailed] = useState(false);
  if (!entry.thumbnail_url || failed) return <span className={styles.missing}><ImageOff size={28} /><small>{failed ? 'Không tải được ảnh' : statusLabel(entry.status)}</small></span>;
  // Native images retain session authentication, with bounded server-generated thumbnails.
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={entry.thumbnail_url} alt="" loading="lazy" decoding="async" width={360} height={280} onError={() => setFailed(true)} />;
}

export default function R2Drive() {
  const [location, setLocation] = useState<DriveLocation>({});
  const [view, setView] = useState<'grid' | 'list'>('grid');
  const [draft, setDraft] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [cursorStack, setCursorStack] = useState<string[]>(['']);
  const [data, setData] = useState<DrivePage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [selected, setSelected] = useState<DriveEntry | null>(null);
  const content = useRef<HTMLDivElement>(null);
  const focusReturn = useRef<HTMLElement | null>(null);
  const cursor = cursorStack[cursorStack.length - 1];

  useEffect(() => {
    const controller = new AbortController();
    void readDrive<DrivePage>(driveUrl(location, search, page, cursor), controller.signal)
      .then(value => { if (!controller.signal.aborted) { setData(value); setError(''); setLoading(false); } })
      .catch(e => { if (!controller.signal.aborted) { setData(null); setLoading(false); setError(e instanceof Error ? e.message : 'Không tải được thư mục.'); } });
    return () => controller.abort();
  }, [location, search, page, cursor, refresh]);

  function navigate(next: DriveLocation, nextSearch = '') {
    setLocation(next); setSearch(nextSearch); setDraft(nextSearch); setPage(1); setCursorStack(['']); setData(null); setLoading(true); setError('');
  }
  function open(entry: DriveEntry) {
    if (entry.kind === 'pipeline') navigate({ pipeline: { id: entry.pipeline_id!, name: entry.ctv_name!, pipelineName: entry.pipeline_name! } });
    else if (entry.kind === 'album') navigate({ pipeline: { id: entry.pipeline_id!, name: entry.ctv_name!, pipelineName: entry.pipeline_name! }, album: { id: entry.id, name: entry.name } });
    else if (entry.kind === 'prefix') navigate({ raw: true, prefixRef: entry.id });
    else { focusReturn.current = document.activeElement as HTMLElement; setSelected(entry); }
  }
  function closeViewer() { setSelected(null); focusReturn.current?.focus(); }
  function back() {
    if (search) navigate(location);
    else if (location.raw) {
      const crumbs = data?.breadcrumbs ?? [];
      if (!location.prefixRef) navigate({});
      else navigate({ raw: true, prefixRef: crumbs.length > 1 ? crumbs[crumbs.length - 2].ref : undefined });
    } else if (location.album) navigate({ pipeline: location.pipeline });
    else navigate({});
  }
  function submitSearch(event: FormEvent) {
    event.preventDefault();
    if (location.raw) return;
    setSearch(draft.trim()); setPage(1); setLoading(true); setData(null); setRefresh(value => value + 1);
  }
  function changePage(direction: -1 | 1) {
    if (location.raw) {
      if (direction === 1 && data?.next_cursor) setCursorStack(current => [...current, data.next_cursor!]);
      else setCursorStack(current => current.slice(0, -1));
    } else setPage(current => current + direction);
    setLoading(true); setData(null); content.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  const entries = data?.items ?? [];
  const isRoot = !location.pipeline && !location.raw;
  const canBack = Boolean(location.pipeline || location.raw || search);
  const title = search ? `Kết quả cho “${search}”` : location.raw ? 'Thư mục trên R2' : location.album?.name ?? location.pipeline?.name ?? 'Tất cả tệp / CTV';
  const pagination = data?.pagination;
  const prevEnabled = location.raw ? cursorStack.length > 1 : page > 1;
  const imageCount = entries.filter(item => item.kind === 'image' || item.kind === 'object').length;

  return <div className={styles.drive}>
    <header className={styles.header}><div className={styles.brand}><Cloud size={29} strokeWidth={1.8} /><h2>Cloudflare R2 Drive</h2></div><span className={styles.badge}>Admin</span></header>
    <div className={styles.intro}><span className={styles.readOnly}>Chỉ đọc</span><p>Thư viện hình ảnh của các CTV</p></div>
    {!location.raw && <form className={styles.search} onSubmit={submitSearch}><Search size={22} aria-hidden="true" /><input aria-label="Tìm kiếm CTV, Album hoặc hình ảnh" value={draft} maxLength={150} onChange={event => setDraft(event.target.value)} placeholder={location.album ? 'Tìm tên ảnh trong Album…' : location.pipeline ? 'Tìm Album, hình ảnh của CTV…' : 'Tìm CTV, Album, hình ảnh…'} /><button type="submit" disabled={loading}>Tìm</button>{draft && <button type="button" className={styles.iconButton} aria-label="Xóa tìm kiếm" onClick={() => navigate(location)}><X size={18} /></button>}</form>}
    <nav className={styles.breadcrumb} aria-label="Đường dẫn thư mục"><button type="button" onClick={() => navigate({})} disabled={isRoot && !search}>Tất cả CTV</button>
      {location.pipeline && <><ChevronRight size={15} /><button type="button" onClick={() => navigate({ pipeline: location.pipeline })} disabled={!location.album && !search}>{location.pipeline.name}</button></>}
      {location.album && <><ChevronRight size={15} /><span aria-current="page">{location.album.name}</span></>}
      {location.raw && <><ChevronRight size={15} /><button type="button" onClick={() => navigate({ raw: true })} disabled={!location.prefixRef}>R2 prefixes</button>{data?.breadcrumbs?.map(crumb => <span className={styles.crumbPart} key={crumb.ref}><ChevronRight size={15} /><button type="button" onClick={() => navigate({ raw: true, prefixRef: crumb.ref })}>{crumb.name}</button></span>)}</>}
    </nav>
    <div className={styles.toolbar} ref={content}><div className={styles.title}><button type="button" className={styles.iconButton} disabled={!canBack || loading} onClick={back} aria-label="Quay lại thư mục cha"><ArrowLeft size={21} /></button><div><h3>{title}</h3><p>{loading ? 'Đang đọc dữ liệu…' : pagination?.total !== undefined ? `${pagination.total} ${location.album ? 'hình ảnh' : 'mục'}${search ? ' phù hợp' : ''}` : `${entries.length} mục trên trang này`}</p></div></div>
      <div className={styles.viewActions}><button type="button" className={styles.iconButton} disabled={loading} aria-label="Làm mới thư mục" onClick={() => { setLoading(true); setRefresh(value => value + 1); }}><RefreshCw size={19} /></button><div className={styles.viewToggle} aria-label="Chế độ hiển thị" role="group"><button type="button" aria-label="Dạng lưới" aria-pressed={view === 'grid'} onClick={() => setView('grid')}><Grid2X2 size={20} /></button><button type="button" aria-label="Dạng danh sách" aria-pressed={view === 'list'} onClick={() => setView('list')}><List size={22} /></button></div></div>
    </div>
    <div aria-live="polite" aria-busy={loading}>
      {error && <div className={styles.error} role="alert"><p>{error}</p><button type="button" onClick={() => { setLoading(true); setRefresh(value => value + 1); }}>Thử lại</button></div>}
      {loading ? <div className={styles.loading}><span role="status"><LoaderCircle size={21} className={styles.spin} /> Đang tải thư mục…</span><div className={styles.skeletons}>{Array.from({ length: 6 }, (_, i) => <div key={i} />)}</div></div> : !error && entries.length === 0 ? <div className={styles.empty}><Folder size={48} /><h3>{search ? 'Không tìm thấy kết quả' : 'Thư mục chưa có dữ liệu'}</h3><p>{search ? 'Thử tìm bằng tên CTV, Album hoặc tên ảnh khác.' : 'Các Album và ảnh sẽ xuất hiện khi CTV tải lên qua luồng Album hiện có.'}</p></div> :
        <div className={view === 'grid' ? styles.grid : styles.list} aria-label="Nội dung thư mục">{entries.map(entry => {
          const folder = ['pipeline', 'album', 'prefix'].includes(entry.kind);
          return <button type="button" className={`${styles.entry} ${folder ? styles.folder : styles.imageEntry}`} key={`${entry.kind}-${entry.id}`} onClick={() => open(entry)} aria-label={`${folder ? 'Mở thư mục' : 'Xem ảnh'} ${entry.name}`}>
            <span className={styles.visual}>{folder ? <Folder size={58} strokeWidth={1.4} fill="currentColor" /> : entry.kind === 'object' && !entry.thumbnail_url ? <File size={42} /> : <Thumbnail entry={entry} />}</span>
            <span className={styles.entryText}><strong title={entry.name}>{entry.name}</strong><span>{entry.kind === 'pipeline' ? `${entry.album_count ?? 0} Album · ${entry.image_count ?? 0} ảnh` : entry.kind === 'album' ? `${entry.image_count ?? 0} hình ảnh` : entry.kind === 'prefix' ? 'Thư mục R2' : formatBytes(entry.file_size)}</span>{search && entry.ctv_name && <small>{entry.ctv_name}{entry.album_name ? ` / ${entry.album_name}` : ''}</small>}{entry.kind === 'pipeline' && <small title={entry.pipeline_name}>{entry.pipeline_name}</small>}</span>
            {view === 'list' && <span className={styles.listMeta}><span>{statusLabel(entry.status)}</span><small>{formatDate(entry.created_at)}</small></span>}
          </button>;
        })}</div>}
    </div>
    {!loading && !error && data && <footer className={styles.footer}><p>{location.raw ? 'Duyệt prefix trực tiếp · Chỉ đọc' : location.album ? `${pagination?.total ?? 0} ảnh trong Album` : `${imageCount > 0 ? `${imageCount} ảnh · ` : ''}${pagination?.total ?? 0} mục`}</p><div className={styles.pagination}><button type="button" disabled={!prevEnabled} onClick={() => changePage(-1)} aria-label="Trang trước"><ChevronLeft size={18} /></button><span>Trang {location.raw ? cursorStack.length : page}{pagination?.total_pages ? ` / ${pagination.total_pages}` : ''}</span><button type="button" disabled={!pagination?.has_next} onClick={() => changePage(1)} aria-label="Trang tiếp"><ChevronRight size={18} /></button></div></footer>}
    {isRoot && !search && <div className={styles.rawLink}><button type="button" onClick={() => navigate({ raw: true })}><HardDrive size={17} /> Duyệt các prefix khác trên R2 <ChevronRight size={15} /></button><p>Thư mục CTV và Album phía trên được lấy từ dữ liệu Pipeline.</p></div>}
    {location.raw && <p className={styles.note}>Các prefix được liệt kê trực tiếp từ R2 theo từng trang. Tìm kiếm CTV, Album và tên ảnh trong thư viện tại “Tất cả CTV”.</p>}
    {selected && <ImageViewer key={selected.id} entry={selected} onClose={closeViewer} onOpenAlbum={() => { navigate({ pipeline: { id: selected.pipeline_id!, name: selected.ctv_name!, pipelineName: selected.pipeline_name! }, album: { id: selected.album_id!, name: selected.album_name! } }); setSelected(null); }} />}
    <div className={styles.securityNote}><FileImage size={15} /> Chỉ xem và tải ảnh · Không thay đổi dữ liệu hiện có</div>
  </div>;
}
