'use client';

import { useEffect, useRef, useState } from 'react';
import { Download, X, ImageOff, LoaderCircle, FolderOpen } from 'lucide-react';
import { DriveEntry, formatBytes, formatDate, readDrive, statusLabel } from './api';
import styles from './R2Drive.module.css';

export default function ImageViewer({ entry, onClose, onOpenAlbum }: { entry: DriveEntry; onClose: () => void; onOpenAlbum: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [metadata, setMetadata] = useState(entry);
  const [loading, setLoading] = useState(Boolean(entry.preview_url));
  const [imageError, setImageError] = useState(false);
  const [error, setError] = useState('');
  const [downloading, setDownloading] = useState(false);
  const [dimensions, setDimensions] = useState<{ width: number; height: number } | null>(null);

  useEffect(() => {
    const node = dialog.current;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    node?.showModal();
    return () => { node?.close(); document.body.style.overflow = overflow; };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    if (entry.metadata_url) {
      void readDrive<Partial<DriveEntry>>(entry.metadata_url, controller.signal)
        .then(value => setMetadata({ ...entry, ...value }))
        .catch(() => { if (!controller.signal.aborted) setError('Không làm mới được metadata. Thử mở lại ảnh.'); });
    }
    return () => controller.abort();
  }, [entry]);

  async function download() {
    if (!entry.download_url) return;
    setDownloading(true); setError('');
    try {
      const response = await fetch(entry.download_url, { credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(45000) });
      if (!response.ok) throw new Error('Không tải được ảnh. Vui lòng thử lại.');
      const blob = await response.blob();
      if (!blob.type.startsWith('image/')) throw new Error('Dữ liệu ảnh không hợp lệ.');
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      // Album uploads are converted to WebP; preserve the original basename with the actual extension.
      link.download = entry.kind === 'image' ? `${entry.name.replace(/\.[^.]+$/, '')}.webp` : entry.name;
      document.body.appendChild(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) { setError(e instanceof Error ? e.message : 'Không tải được ảnh.'); }
    finally { setDownloading(false); }
  }

  return <dialog ref={dialog} className={styles.viewer} aria-labelledby="r2-image-title" onCancel={event => { event.preventDefault(); onClose(); }} onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div className={styles.viewerHeader}><div><span className={styles.eyebrow}>XEM TRƯỚC HÌNH ẢNH</span><h2 id="r2-image-title">{entry.name}</h2></div><button type="button" onClick={onClose} aria-label="Đóng ảnh"><X size={22} /></button></div>
    <div className={styles.viewerBody}>
      <div className={styles.preview}>
        {loading && !imageError && <span className={styles.previewLoading}><LoaderCircle className={styles.spin} size={24} /> Đang tải ảnh…</span>}
        {imageError ? <div className={styles.previewLoading}><ImageOff size={32} /><p>Không đọc được ảnh. Thử mở lại hoặc kiểm tra kết nối R2.</p></div> : entry.preview_url ?
          // Protected same-origin image endpoint: cookies must reach Django; no public object URL.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={entry.preview_url} alt={entry.name} onLoad={event => { setLoading(false); setDimensions({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight }); }} onError={() => { setImageError(true); setLoading(false); }} /> : <p>File này không hỗ trợ xem trước.</p>}
      </div>
      <aside className={styles.details}><h3>Chi tiết ảnh</h3><dl>
        <dt>Tên gốc</dt><dd>{entry.name}</dd>
        {entry.ctv_name && <><dt>CTV / Pipeline</dt><dd>{entry.ctv_name} · {entry.pipeline_name}</dd></>}
        {entry.album_name && <><dt>Album</dt><dd>{entry.album_name}</dd></>}
        <dt>Kích thước</dt><dd>{metadata.width || dimensions?.width ? `${metadata.width ?? dimensions?.width} × ${metadata.height ?? dimensions?.height} px` : '—'}</dd>
        <dt>Dung lượng</dt><dd>{formatBytes(metadata.file_size)}</dd><dt>Ngày upload</dt><dd>{formatDate(metadata.created_at)}</dd><dt>Trạng thái</dt><dd>{statusLabel(metadata.status)}</dd>
      </dl><button type="button" className={styles.primary} disabled={!entry.download_url || downloading} onClick={() => void download()}><Download size={18} />{downloading ? 'Đang tải…' : 'Tải ảnh về thiết bị'}</button>
      {entry.album_id && <button type="button" onClick={onOpenAlbum}><FolderOpen size={18} /> Mở Album chứa ảnh</button>}
      {entry.kind === 'image' && <p className={styles.note}>Ảnh được lưu và tải xuống ở định dạng WebP.</p>}
      {error && <p className={styles.error} role="alert">{error}</p>}</aside>
    </div>
  </dialog>;
}
