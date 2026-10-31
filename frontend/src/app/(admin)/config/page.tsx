"use client";

import { useCallback, useEffect, useState } from "react";
import { getCsrfToken } from "@/features/auth/api/auth-client";
import AIConfig from "@/features/ai-config/AIConfig";
import R2Drive from "@/features/r2-drive/R2Drive";
import styles from "./page.module.css";

type R2 = { source: string; account_id: string; endpoint_url: string; bucket_name: string; has_secret: boolean; has_access_key: boolean; override_exists: boolean; override_active: boolean; storage_stats: { total_images: number; total_size_display: string } };
type Database = { host: string; database_name: string; connection_status: string; latency_ms: number; region: string; pool_info: { active_connections: number; max_connections: number; server_version: string; database_size: string }; migrations: { pending_migrations: number; is_synced: boolean }; bootstrap_notice: string };
type Service = { id: string; name: string; status: string; last_heartbeat: string | null; last_error: string | null; systemd_state: string };
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
        <h2>Neon PostgreSQL</h2><dl className={styles.facts}>{Object.entries({ Host: db.host, Database: db.database_name, Vùng: db.region, 'Trạng thái': db.connection_status, 'Độ trễ': `${db.latency_ms} ms`, 'Kết nối đang mở': db.pool_info.active_connections, 'Giới hạn kết nối': db.pool_info.max_connections, 'Dung lượng': db.pool_info.database_size, 'Phiên bản': db.pool_info.server_version, 'Migrations chờ': db.migrations.pending_migrations }).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>
        <p>{db.bootstrap_notice}</p><form onSubmit={e => { e.preventDefault(); void run(() => api("database", "POST", { database_url: dbUrl })); }}><label>URL kết nối thử (để trống để kiểm tra Neon hiện tại)<input type="password" autoComplete="off" value={dbUrl} onChange={e => setDbUrl(e.target.value)} placeholder="postgresql://…" /></label><button disabled={buttonDisabled}>Test Connection</button></form>
      </article>}
      {tab === 1 && r2Area === "connection" && r2 && <article className={styles.card}><h2>Cloudflare R2</h2><p>Nguồn đang dùng: {r2.source} · {r2.storage_stats.total_images} ảnh · {r2.storage_stats.total_size_display}</p><p>Access Key: {r2.has_access_key ? "Đã cấu hình" : "Chưa có"} · Secret: {r2.has_secret ? "Đã mã hóa" : "Chưa có"}</p>
        <form onSubmit={e => { e.preventDefault(); void run(() => api("r2", "POST", storage), true); }}><div className={styles.grid}>{([['account_id', 'Account ID'], ['endpoint_url', 'Endpoint URL'], ['bucket_name', 'Bucket Name'], ['access_key_id', 'Access Key ID'], ['secret_access_key', 'Secret Access Key']] as const).map(([key, label]) => <label key={key}>{label}<input type={key.includes('key') ? 'password' : key === 'endpoint_url' ? 'url' : 'text'} autoComplete="off" required={key === 'bucket_name'} value={storage[key]} placeholder={key.includes('key') ? 'Để trống để giữ credentials hiện tại' : ''} onChange={e => setStorage({ ...storage, [key]: e.target.value })} /></label>)}</div><div className={styles.actions}><button disabled={buttonDisabled}>Save</button><button type="button" disabled={buttonDisabled} onClick={() => void run(() => api("r2/test", "POST", { ...storage, test_read_write: true }))}>Test Connection</button>{r2.override_exists && <><button type="button" disabled={buttonDisabled} onClick={() => void run(() => api("r2", "PATCH", { is_active: !r2.override_active }), true)}>{r2.override_active ? 'Disable override' : 'Enable override'}</button><button type="button" disabled={buttonDisabled} onClick={() => { if (window.confirm('Xóa cấu hình riêng và dùng lại cấu hình môi trường?')) void run(() => api('r2', 'DELETE'), true); }}>Dùng cấu hình môi trường</button></>}</div></form><p>Test Connection ghi object tạm riêng, đọc lại và xóa sau khi kiểm tra.</p>
      </article>}
      {tab === 2 && <AIConfig />}
      {tab === 3 && <article className={styles.card}><h2>System Services</h2><p>Lần kiểm tra: {checkedAt ? new Date(checkedAt).toLocaleString('vi-VN') : '—'}</p><div className={styles.grid}>{services.map(s => <article className={styles.provider} key={s.id}><h3>{s.name}</h3><p><strong>{s.status}</strong> · {s.systemd_state}</p><p>Hoạt động gần nhất: {s.last_heartbeat ? new Date(s.last_heartbeat).toLocaleString('vi-VN') : 'Chưa có dữ liệu'}</p>{s.last_error && <p role="alert">{s.last_error}</p>}</article>)}</div></article>}
    </section>
  </main>;
}
