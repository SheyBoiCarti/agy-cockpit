import { useCockpitStore } from '../store/useCockpitStore';

export function NoticeBanner() {
  const notices = useCockpitStore(s => s.notices);
  const dismiss = useCockpitStore(s => s.dismissNotice);
  return <div className="shrink-0 space-y-1">{notices.map(n => <div key={n.id} role="alert" className="flex items-start gap-2 bg-rose-950 border border-rose-700 p-3 text-sm text-rose-100 break-words">
    <span className="min-w-0 flex-1">{n.conversationId ? 'Conversation action failed: ' : ''}{n.message}</span>
    <button aria-label="Dismiss error" onClick={() => dismiss(n.id)}>×</button>
  </div>)}</div>;
}
