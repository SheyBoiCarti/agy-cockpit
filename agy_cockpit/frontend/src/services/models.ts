import { useCockpitStore } from '../store/useCockpitStore';

let loading: Promise<void> | null = null;
export function refreshModels(force = false): Promise<void> {
  if (loading) return loading;
  const store = useCockpitStore.getState();
  store.setModelCatalogStatus('loading');
  loading = (async () => {
    try {
      const token = localStorage.getItem('agy_token') || '';
      const response = await fetch(`/api/models${force ? '?refresh=true' : ''}`, { headers: { 'x-antigravity-token': token } });
      if (!response.ok) throw new Error(`Model discovery failed (${response.status})`);
      const result = await response.json();
      store.setModels(result.models || []);
      store.setModelCatalogStatus(result.status || 'ready', result.error || null);
    } catch (error) {
      store.setModelCatalogStatus('unavailable', String(error));
    } finally { loading = null; }
  })();
  return loading;
}
