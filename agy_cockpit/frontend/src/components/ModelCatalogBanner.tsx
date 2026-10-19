import { useCockpitStore } from '../store/useCockpitStore';
import { refreshModels } from '../services/models';

export function ModelCatalogBanner() {
  const status = useCockpitStore(s => s.modelCatalogStatus);
  const error = useCockpitStore(s => s.modelCatalogError);
  return <div className="shrink-0 flex flex-wrap items-center justify-between gap-2 px-4 py-1 text-xs text-neutral-400">
    <span role={error ? 'alert' : 'status'}>{status === 'loading' ? 'Discovering account models…' : status === 'ready' ? 'Account models up to date' : `${status === 'stale' ? 'Cached models are stale. ' : ''}${error || 'Account models unavailable.'}`}</span>
    <button disabled={status === 'loading'} onClick={() => void refreshModels(true)}>Refresh models</button>
  </div>;
}
