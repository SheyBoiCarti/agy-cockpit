import { useEffect, useRef } from 'react';

/** Focus and background isolation apply only while a responsive panel overlays chat. */
export function usePanelFocus(open: boolean, query: string, close: () => void) {
  const ref = useRef<HTMLElement>(null);
  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    if (!open) return;
    const media = matchMedia(query);
    let cleanup = () => {};
    const update = () => {
      cleanup();
      if (!media.matches || !ref.current) return;
      const panel = ref.current;
      const previous = document.activeElement as HTMLElement | null;
      const backgrounds = [...document.querySelectorAll<HTMLElement>('main, aside')].filter(e => e !== panel && !e.contains(panel));
      const prior = backgrounds.map(e => e.inert);
      backgrounds.forEach(e => { e.inert = true; });
      const focusable = () => [...panel.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]')].filter(e => e.getClientRects().length);
      (focusable()[0] || panel).focus();
      const key = (event: KeyboardEvent) => {
        if (event.key === 'Escape') { event.preventDefault(); closeRef.current(); }
        if (event.key === 'Tab') {
          const items = focusable(), first = items[0], last = items[items.length - 1];
          if (!first) { event.preventDefault(); return; }
          if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
          else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
        }
      };
      panel.addEventListener('keydown', key);
      cleanup = () => { panel.removeEventListener('keydown', key); backgrounds.forEach((e, i) => { e.inert = prior[i]; }); previous?.focus(); };
    };
    update(); media.addEventListener('change', update);
    return () => { cleanup(); media.removeEventListener('change', update); };
  }, [open, query]);
  return ref;
}
