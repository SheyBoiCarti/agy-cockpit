import { useEffect, useRef, useState } from 'react';
import { useCockpitStore } from '../store/useCockpitStore';
import { wsService, CouncilAction } from '../services/websocket';
import { MarkdownView } from './MarkdownView';

interface Member { id: string; name: string; title: string; focus: string; icon: string }
export function CouncilPanel() {
  const [roster, setRoster] = useState<{ members: Member[]; chair: Member } | null>(null);
  const [error, setError] = useState('');
  const [action, setAction] = useState<CouncilAction | null>(null);
  const [question, setQuestion] = useState('');
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const activeId = useCockpitStore(s => s.activeConversationId);
  const model = useCockpitStore(s => s.conversations[s.activeConversationId || '']?.model_slug);
  const busy = useCockpitStore(s => Boolean(s.activeRunId || s.pendingSubmissions[s.activeConversationId || '']));
  const modelReady = useCockpitStore(s => s.modelCatalogStatus === 'ready' && s.models.some(m => m.slug === model));
  const progress = useCockpitStore(s => s.councilProgress);
  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/council', { signal: controller.signal, headers: { 'x-antigravity-token': localStorage.getItem('agy_token') || '' } })
      .then(async r => { if (!r.ok) throw new Error('Could not load Council roster'); setRoster(await r.json()); })
      .catch(e => { if (e.name !== 'AbortError') setError(String(e)); });
    return () => controller.abort();
  }, []);
  useEffect(() => { if (action) { dialog.current?.showModal(); input.current?.focus(); } else dialog.current?.close(); }, [action]);
  useEffect(() => { setAction(null); setQuestion(''); }, [activeId]);
  const open = (value: CouncilAction) => { setQuestion(''); setAction(value); };
  const disabled = busy || !activeId || !modelReady || !roster;
  return <div className="flex-1 min-h-0 p-4 overflow-y-auto space-y-4 text-sm">
    <h3 className="font-semibold">AI Council</h3>
    <p>Independent analysis, peer critique, then synthesis. Members use the selected conversation model and tool policy.</p>
    {error && <p role="alert">{error}</p>}
    <div className="flex flex-wrap gap-2">
      <button className="p-2 border rounded disabled:opacity-40" disabled={disabled} onClick={() => open({ kind: 'deliberate' })}>Deliberate</button>
      <button className="p-2 border rounded disabled:opacity-40" disabled={disabled} onClick={() => open({ kind: 'vote' })}>Roll-Call Vote</button>
    </div>
    {roster && <><h4>{roster.members.length} Council members + 1 synthesis chair</h4>
      {[...roster.members, roster.chair].map(m => <div key={m.id} className="p-3 border rounded space-y-2">
        <p>{m.icon} <strong>{m.name}</strong> — {m.title}{m.id === roster.chair.id ? ' (Chair; does not vote)' : ''}</p>
        <p className="text-xs text-neutral-400">{m.focus}</p>
        <button aria-label={`Ask ${m.name}`} disabled={disabled} onClick={() => open({ kind: 'ask', member_id: m.id })}>Ask</button>
      </div>)}
    </>}
    <div aria-live="polite">{Object.entries(progress).filter(([, p]) => p.conversationId === activeId).map(([id, p]) => <section key={id} className="border rounded p-3 my-2">
      <h4>{p.stage} · {p.memberId} · {p.state}</h4><MarkdownView content={p.text} />
    </section>)}</div>
    <dialog ref={dialog} aria-label="Council question" className="bg-neutral-900 text-neutral-100 p-5 rounded-xl border border-neutral-700 w-[min(32rem,calc(100vw-2rem))] backdrop:bg-black/75"
      onCancel={e => { e.preventDefault(); setAction(null); }} onKeyDown={e => e.stopPropagation()}>
      <form className="space-y-4" onSubmit={e => { e.preventDefault(); if (action && question.trim() && wsService.sendPrompt(question.trim(), [], model, action)) setAction(null); }}>
        <label className="block">{action?.kind === 'ask' ? 'Question for Council member' : action?.kind === 'vote' ? 'Voting motion' : 'Deliberation topic'}
          <textarea ref={input} aria-label="Council question or topic" className="block border rounded p-2 w-full mt-2" value={question} onChange={e => setQuestion(e.target.value)} rows={4} />
        </label>
        <div className="flex justify-end gap-4"><button type="button" onClick={() => setAction(null)}>Cancel</button><button type="submit" disabled={!question.trim() || disabled}>Start Council</button></div>
      </form>
    </dialog>
  </div>;
}
