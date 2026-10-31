'use client';
import { FormEvent, useEffect, useState } from 'react';
import { BrainCircuit, Plus, Server, RefreshCw, KeyRound, Check, ChevronRight, Workflow, FlaskConical, ArrowDown, ShieldCheck } from 'lucide-react';
import { aiAPI, Catalog, Provider, Key, Model, ModelPage, Route, Step, TestResult } from './api';
import ModelPicker from './ModelPicker';
import styles from './AIConfig.module.css';

const blankProvider = { name: '', provider_type: 'toolnet', base_url: 'https://api.toolnet.tech/v1', api_key: '', custom_headers: '', timeout_seconds: 60, is_active: false, rotation_authorized: false };
const blankModel = { model_id: '', display_name: '', is_enabled: false, supports_temperature: '', supports_top_p: '', temperature: '', top_p: '', max_output_tokens: '', token_parameter: 'max_tokens', request_timeout: 60, retry_count: 0 };
const blankStep = (): Step => ({ provider: '', model: '', priority: 1, timeout: 60, retries: 0, key_policy: 'priority' });
const date = (value: string | null) => value ? new Date(value).toLocaleString('vi-VN') : 'Chưa kiểm tra';

function parseHeaders(value: string): Record<string, string> {
  if (!value.trim()) return {};
  try {
    const data = JSON.parse(value);
    if (!data || Array.isArray(data) || typeof data !== 'object') throw new Error();
    return data;
  } catch { throw new Error('Custom Headers phải là JSON object hợp lệ.'); }
}

function TestOutput({ value }: { value: TestResult }) {
  return <div className={styles.testOutput} role="status"><strong>{value.success ? 'Thành công' : 'Thất bại'} · HTTP {value.http_status ?? '—'} · {value.latency_ms ?? '—'} ms</strong>{value.provider && <p>{value.provider} → {value.model}</p>}{value.error && <p>{value.error}</p>}{value.discovered !== undefined && <p>{value.discovered} Models được API trả về.</p>}{value.text && <pre>{value.text}</pre>}{value.usage && <p>Token Usage: {Object.entries(value.usage).map(([name, count]) => `${name}: ${count}`).join(' · ') || 'Provider không trả số liệu.'}</p>}{value.fallback_index !== undefined && <p>Bước định tuyến: {value.fallback_index === 0 ? 'Primary' : `Fallback ${value.fallback_index}`}</p>}</div>;
}

export default function AIConfig() {
  const [tab, setTab] = useState(0);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [routes, setRoutes] = useState<Route[]>([]);
  const [selected, setSelected] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [providerForm, setProviderForm] = useState({ ...blankProvider });
  const [editingProvider, setEditingProvider] = useState<string | null>(null);
  const [showProvider, setShowProvider] = useState(false);
  const [keys, setKeys] = useState<Key[]>([]);
  const [keyForm, setKeyForm] = useState({ name: '', secret: '', priority: 10, is_active: true });
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [modelPage, setModelPage] = useState<ModelPage | null>(null);
  const [page, setPage] = useState(1);
  const [modelQuery, setModelQuery] = useState('');
  const [modelSearch, setModelSearch] = useState('');
  const [modelLoading, setModelLoading] = useState(false);
  const [modelForm, setModelForm] = useState({ ...blankModel });
  const [editingModel, setEditingModel] = useState<string | null>(null);
  const [showModel, setShowModel] = useState(false);
  const [testModel, setTestModel] = useState<Model | null>(null);
  const [testPrompt, setTestPrompt] = useState('Viết một câu chào bằng tiếng Việt.');
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [task, setTask] = useState('caption_generation');
  const [primary, setPrimary] = useState<Step>(blankStep);
  const [fallbacks, setFallbacks] = useState<Step[]>([]);
  const [routeEnabled, setRouteEnabled] = useState(false);
  const [routeVersion, setRouteVersion] = useState(0);
  const [routeDirty, setRouteDirty] = useState(false);
  const currentProvider = providers.find(p => p.id === selected);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([aiAPI<Catalog>('registry', 'GET', undefined, controller.signal), aiAPI<Provider[]>('providers', 'GET', undefined, controller.signal), aiAPI<Route[]>('routes', 'GET', undefined, controller.signal)])
      .then(([registry, list, routing]) => { if (!controller.signal.aborted) { setCatalog(registry); setProviders(list); setRoutes(routing); setSelected(current => current || list[0]?.id || ''); setLoading(false); } })
      .catch(e => { if (!controller.signal.aborted) { setError(e instanceof Error ? e.message : 'Không tải được cấu hình.'); setLoading(false); } });
    return () => controller.abort();
  }, [refresh]);

  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    void aiAPI<Key[]>(`providers/${selected}/keys`, 'GET', undefined, controller.signal).then(value => { if (!controller.signal.aborted) setKeys(value); }).catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Không tải được Keys.'); });
    return () => controller.abort();
  }, [selected, refresh]);

  useEffect(() => {
    if (!selected || tab !== 1) return;
    const controller = new AbortController();
    void aiAPI<ModelPage>(`providers/${selected}/models?page=${page}&q=${encodeURIComponent(modelSearch)}`, 'GET', undefined, controller.signal)
      .then(value => { if (!controller.signal.aborted) { setModelPage(value); setModelLoading(false); } })
      .catch(e => { if (!controller.signal.aborted) { setModelLoading(false); setError(e instanceof Error ? e.message : 'Không tải được Models.'); } });
    return () => controller.abort();
  }, [selected, page, modelSearch, tab, refresh]);

  useEffect(() => {
    const route = routes.find(value => value.task === task);
    if (!route || routeDirty || route.version < routeVersion) return;
    let cancelled = false;
    void Promise.resolve().then(() => {
      if (cancelled) return;
      setPrimary({ ...blankStep(), provider: route.primary_provider, model: route.primary_model, model_name: route.primary_model_name, key_policy: route.key_policy });
      setFallbacks(route.fallbacks); setRouteEnabled(route.is_enabled); setRouteVersion(route.version);
    });
    return () => { cancelled = true; };
  }, [routes, task, routeDirty, routeVersion]);

  async function run(work: () => Promise<unknown>, message = 'Đã lưu cấu hình.', reload = true) {
    setBusy(true); setError(''); setNotice(''); setTestResult(null);
    try { await work(); setNotice(message); if (reload) setRefresh(value => value + 1); }
    catch (e) { setError(e instanceof Error ? e.message : 'Thao tác thất bại.'); }
    finally { setBusy(false); }
  }
  function chooseProvider(id: string) {
    setSelected(id); setPage(1); setModelPage(null); setModelSearch(''); setModelQuery(''); setKeys([]); setShowModel(false); setTestModel(null); setTestResult(null); setKeyForm({ name: '', secret: '', priority: 10, is_active: true }); setEditingKey(null); setModelLoading(true);
  }
  function editProvider(provider: Provider) {
    setEditingProvider(provider.id); setProviderForm({ ...blankProvider, ...provider, api_key: '', custom_headers: '' }); setShowProvider(true); chooseProvider(provider.id);
  }
  function saveProvider(event: FormEvent) {
    event.preventDefault();
    void run(async () => {
      const { custom_headers, ...values } = providerForm;
      const headers = custom_headers.trim() ? parseHeaders(custom_headers) : undefined;
      const result = await aiAPI<Provider>(editingProvider ? `providers/${editingProvider}` : 'providers', editingProvider ? 'PATCH' : 'POST', { ...values, ...(headers ? { custom_headers: headers } : {}) });
      setSelected(result.id); setShowProvider(false); setProviderForm({ ...blankProvider }); setEditingProvider(null);
    });
  }
  function saveKey(event: FormEvent) {
    event.preventDefault();
    if (editingKey && keyForm.secret && !window.confirm('Rotate Key này cho các yêu cầu mới? Key cũ sẽ được thay thế.')) return;
    void run(async () => { await aiAPI(editingKey ? `providers/${selected}/keys/${editingKey}` : `providers/${selected}/keys`, editingKey ? 'PATCH' : 'POST', keyForm); setKeyForm({ name: '', secret: '', priority: 10, is_active: true }); setEditingKey(null); });
  }
  function editModel(model: Model) {
    setEditingModel(model.id); setModelForm({ model_id: model.model_id, display_name: model.display_name, is_enabled: model.is_enabled, supports_temperature: model.supports_temperature === null ? '' : String(model.supports_temperature), supports_top_p: model.supports_top_p === null ? '' : String(model.supports_top_p), temperature: model.temperature === null ? '' : String(model.temperature), top_p: model.top_p === null ? '' : String(model.top_p), max_output_tokens: model.max_output_tokens === null ? '' : String(model.max_output_tokens), token_parameter: model.token_parameter, request_timeout: model.request_timeout, retry_count: model.retry_count }); setShowModel(true);
  }
  function saveModel(event: FormEvent) {
    event.preventDefault();
    const numberOrNull = (value: string) => value.trim() ? Number(value) : null;
    void run(async () => {
      await aiAPI(editingModel ? `providers/${selected}/models/${editingModel}` : `providers/${selected}/models`, editingModel ? 'PATCH' : 'POST', { ...modelForm, supports_temperature: modelForm.supports_temperature === '' ? null : modelForm.supports_temperature === 'true', supports_top_p: modelForm.supports_top_p === '' ? null : modelForm.supports_top_p === 'true', temperature: modelForm.supports_temperature === 'true' ? numberOrNull(modelForm.temperature) : null, top_p: modelForm.supports_top_p === 'true' ? numberOrNull(modelForm.top_p) : null, max_output_tokens: numberOrNull(modelForm.max_output_tokens) });
      setShowModel(false); setModelForm({ ...blankModel }); setEditingModel(null);
    });
  }
  function chooseTask(next: string) {
    const route = routes.find(r => r.task === next);
    setTask(next); setPrimary(route ? { ...blankStep(), provider: route.primary_provider, model: route.primary_model, model_name: route.primary_model_name, key_policy: route.key_policy } : blankStep()); setFallbacks(route?.fallbacks ?? []); setRouteEnabled(route?.is_enabled ?? false); setRouteVersion(route?.version ?? 0); setRouteDirty(false); setTestResult(null);
  }
  function loadRoute() { chooseTask(task); }
  function saveRoute(event: FormEvent) {
    event.preventDefault();
    void run(async () => {
      const route = await aiAPI<Route>(`routes/${task}`, 'PUT', { primary_model: primary.model, key_policy: primary.key_policy, is_enabled: routeEnabled, expected_version: routeVersion, fallbacks: fallbacks.map((step, index) => ({ model: step.model, priority: index + 1, timeout: step.timeout, retries: step.retries, key_policy: step.key_policy })) });
      setRouteVersion(route.version); setRouteDirty(false);
    }, 'Đã lưu tuyến. Các yêu cầu AI mới sẽ dùng cấu hình này.');
  }
  const providerSelect = <label>Nhà cung cấp<select value={selected} onChange={event => chooseProvider(event.target.value)} disabled={busy || !providers.length}>{!providers.length && <option value="">Chưa có Provider</option>}{providers.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>;

  return <section className={styles.ai} aria-label="Cấu hình AI và API">
    <header className={styles.header}><div className={styles.heading}><span className={styles.headingIcon}><BrainCircuit size={27} /></span><div><h2>Cấu hình AI</h2><p>Quản lý nhà cung cấp, Models và định tuyến AI</p></div></div><span className={styles.admin}>Admin</span></header>
    <nav className={styles.tabs} aria-label="Cấu hình AI">{['Nhà cung cấp', 'Models', 'Định tuyến'].map((name, i) => <button type="button" key={name} aria-pressed={tab === i} disabled={busy || loading} onClick={() => { setTab(i); setTestResult(null); if (i === 1 && tab !== 1) setModelLoading(true); if (i === 2) chooseTask(task); }}>{name}</button>)}</nav>
    {loading && <p role="status">Đang tải cấu hình…</p>}{busy && <p role="status" className={styles.loading}><RefreshCw size={16} />Đang xử lý…</p>}{error && <div className={styles.error} role="alert">{error}<button type="button" onClick={() => setRefresh(v => v + 1)}>Tải lại</button></div>}{notice && <div className={styles.success} role="status"><Check size={16} />{notice}</div>}
    {tab === 0 && <>
      <div className={styles.sectionTitle}><div><h3>Nhà cung cấp AI</h3><p>{providers.length} nhà cung cấp đã cấu hình</p></div><button type="button" className={styles.primary} disabled={busy} onClick={() => { setProviderForm({ ...blankProvider }); setEditingProvider(null); setShowProvider(true); }}><Plus size={17} /> Thêm nhà cung cấp</button></div>
      {catalog?.legacy.configured && <div className={styles.legacy}><ShieldCheck size={21} /><div><strong>Cấu hình production hiện có được giữ nguyên</strong><p>ToolNetAPI · {catalog.legacy.model} · Key từ môi trường bảo mật</p></div><button type="button" disabled={busy} onClick={() => void run(async () => { const imported = await aiAPI<Provider>('import-legacy', 'POST', {}); chooseProvider(imported.id); }, 'Đã tiếp nhận legacy ở trạng thái Disabled. Chưa đổi runtime.')}>Tiếp nhận cấu hình</button></div>}
      <div className={styles.cards}>{providers.map(p => <article className={`${styles.providerCard} ${selected === p.id ? styles.selected : ''}`} key={p.id}><div className={styles.providerTop}><span className={styles.providerIcon}><Server size={22} /></span><div><h4>{p.name}</h4><p>{catalog?.providers.find(t => t.id === p.provider_type)?.name ?? p.provider_type}</p></div>{p.is_default && <span className={styles.default}>Mặc định</span>}</div><p className={styles.url}>{p.base_url}</p><div className={styles.metrics}><span>{p.is_active ? 'Enabled' : 'Disabled'}</span><span>{p.last_status}</span><span>{p.key_count} Keys</span><span>{p.model_count} Models</span></div><div className={styles.actions}><button type="button" disabled={busy} onClick={() => editProvider(p)}>Chỉnh sửa</button><button type="button" disabled={busy} onClick={() => { chooseProvider(p.id); void run(async () => { const result = await aiAPI<TestResult>(`providers/${p.id}/test`, 'POST', {}); setTestResult(result); }, 'Đã kiểm tra kết nối.'); }}>Kiểm tra</button><button type="button" disabled={busy} onClick={() => { if (window.confirm(`${p.is_active ? 'Tắt' : 'Bật'} Provider ${p.name}? Các tác vụ AI mới có thể bị ảnh hưởng.`)) void run(() => aiAPI(`providers/${p.id}`, 'PATCH', { is_active: !p.is_active, ...(p.is_active && p.is_default ? { is_default: false } : {}) })); }}>{p.is_active ? 'Tắt' : 'Bật'}</button><button type="button" disabled={busy} onClick={() => chooseProvider(p.id)}><KeyRound size={15} /> Keys</button><button type="button" disabled={busy} onClick={() => { if (window.confirm(`Xóa Provider ${p.name} cùng cấu hình Keys/Models? Tuyến đang dùng sẽ chặn xóa.`)) void run(() => aiAPI(`providers/${p.id}`, 'DELETE')); }}>Xóa</button></div></article>)}</div>
      {!loading && !providers.length && <p className={styles.empty}>Chưa có Provider trong registry. Caption tiếp tục dùng cấu hình legacy.</p>}
      {showProvider && <article className={styles.panel}><h3>{editingProvider ? 'Chỉnh sửa Provider' : 'Thêm nhà cung cấp'}</h3><form onSubmit={saveProvider}><div className={styles.formGrid}><label>Provider Name<input required maxLength={120} value={providerForm.name} onChange={e => setProviderForm({ ...providerForm, name: e.target.value })} /></label><label>Provider Type<select value={providerForm.provider_type} onChange={e => setProviderForm({ ...providerForm, provider_type: e.target.value, base_url: catalog?.providers.find(p => p.id === e.target.value)?.base_url ?? '' })}>{catalog?.providers.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label><label>Base URL<input type="url" required placeholder="https://…" value={providerForm.base_url} onChange={e => setProviderForm({ ...providerForm, base_url: e.target.value })} /></label><label>API Key<input type="password" autoComplete="new-password" required={!editingProvider} value={providerForm.api_key} placeholder={editingProvider ? 'Để trống để giữ Key cũ' : ''} onChange={e => setProviderForm({ ...providerForm, api_key: e.target.value })} /></label><label>Timeout (giây)<input type="number" min={1} max={120} required value={providerForm.timeout_seconds} onChange={e => setProviderForm({ ...providerForm, timeout_seconds: Number(e.target.value) })} /></label></div><label>Custom Headers · JSON (tùy chọn)<textarea rows={3} value={providerForm.custom_headers} placeholder={'{"X-Title": "ToolNet Fplus24h"}'} onChange={e => setProviderForm({ ...providerForm, custom_headers: e.target.value })} /></label><p className={styles.hint}>Headers được mã hóa; GET chỉ trả tên header. Để trống giữ nguyên. Chấp nhận HTTP-Referer, X-Title, OpenAI-Organization/Project, Anthropic-Beta, X-Client-*.</p><label className={styles.check}><input type="checkbox" checked={providerForm.is_active} onChange={e => setProviderForm({ ...providerForm, is_active: e.target.checked })} /> Tôi xác nhận bật Provider này</label><label className={styles.check}><input type="checkbox" checked={providerForm.rotation_authorized} onChange={e => setProviderForm({ ...providerForm, rotation_authorized: e.target.checked })} /> Nhà cung cấp cho phép luân chuyển Keys theo chính sách sử dụng</label><div className={styles.actions}><button className={styles.primary} disabled={busy}>Save</button><button type="button" disabled={busy} onClick={() => void run(async () => { const result = editingProvider && !providerForm.api_key ? await aiAPI<TestResult>(`providers/${editingProvider}/test`, 'POST', {}) : await aiAPI<TestResult>('test-provider', 'POST', { ...providerForm, ...(providerForm.custom_headers.trim() ? { custom_headers: parseHeaders(providerForm.custom_headers) } : { custom_headers: {} }) }); setTestResult(result); }, 'Đã kiểm tra.', false)}>Test Connection</button><button type="button" onClick={() => { setShowProvider(false); setProviderForm({ ...blankProvider }); }}>Hủy</button></div></form></article>}
      {selected && <article className={styles.panel}><div className={styles.sectionTitle}><h3><KeyRound size={19} /> API Keys · {currentProvider?.name}</h3>{providerSelect}</div><p className={styles.hint}>Key không bao giờ hiển thị lại. Lỗi quota/rate limit không làm đổi Key hoặc chuyển Provider.</p><div className={styles.keyList}>{keys.map(key => <div key={key.id}><div><strong>{key.name}</strong><p>{key.is_active ? 'Enabled' : 'Disabled'} · Priority {key.priority} · {key.last_status} · {date(key.last_tested_at)}</p></div><div className={styles.actions}><button type="button" disabled={busy} onClick={() => { setEditingKey(key.id); setKeyForm({ name: key.name, secret: '', priority: key.priority, is_active: key.is_active }); }}>Sửa / Rotate</button><button type="button" disabled={busy} onClick={() => void run(async () => { setTestResult(await aiAPI<TestResult>(`providers/${selected}/keys/${key.id}/test`, 'POST', {})); }, 'Đã kiểm tra Key.')}>Test</button><button type="button" disabled={busy} onClick={() => { if (window.confirm('Thay đổi trạng thái Key? Tuyến đang dùng có thể ngừng hoạt động nếu hết Key.')) void run(() => aiAPI(`providers/${selected}/keys/${key.id}`, 'PATCH', { is_active: !key.is_active })); }}>{key.is_active ? 'Tắt' : 'Bật'}</button><button type="button" disabled={busy} onClick={() => { if (window.confirm(`Xóa Key ${key.name}? Không thể khôi phục Key từ giao diện.`)) void run(() => aiAPI(`providers/${selected}/keys/${key.id}`, 'DELETE')); }}>Xóa</button></div></div>)}</div><form onSubmit={saveKey}><h4>{editingKey ? 'Chỉnh sửa / Rotate Key' : 'Thêm API Key'}</h4><div className={styles.formGrid}><label>Tên Key<input required value={keyForm.name} maxLength={120} onChange={e => setKeyForm({ ...keyForm, name: e.target.value })} /></label><label>{editingKey ? 'Key mới (để trống để giữ)' : 'API Key'}<input type="password" autoComplete="new-password" required={!editingKey} value={keyForm.secret} onChange={e => setKeyForm({ ...keyForm, secret: e.target.value })} /></label><label>Priority<input type="number" required min={1} max={10000} value={keyForm.priority} onChange={e => setKeyForm({ ...keyForm, priority: Number(e.target.value) })} /></label></div><label className={styles.check}><input type="checkbox" checked={keyForm.is_active} onChange={e => setKeyForm({ ...keyForm, is_active: e.target.checked })} /> Enabled</label><div className={styles.actions}><button disabled={busy} className={styles.primary}>{editingKey ? 'Lưu Key' : '+ Thêm Key'}</button>{editingKey && <button type="button" onClick={() => { setEditingKey(null); setKeyForm({ name: '', secret: '', priority: 10, is_active: true }); }}>Hủy</button>}</div></form></article>}
    </>}
    {tab === 1 && <><div className={styles.sectionTitle}><div><h3>Quản lý Models</h3><p>Danh sách và khả năng thực tế theo từng Provider</p></div><div className={styles.actions}><button type="button" disabled={busy || !selected} onClick={() => void run(() => aiAPI(`providers/${selected}/models/sync`, 'POST', {}), 'Đã đồng bộ Models. Cấu hình cũ được giữ nguyên.')}><RefreshCw size={16} />Đồng bộ Models</button><button type="button" disabled={busy || !selected} onClick={() => { setShowModel(true); setEditingModel(null); setModelForm({ ...blankModel }); }}><Plus size={16} /> Thêm Model</button></div></div>{providerSelect}<form className={styles.search} onSubmit={e => { e.preventDefault(); setModelSearch(modelQuery.trim()); setPage(1); setModelLoading(true); setRefresh(v => v + 1); }}><input type="search" placeholder="Tìm Model ID hoặc tên…" value={modelQuery} onChange={e => setModelQuery(e.target.value)} maxLength={150} /><button disabled={busy || !selected}>Tìm kiếm</button></form>
      {modelLoading && selected && <p role="status">Đang tải Models…</p>}
      <div className={styles.cards}>{modelPage?.items.map(model => <article className={styles.modelCard} key={model.id}><div className={styles.providerTop}><FlaskConical size={20} /><h4>{model.display_name || model.model_id}</h4>{currentProvider?.is_default && currentProvider.default_model === model.model_id && <span className={styles.default}>Mặc định</span>}</div><p className={styles.url}>{model.model_id}</p><div className={styles.metrics}><span>{model.is_enabled ? 'Enabled' : 'Disabled'}</span><span>{({ available: 'Khả dụng', unavailable: 'Không khả dụng', untested: 'Chưa kiểm tra' } as Record<string, string>)[model.availability]}</span><span>{model.source}</span></div><p className={styles.hint}>Output tokens: {model.max_output_tokens ?? 'Mặc định của Model'}{model.output_token_limit ? ` / tối đa ${model.output_token_limit}` : ''}</p><div className={styles.actions}><button type="button" disabled={busy} onClick={() => editModel(model)}>Chỉnh sửa</button><button type="button" disabled={busy} onClick={() => { if (!model.is_enabled || window.confirm('Tắt Model này? Các tuyến đang sử dụng có thể ngừng tạo nội dung.')) void run(() => aiAPI(`providers/${selected}/models/${model.id}`, 'PATCH', { is_enabled: !model.is_enabled })); }}>{model.is_enabled ? 'Tắt' : 'Bật'}</button><button type="button" disabled={busy} onClick={() => { setTestModel(model); setTestResult(null); }}>Test Model</button><button type="button" disabled={busy || !model.is_enabled || !currentProvider?.is_active} onClick={() => { if (window.confirm(`Dùng ${model.model_id} làm Model mặc định cho các yêu cầu AI Caption mới?`)) void run(() => aiAPI(`providers/${selected}/models/${model.id}/default`, 'POST', {}), 'Đã chọn Model mặc định và cập nhật tuyến Caption nếu có.'); }}>Set Default</button></div></article>)}</div>
      {!modelLoading && (!modelPage || modelPage.items.length === 0) && <p className={styles.empty}>Chưa có Models phù hợp. Đồng bộ từ API hoặc thêm Model ID thủ công.</p>}{modelPage && <div className={styles.pagination}><button type="button" disabled={busy || page <= 1} onClick={() => { setPage(p => p - 1); setModelLoading(true); }}>Trước</button><span>{modelPage.total} Models · Trang {page}/{modelPage.pages}</span><button type="button" disabled={busy || page >= modelPage.pages} onClick={() => { setPage(p => p + 1); setModelLoading(true); }}>Tiếp</button></div>}
      {showModel && <article className={styles.panel}><h3>{editingModel ? 'Chỉnh sửa Model' : 'Thêm Model thủ công'}</h3><form onSubmit={saveModel}><div className={styles.formGrid}><label>Model ID<input required maxLength={120} value={modelForm.model_id} onChange={e => setModelForm({ ...modelForm, model_id: e.target.value })} /></label><label>Display Name<input maxLength={200} value={modelForm.display_name} onChange={e => setModelForm({ ...modelForm, display_name: e.target.value })} /></label>{(['temperature', 'top_p'] as const).map(parameter => <div key={parameter}><label>Hỗ trợ {parameter}<select value={modelForm[`supports_${parameter}`]} onChange={e => setModelForm({ ...modelForm, [`supports_${parameter}`]: e.target.value })}><option value="">Chưa xác định</option><option value="true">Có hỗ trợ</option><option value="false">Không hỗ trợ</option></select></label><label>{parameter}<input type="number" min={0} max={parameter === 'temperature' ? 2 : 1} step="any" value={modelForm[parameter]} disabled={modelForm[`supports_${parameter}`] !== 'true'} onChange={e => setModelForm({ ...modelForm, [parameter]: e.target.value })} /></label></div>)}<label>Max Output Tokens<input type="number" min={1} max={10000000} value={modelForm.max_output_tokens} placeholder={currentProvider?.provider_type === 'anthropic' ? 'Bắt buộc với Anthropic' : 'Để trống dùng mặc định Provider'} onChange={e => setModelForm({ ...modelForm, max_output_tokens: e.target.value })} /></label><label>Trường token của OpenAI-compatible<select value={modelForm.token_parameter} onChange={e => setModelForm({ ...modelForm, token_parameter: e.target.value })}><option>max_tokens</option><option>max_completion_tokens</option></select></label><label>Request Timeout<input required type="number" min={1} max={120} value={modelForm.request_timeout} onChange={e => setModelForm({ ...modelForm, request_timeout: Number(e.target.value) })} /></label><label>Retry lỗi HTTP tạm thời (500/502/503)<input required type="number" min={0} max={2} value={modelForm.retry_count} onChange={e => setModelForm({ ...modelForm, retry_count: Number(e.target.value) })} /></label></div><label className={styles.check}><input type="checkbox" checked={modelForm.is_enabled} onChange={e => setModelForm({ ...modelForm, is_enabled: e.target.checked })} /> Enabled</label><p className={styles.hint}>Không gửi Temperature/Top P khi chưa xác định hỗ trợ. Retry không đổi Key, không áp dụng với quota/auth hoặc timeout không rõ kết quả.</p><div className={styles.actions}><button disabled={busy} className={styles.primary}>Lưu cấu hình Model</button><button type="button" onClick={() => setShowModel(false)}>Hủy</button></div></form></article>}
      {testModel && <article className={styles.panel}><h3>Test Model · {testModel.model_id}</h3><form onSubmit={e => { e.preventDefault(); void run(async () => { setTestResult(await aiAPI<TestResult>(`providers/${selected}/models/${testModel.id}/test`, 'POST', { prompt: testPrompt })); }, 'Đã hoàn tất kiểm tra Model.'); }}><label>Prompt kiểm thử<textarea rows={3} required maxLength={2000} value={testPrompt} onChange={e => setTestPrompt(e.target.value)} /></label><p className={styles.hint}>Prompt và response chỉ hiển thị trong phiên này, không ghi vào audit log.</p><button disabled={busy} className={styles.primary}>Gọi Model thực tế</button></form></article>}
    </>}
    {tab === 2 && <><div className={styles.sectionTitle}><div><h3>Định tuyến AI theo tác vụ</h3><p>Primary → Fallback có điều kiện</p></div><Workflow size={25} /></div><label>Tác vụ<select value={task} onChange={e => { if (!routeDirty || window.confirm('Bỏ các thay đổi tuyến chưa lưu?')) chooseTask(e.target.value); }}>{catalog?.tasks.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}{routes.filter(r => !catalog?.tasks.some(t => t.id === r.task)).map(r => <option key={r.task}>{r.task}</option>)}</select></label><button type="button" onClick={loadRoute} disabled={busy}>Tải cấu hình tuyến đã lưu</button><p className={styles.hint}>Phiên bản {routeVersion || 'chưa lưu'} · Khi chưa có tuyến được bật, AI Caption dùng Provider/Model mặc định đã chọn; nếu chưa chọn thì dùng legacy production. Caption Review chỉ được gọi khi tác vụ sử dụng tuyến này; không tự duyệt Caption.</p><form onSubmit={saveRoute} onChange={() => setRouteDirty(true)}><article className={styles.primaryRoute}><h4>Primary Provider / Model</h4><div className={styles.formGrid}><ModelPicker providers={providers} provider={primary.provider} model={primary.model} modelName={primary.model_name} onProvider={value => { setPrimary({ ...primary, provider: value, model: '' }); setRouteDirty(true); }} onModel={value => { setPrimary({ ...primary, model: value }); setRouteDirty(true); }} /><label>API Key selection policy<select value={primary.key_policy} onChange={e => setPrimary({ ...primary, key_policy: e.target.value })}><option value="priority">Priority · Key đầu tiên đang bật</option><option value="round_robin">Round robin · Được Provider cho phép</option></select></label></div></article>{fallbacks.map((step, index) => <div key={index}><div className={styles.arrow}><ArrowDown size={22} /></div><article className={styles.fallback}><div className={styles.sectionTitle}><h4>Fallback {index + 1}</h4><div className={styles.actions}><button type="button" disabled={index === 0} onClick={() => { const next = [...fallbacks]; [next[index - 1], next[index]] = [next[index], next[index - 1]]; setFallbacks(next); setRouteDirty(true); }}>Lên</button><button type="button" onClick={() => { setFallbacks(fallbacks.filter((_, i) => i !== index)); setRouteDirty(true); }}>Bỏ</button></div></div><div className={styles.formGrid}><ModelPicker providers={providers} provider={step.provider} model={step.model} modelName={step.model_name} onProvider={value => { setFallbacks(fallbacks.map((s, i) => i === index ? { ...s, provider: value, model: '' } : s)); setRouteDirty(true); }} onModel={value => { setFallbacks(fallbacks.map((s, i) => i === index ? { ...s, model: value } : s)); setRouteDirty(true); }} /><label>Timeout<input required type="number" min={1} max={120} value={step.timeout} onChange={e => setFallbacks(fallbacks.map((s, i) => i === index ? { ...s, timeout: Number(e.target.value) } : s))} /></label><label>Retry<input required type="number" min={0} max={2} value={step.retries} onChange={e => setFallbacks(fallbacks.map((s, i) => i === index ? { ...s, retries: Number(e.target.value) } : s))} /></label><label>Key policy<select value={step.key_policy} onChange={e => setFallbacks(fallbacks.map((s, i) => i === index ? { ...s, key_policy: e.target.value } : s))}><option value="priority">Priority</option><option value="round_robin">Round robin được cho phép</option></select></label></div></article></div>)}<button type="button" disabled={fallbacks.length >= 8 || busy} onClick={() => { setFallbacks([...fallbacks, blankStep()]); setRouteDirty(true); }}><Plus size={16} /> Thêm Fallback</button><label className={styles.check}><input type="checkbox" checked={routeEnabled} onChange={e => setRouteEnabled(e.target.checked)} /> Tôi xác nhận bật tuyến này cho các yêu cầu AI mới</label><p className={styles.hint}>Không fallback khi lỗi input, authentication, permission, TLS hoặc quota/rate limit. Caption Engine vẫn giữ generation token, CAS commit và khóa destination theo Pipeline.</p><button disabled={busy} className={styles.primary}>Save Routing</button></form><article className={styles.panel}><h4>Kiểm tra tuyến đã lưu</h4><form onSubmit={e => { e.preventDefault(); void run(async () => { setTestResult(await aiAPI<TestResult>(`routes/${task}/test`, 'POST', { prompt: testPrompt })); }, 'Đã gọi runtime theo tuyến đã lưu.', false); }}><label>Prompt<textarea maxLength={2000} required rows={3} value={testPrompt} onChange={e => setTestPrompt(e.target.value)} /></label><button type="submit" disabled={busy || routeDirty}>Test Routing</button></form><p className={styles.hint}>Dùng cùng router với Caption Engine; không tạo Caption/Publishing Job và không sửa dữ liệu Pipeline.</p></article></>}
    {testResult && <TestOutput value={testResult} />}
    <footer className={styles.footer}><ShieldCheck size={16} /> Secrets được mã hóa · Thay đổi cấu hình có audit log <ChevronRight size={14} /></footer>
  </section>;
}
