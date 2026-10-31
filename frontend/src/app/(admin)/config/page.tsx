"use client";

import { useCallback, useEffect, useState } from "react";
import { getCsrfToken } from "@/features/auth/api/auth-client";
import AIConfig from "@/features/ai-config/AIConfig";
import R2Drive from "@/features/r2-drive/R2Drive";
import styles from "./page.module.css";

type R2 = { source: string; account_id: string; endpoint_url: string; bucket_name: string; has_secret: boolean; has_access_key: boolean; override_exists: boolean; override_active: boolean; storage_stats: { total_images: number; total_size_display: string } };
type Database = {
  provider: string;
  region: string;
  connection_status: string;
  latency_ms: number;
  last_error: string;
  database_size: string;
  migrations_pending: number;
  migrations_synced: boolean;
  checked_at: number;
};
type Service = { id: string; name: string; status: string; color: string; last_heartbeat: string | null; last_error: string | null; systemd_state: string };
type TestResult = { success: boolean; error?: string; latency_ms?: number };
const tabs = ["Database", "Cloudflare R2", "AI & API", "System Services"];


async function api<T>(path: string, method = "GET", data?: unknown): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (method !== "GET") headers["X-CSRFToken"] = await getCsrfToken();
  const response = await fetch(`/api/v1/admin/config/${path}/`, { method, headers, credentials: "same-origin", cache: "no-store", body: data === undefined ? undefined : JSON.stringify(data), signal: AbortSignal.timeout(180000) });
  const result = await response.json();
  if (!response.ok) throw new Error(response.status === 403 ? "Chỉ Super Admin được truy cập cấu hình." : result.error || result.detail || JSON.stringify(result));
  return result;
}

export default function ConfigPage() {
  const [tab, setTab] = useState(0);
  const [r2Area, setR2Area] = useState<"drive" | "connection">("drive");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [db, setDb] = useState<Database | null>(null);
  const [dbUrl, setDbUrl] = useState("");
  const [r2, setR2] = useState<R2 | null>(null);
  const [storage, setStorage] = useState({ account_id: "", endpoint_url: "", bucket_name: "", access_key_id: "", secret_access_key: "" });
  const [services, setServices] = useState<Service[]>([]);
  const [checkedAt, setCheckedAt] = useState("");
  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      if (tab === 0) setDb(await api<Database>("database"));
      if (tab === 1 && r2Area === "connection") { const value = await api<R2>("r2"); setR2(value); setStorage({ account_id: value.account_id, endpoint_url: value.endpoint_url, bucket_name: value.bucket_name, access_key_id: "", secret_access_key: "" }); }
      if (tab === 3) { const value = await api<{ services: Service[]; checked_at: string }>("services"); setServices(value.services); setCheckedAt(value.checked_at); }
    } catch (e) { setError(e instanceof Error ? e.message : "Không tải được cấu hình."); }
    finally { setLoading(false); }
  }, [tab, r2Area]);
  useEffect(() => {
    let cancelled = false;
    void Promise.resolve().then(() => { if (!cancelled) return load(); });
    return () => { cancelled = true; };
  }, [load]);
  async function run(work: () => Promise<unknown>, refresh = false) {
    setBusy(true); setError(""); setMessage("");
    try { const value = await work() as Partial<TestResult> | undefined; if (value?.success === false) throw new Error(value.error || "Kiểm tra kết nối thất bại."); if (refresh) await load(); setMessage(value?.success ? `Kết nối thành công (${value.latency_ms ?? "—"} ms).` : "Đã cập nhật cấu hình."); }
    catch (e) { setError(e instanceof Error ? e.message : "Thao tác thất bại."); }
    finally { setBusy(false); }
  }
  const buttonDisabled = busy || loading;
  
  // Function to translate status to Vietnamese
  const getStatusVietnamese = (status: string): string => {
    const statusMap: Record<string, string> = {
      'running': 'Đang hoạt động',
      'healthy': 'Khỏe mạnh',
      'connected': 'Đã kết nối',
      'stopped': 'Dừng',
      'error': 'Lỗi',
      'unknown': 'Không xác định',
      'standby': 'Chờ',
      'degraded': 'Giảm sút',
      'idle': 'Không hoạt động',
      'failed': 'Thất bại',
    };
    return statusMap[status] || status;
  };
  
  return <main className={styles.page}>
    <header><h1>Cấu hình hệ thống</h1><p>Quản lý kết nối và dịch vụ · Chỉ dành cho Super Admin</p></header>
    <div className={styles.tabs} role="tablist" aria-label="Cấu hình">{tabs.map((name, i) => <button key={name} role="tab" aria-selected={tab === i} aria-controls={`config-panel-${i}`} id={`config-tab-${i}`} disabled={busy} onClick={() => { setMessage(""); setTab(i); }}>{name}</button>)}</div>
    {error && <div className={styles.error} role="alert">{error}</div>}
    {message && <div className={styles.success} role="status">{message}</div>}
    {loading && <p role="status">Đang tải dữ liệu thực tế…</p>}
    {busy && <p role="status">Đang xử lý…</p>}
    <section role="tabpanel" id={`config-panel-${tab}`} aria-labelledby={`config-tab-${tab}`} aria-busy={loading || busy}>
      {(tab !== 2 && (tab !== 1 || r2Area === "connection")) && <button disabled={buttonDisabled} onClick={() => void load()}>Làm mới</button>}
      {tab === 1 && <><div className={styles.r2Areas} role="group" aria-label="Cloudflare R2"><button type="button" aria-pressed={r2Area === "drive"} onClick={() => setR2Area("drive")}>Quản lý tệp</button><button type="button" aria-pressed={r2Area === "connection"} onClick={() => setR2Area("connection")}>Kết nối R2</button></div>{r2Area === "drive" && <R2Drive />}</>}
      {tab === 0 && db && <article className={styles.card}>
        <h2>Neon PostgreSQL</h2><div className={styles.dashboard}><div className={styles.metric}><span>Trạng thái</span><strong className={`${styles.status} ${styles[db.connection_status || "unknown"]}`}>{db.connection_status}</strong></div><div className={styles.metric}><span>Độ trễ</span><span>{db.latency_ms} ms</span></div><div className={styles.metric}><span>Dung lượng</span><span>{db.database_size}</span></div><div className={styles.metric}><span>Migrations chờ</span><span>{db.migrations_pending}</span></div><div className={styles.metric}><span>Cập nhật lần cuối</span><span>{db.checked_at ? new Date(db.checked_at).toLocaleString("vi-VN") : "—"}</span></div></div><p>{db.migrations_synced ? "Đã đồng bộ hóa." : "Chưa đồng bộ hóa migrations."}</p></article>}
      {tab === 1 && r2Area === "connection" && r2 && <article className={styles.card}><h2>Cloudflare R2</h2><p>Nguồn đang dùng: {r2.source} · {r2.storage_stats.total_images} ảnh · {r2.storage_stats.total_size_display}</p><p>Access Key: {r2.has_access_key ? "Đã cấu hình" : "Chưa có"} · Secret: {r2.has_secret ? "Đã mã hóa" : "Chưa có"}</p>
        <form onSubmit={e => { e.preventDefault(); void run(() => api("r2", "POST", storage), true); }}><div className={styles.grid}>{([['account_id', 'Account ID'], ['endpoint_url', 'Endpoint URL'], ['bucket_name', 'Bucket Name'], ['access_key_id', 'Access Key ID'], ['secret_access_key', 'Secret Access Key']] as const).map(([key, label]) => <label key={key}>{label}<input type={key.includes('key') ? 'password' : key === 'endpoint_url' ? 'url' : 'text'} autoComplete="off" required={key === 'bucket_name'} value={storage[key]} placeholder={key.includes('key') ? 'Để trống để giữ credentials hiện tại' : ''} onChange={e => setStorage({ ...storage, [key]: e.target.value })} /></label>)}</div><div className={styles.actions}><button disabled={buttonDisabled}>Save</button><button type="button" disabled={buttonDisabled} onClick={() => void run(() => api("r2/test", "POST", { ...storage, test_read_write: true }))}>Test Connection</button>{r2.override_exists && <><button type="button" disabled={buttonDisabled} onClick={() => void run(() => api("r2", "PATCH", { is_active: !r2.override_active }), true)}>{r2.override_active ? 'Disable override' : 'Enable override'}</button><button type="button" disabled={buttonDisabled} onClick={() => { if (window.confirm('Xóa cấu hình riêng và dùng lại cấu hình môi trường?')) void run(() => api('r2', 'DELETE'), true); }}>Dùng cấu hình môi trường</button></>}</div></form><p>Test Connection ghi object tạm riêng, đọc lại và xóa sau khi kiểm tra.</p>
      </article>}
      {tab === 2 && <AIConfig />}
      {tab === 3 && <article className={styles.card}><h2>System Services</h2><p>Lần kiểm tra: {checkedAt ? new Date(checkedAt).toLocaleString('vi-VN') : '—'}</p><div className={styles.grid}>{services.map(s => <article className={styles.provider} key={s.id}><div className={styles.providerHeader}><h3>{s.name}</h3><div className={styles.statusWrapper}><div className={`${styles.statusIcon} ${styles[s.color]}`}><svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10 10-4.5 10-10S17.5 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm.5-13H11v6l5.2 3.2.8-.8-4.4-4.4z"/></svg></div></div></div><div className={styles.statusText}><strong className={styles.statusValue}>{s.status}</strong><p>{getStatusVietnamese(s.status)}</p></div>{s.last_error && <p role="alert" className={styles.errorText}>{s.last_error}</p>}{s.last_heartbeat && <p>Hoạt động gần nhất: {new Date(s.last_heartbeat).toLocaleString('vi-VN')}</p>}</article>)}</div><button className={styles.refreshButton} onClick={() => load()}>Làm mới trạng thái</button></article>}
    </section>
  </main>;
}
