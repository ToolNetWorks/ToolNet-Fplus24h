'use client';
import { useEffect, useState } from 'react';
import { aiAPI, ModelPage, Provider } from './api';

export default function ModelPicker({ providers, provider, model, modelName, onProvider, onModel }: { providers: Provider[]; provider: string; model: string; modelName?: string; onProvider: (value: string) => void; onModel: (value: string) => void }) {
  const [models, setModels] = useState<ModelPage | null>(null);
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    if (!provider) return;
    const controller = new AbortController();
    // Search is passed through the URL separately to keep path slashes canonical.
    void aiAPI<ModelPage>(`providers/${provider}/models?page_size=100&q=${encodeURIComponent(query)}`, 'GET', undefined, controller.signal)
      .then(value => { if (!controller.signal.aborted) { setModels(value); setError(''); } })
      .catch(() => { if (!controller.signal.aborted) setError('Không tải được Models.'); });
    return () => controller.abort();
  }, [provider, query]);
  return <><label>Provider<select required value={provider} onChange={event => { setModels(null); setQuery(''); onProvider(event.target.value); }}><option value="">Chọn Provider</option>{providers.map(p => <option key={p.id} value={p.id}>{p.name}{!p.is_active ? ' (Disabled)' : ''}</option>)}</select></label>
    <label>Tìm Model<input type="search" placeholder="Nhập Model ID hoặc tên…" value={query} onChange={event => setQuery(event.target.value)} disabled={!provider} /></label>
    <label>Model<select required value={model} onChange={event => onModel(event.target.value)} disabled={!provider}><option value="">Chọn Model</option>{model && !models?.items.some(m => m.id === model) && <option value={model}>{modelName || 'Model đã chọn'}</option>}{models?.items.map(m => <option key={m.id} value={m.id}>{m.display_name || m.model_id} · {m.model_id}{!m.is_enabled ? ' (Disabled)' : ''}</option>)}</select></label>{models && models.total > 100 && <p>Đang hiển thị 100 kết quả đầu; nhập tên để tìm Model cần dùng.</p>}{error && <p role="alert">{error}</p>}</>;
}
