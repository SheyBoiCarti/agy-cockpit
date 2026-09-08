import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useCockpitStore } from '../store/useCockpitStore';
import { wsService } from '../services/websocket';
import { DiffEditor } from '@monaco-editor/react';
import Convert from 'ansi-to-html';
import { MarkdownView } from './MarkdownView';
import { Artifact } from '../types/models';
import {
  X,
  FileDiff,
  Terminal,
  Boxes,
  Layers,
  FileText,
  Eye,
  Loader2,
  AlertTriangle,
  Scissors,
} from 'lucide-react';

const ansiConverter = new Convert({
  fg: '#e5e5e5',
  bg: '#0a0a0a',
  stream: true,
  escapeXML: true,
});

export const RightDrawer: React.FC = () => {
  const activeDrawerTab = useCockpitStore((s) => s.activeDrawerTab);
  const setActiveDrawerTab = useCockpitStore((s) => s.setActiveDrawerTab);

  const changedFilesMap = useCockpitStore((s) => s.changedFiles);
  const selectedDiffFile = useCockpitStore((s) => s.selectedDiffFile);
  const diffData = useCockpitStore((s) => s.diffData);
  const toolLogs = useCockpitStore((s) => s.toolLogs);
  const subagentsMap = useCockpitStore((s) => s.subagents);
  const artifactsMap = useCockpitStore((s) => s.artifacts);

  const changedFiles = useMemo(() => Object.values(changedFilesMap), [changedFilesMap]);
  const subagents = useMemo(() => Object.values(subagentsMap), [subagentsMap]);
  const artifacts = useMemo(() => Object.values(artifactsMap), [artifactsMap]);

  const [selectedToolId, setSelectedToolId] = useState<string | null>(null);
  const [previewArtifact, setPreviewArtifact] = useState<Artifact | null>(null);
  const [artifactContent, setArtifactContent] = useState<string | null>(null);
  const [isLoadingArtifact, setIsLoadingArtifact] = useState(false);
  const [htmlViewMode, setHtmlViewMode] = useState<'preview' | 'source'>('preview');
  const [autoScroll, setAutoScroll] = useState(true);
  const terminalEndRef = useRef<HTMLDivElement>(null);

  // Default to first tool with logs if not selected
  useEffect(() => {
    const toolIdsWithLogs = Object.keys(toolLogs);
    if (!selectedToolId && toolIdsWithLogs.length > 0) {
      setSelectedToolId(toolIdsWithLogs[toolIdsWithLogs.length - 1]);
    }
  }, [toolLogs, selectedToolId]);

  // Auto-scroll terminal to bottom
  useEffect(() => {
    if (activeDrawerTab === 'terminal' && autoScroll && terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [toolLogs, selectedToolId, activeDrawerTab, autoScroll]);

  if (!activeDrawerTab) return null;

  const handleSelectFileDiff = (path: string) => {
    wsService.requestFileDiff(path);
  };

  const handleSelectArtifact = async (art: Artifact) => {
    setPreviewArtifact(art);
    if (art.mime_type.startsWith('image/')) {
      setArtifactContent(null);
      return;
    }
    setIsLoadingArtifact(true);
    try {
      const token = (typeof window !== 'undefined' && localStorage.getItem('agy_token')) || '';
      const res = await fetch(`/api/artifacts/${art.id}/content?token=${encodeURIComponent(token)}`, {
        headers: token ? { 'x-antigravity-token': token } : {},
      });
      if (res.ok) {
        const text = await res.text();
        setArtifactContent(text);
      } else {
        setArtifactContent(`Failed to load artifact content (${res.statusText})`);
      }
    } catch (e: any) {
      setArtifactContent(`Error loading artifact: ${e?.message || String(e)}`);
    } finally {
      setIsLoadingArtifact(false);
    }
  };

  return (
    <aside className="w-96 md:w-[480px] lg:w-[560px] border-l border-neutral-800 bg-neutral-950 flex flex-col h-full z-20 shadow-2xl transition-all select-none">
      {/* Drawer Header with Tabs */}
      <div className="h-14 border-b border-neutral-800 bg-neutral-900/60 px-4 flex items-center justify-between">
        <div className="flex items-center space-x-1">
          <button
            onClick={() => setActiveDrawerTab('diffs')}
            className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              activeDrawerTab === 'diffs'
                ? 'bg-neutral-800 text-indigo-300'
                : 'text-neutral-400 hover:text-neutral-200'
            }`}
          >
            <FileDiff className="w-3.5 h-3.5" />
            <span>Diffs ({changedFiles.length})</span>
          </button>

          <button
            onClick={() => setActiveDrawerTab('terminal')}
            className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              activeDrawerTab === 'terminal'
                ? 'bg-neutral-800 text-indigo-300'
                : 'text-neutral-400 hover:text-neutral-200'
            }`}
          >
            <Terminal className="w-3.5 h-3.5" />
            <span>Terminal</span>
          </button>

          <button
            onClick={() => setActiveDrawerTab('subagents')}
            className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              activeDrawerTab === 'subagents'
                ? 'bg-neutral-800 text-indigo-300'
                : 'text-neutral-400 hover:text-neutral-200'
            }`}
          >
            <Boxes className="w-3.5 h-3.5" />
            <span>Subagents ({subagents.length})</span>
          </button>

          <button
            onClick={() => setActiveDrawerTab('artifacts')}
            className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              activeDrawerTab === 'artifacts'
                ? 'bg-neutral-800 text-indigo-300'
                : 'text-neutral-400 hover:text-neutral-200'
            }`}
          >
            <Layers className="w-3.5 h-3.5" />
            <span>Artifacts ({artifacts.length})</span>
          </button>
        </div>

        <button
          onClick={() => setActiveDrawerTab(null)}
          className="p-1.5 text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800 rounded-lg transition-colors"
          title="Close panel"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Drawer Content */}
      <div className="flex-1 overflow-hidden flex flex-col">
        {/* DIFFS TAB */}
        {activeDrawerTab === 'diffs' && (
          <div className="flex-1 flex flex-col overflow-hidden">
            {/* Changed Files Sub-header */}
            <div className="p-3 border-b border-neutral-800 bg-neutral-900/30 overflow-x-auto flex items-center space-x-2">
              {changedFiles.length === 0 ? (
                <span className="text-xs text-neutral-400">No files modified in active run</span>
              ) : (
                changedFiles.map((file) => (
                  <button
                    key={file.path}
                    onClick={() => handleSelectFileDiff(file.path)}
                    className={`flex items-center space-x-1.5 px-2.5 py-1 rounded-lg text-xs font-mono shrink-0 transition-colors ${
                      selectedDiffFile === file.path
                        ? 'bg-indigo-600/30 text-indigo-200 border border-indigo-500/40'
                        : 'bg-neutral-900 text-neutral-300 hover:bg-neutral-800 border border-neutral-800'
                    }`}
                  >
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${
                        file.status === 'added'
                          ? 'bg-emerald-400'
                          : file.status === 'deleted'
                          ? 'bg-rose-400'
                          : 'bg-amber-400'
                      }`}
                    />
                    <span className="truncate max-w-xs">{file.path}</span>
                  </button>
                ))
              )}
            </div>

            {/* Monaco Diff Viewer */}
            <div className="flex-1 bg-neutral-950 flex flex-col">
              {selectedDiffFile && diffData ? (
                <>
                  {/* Binary file warning */}
                  {diffData.is_binary && (
                    <div className="flex items-center space-x-2 px-4 py-2.5 bg-amber-950/40 border-b border-amber-800/40 text-amber-300 text-xs">
                      <AlertTriangle className="w-4 h-4 shrink-0" />
                      <span className="font-medium">Binary file</span>
                      <span className="text-amber-200/70">— Content diff is not available for binary files.</span>
                    </div>
                  )}
                  {/* Truncated diff warning */}
                  {diffData.truncated && (
                    <div className="flex items-center space-x-2 px-4 py-2.5 bg-blue-950/40 border-b border-blue-800/40 text-blue-300 text-xs">
                      <Scissors className="w-4 h-4 shrink-0" />
                      <span className="font-medium">Diff truncated</span>
                      <span className="text-blue-200/70">— File is too large; only a portion is shown.</span>
                    </div>
                  )}
                  <div className="flex-1">
                    <DiffEditor
                      height="100%"
                      language={diffData.language || 'typescript'}
                      original={diffData.original}
                      modified={diffData.modified}
                      theme="vs-dark"
                      options={{
                        readOnly: true,
                        renderSideBySide: true,
                        minimap: { enabled: false },
                        scrollBeyondLastLine: false,
                        fontSize: 12,
                      }}
                    />
                  </div>
                </>
              ) : (
                <div className="h-full flex flex-col items-center justify-center text-neutral-400 text-xs p-8 text-center">
                  <FileDiff className="w-8 h-8 mb-2 opacity-50" />
                  <span>Select a modified file above to view side-by-side diff.</span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* TERMINAL TAB */}
        {activeDrawerTab === 'terminal' && (
          <div className="flex-1 flex flex-col overflow-hidden bg-neutral-950 font-mono">
            {/* Terminal toolbar */}
            <div className="p-2 border-b border-neutral-800 bg-neutral-900/40 flex items-center justify-between text-xs">
              <div className="flex items-center space-x-2 overflow-x-auto">
                {Object.keys(toolLogs).length > 1 ? (
                  Object.keys(toolLogs).map((id) => (
                    <button
                      key={id}
                      onClick={() => setSelectedToolId(id)}
                      className={`px-2 py-1 rounded cursor-pointer ${
                        selectedToolId === id ? 'bg-indigo-600 text-white' : 'bg-neutral-800 text-neutral-300'
                      }`}
                    >
                      Tool {id.slice(0, 8)}
                    </button>
                  ))
                ) : selectedToolId ? (
                  <span className="text-neutral-400 font-mono text-[11px] px-1">
                    Tool {selectedToolId.slice(0, 8)}
                  </span>
                ) : (
                  <span className="text-neutral-400 font-mono text-[11px] px-1">
                    Console Logs
                  </span>
                )}
              </div>
              <button
                onClick={() => setAutoScroll((prev) => !prev)}
                className={`px-2.5 py-1 rounded text-[11px] font-medium transition-colors flex items-center space-x-1.5 shrink-0 cursor-pointer ${
                  autoScroll
                    ? 'bg-emerald-950/60 text-emerald-400 border border-emerald-800/60'
                    : 'bg-neutral-800 text-neutral-400 border border-neutral-700'
                }`}
                title={autoScroll ? 'Pause auto-scroll' : 'Resume auto-scroll'}
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    autoScroll ? 'bg-emerald-400 animate-pulse' : 'bg-neutral-500'
                  }`}
                />
                <span>Auto-scroll: {autoScroll ? 'ON' : 'PAUSED'}</span>
              </button>
            </div>

            {/* Terminal output box */}
            <div className="flex-1 p-4 overflow-y-auto text-xs space-y-1 select-text">
              {(!selectedToolId || !toolLogs[selectedToolId] || toolLogs[selectedToolId].length === 0) ? (
                <div className="text-neutral-400 text-center py-12">
                  No active command logs available.
                </div>
              ) : (
                toolLogs[selectedToolId].map((entry, idx) => {
                  const text = typeof entry === 'string' ? entry : entry.chunk;
                  const isStderr = typeof entry === 'object' && entry.is_stderr;
                  return (
                    <div
                      key={idx}
                      className={`leading-relaxed break-all ${
                        isStderr ? 'text-rose-400 font-medium' : 'text-neutral-300'
                      }`}
                      dangerouslySetInnerHTML={{
                        __html: ansiConverter.toHtml(text),
                      }}
                    />
                  );
                })
              )}
              <div ref={terminalEndRef} />
            </div>
          </div>
        )}

        {/* SUBAGENTS TAB */}
        {activeDrawerTab === 'subagents' && (
          <div className="flex-1 p-4 overflow-y-auto space-y-3 bg-neutral-950">
            {subagents.length === 0 ? (
              <div className="text-center py-16 text-neutral-400 text-xs">
                <Boxes className="w-8 h-8 mx-auto mb-2 opacity-40" />
                <span>No subagents spawned in this run.</span>
              </div>
            ) : (
              subagents.map((sa) => (
                <div
                  key={sa.id}
                  style={{ marginLeft: `${(sa.depth || 0) * 16}px` }}
                  className="p-3 bg-neutral-900 border border-neutral-800 rounded-xl space-y-2 text-xs"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-2 font-medium text-neutral-200">
                      <Boxes className="w-4 h-4 text-indigo-400" />
                      <span>{sa.name_or_role}</span>
                    </div>
                    <span
                      className={`px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase ${
                        sa.state === 'running'
                          ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                          : sa.state === 'completed'
                          ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                          : 'bg-neutral-800 text-neutral-400'
                      }`}
                    >
                      {sa.state}
                    </span>
                  </div>

                  {sa.current_activity && (
                    <div className="text-neutral-400 text-[11px] font-mono">
                      {sa.current_activity}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        )}

        {/* ARTIFACTS TAB */}
        {activeDrawerTab === 'artifacts' && (
          <div className="flex-1 flex flex-col min-h-0 bg-neutral-950">
            {previewArtifact ? (
              <div className="flex-1 flex flex-col min-h-0">
                {/* Preview Header */}
                <div className="p-3 border-b border-neutral-800 bg-neutral-900/80 flex items-center justify-between">
                  <div className="flex items-center space-x-2 truncate">
                    <FileText className="w-4 h-4 text-amber-400 shrink-0" />
                    <span className="text-xs font-semibold text-neutral-200 truncate font-mono">
                      {previewArtifact.name}
                    </span>
                    <span className="text-[10px] font-mono px-1.5 py-0.5 bg-neutral-800 text-neutral-400 rounded">
                      {previewArtifact.kind}
                    </span>
                  </div>
                  <div className="flex items-center space-x-2">
                    {(previewArtifact.mime_type === 'text/html' ||
                      previewArtifact.name.endsWith('.html') ||
                      previewArtifact.name.endsWith('.htm')) && (
                      <div className="flex rounded bg-neutral-800 p-0.5 text-[11px]">
                        <button
                          onClick={() => setHtmlViewMode('preview')}
                          className={`px-2 py-0.5 rounded transition-colors ${
                            htmlViewMode === 'preview'
                              ? 'bg-indigo-600 text-white'
                              : 'text-neutral-400 hover:text-neutral-200'
                          }`}
                        >
                          Preview
                        </button>
                        <button
                          onClick={() => setHtmlViewMode('source')}
                          className={`px-2 py-0.5 rounded transition-colors ${
                            htmlViewMode === 'source'
                              ? 'bg-indigo-600 text-white'
                              : 'text-neutral-400 hover:text-neutral-200'
                          }`}
                        >
                          Source
                        </button>
                      </div>
                    )}
                    <button
                      onClick={() => setPreviewArtifact(null)}
                      className="p-1 text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800 rounded transition-colors"
                      title="Close preview"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {/* Preview Body */}
                <div className="flex-1 p-4 overflow-y-auto text-xs select-text">
                  {previewArtifact.mime_type.startsWith('image/') ? (
                    <div className="flex items-center justify-center p-4">
                      <img
                        src={`/api/artifacts/${previewArtifact.id}/content?token=${encodeURIComponent(
                          (typeof window !== 'undefined' && localStorage.getItem('agy_token')) || ''
                        )}`}
                        alt={previewArtifact.name}
                        className="max-h-[70vh] rounded-lg border border-neutral-800 object-contain shadow-lg"
                      />
                    </div>
                  ) : isLoadingArtifact ? (
                    <div className="flex items-center justify-center py-16 text-neutral-400 space-x-2">
                      <Loader2 className="w-4 h-4 animate-spin text-indigo-400" />
                      <span>Loading artifact content...</span>
                    </div>
                  ) : artifactContent !== null ? (
                    previewArtifact.mime_type === 'text/markdown' || previewArtifact.name.endsWith('.md') ? (
                      <MarkdownView content={artifactContent} />
                    ) : (previewArtifact.mime_type === 'text/html' ||
                        previewArtifact.name.endsWith('.html') ||
                        previewArtifact.name.endsWith('.htm')) ? (
                      htmlViewMode === 'preview' ? (
                        <div className="w-full h-full min-h-[500px] rounded border border-neutral-800 bg-white overflow-hidden shadow">
                          <iframe
                            sandbox="allow-scripts"
                            srcDoc={artifactContent}
                            className="w-full h-full min-h-[500px] border-0"
                            title={previewArtifact.name}
                          />
                        </div>
                      ) : (
                        <pre className="p-3 rounded bg-neutral-900 border border-neutral-800 font-mono text-neutral-300 text-xs overflow-x-auto whitespace-pre-wrap">
                          {artifactContent}
                        </pre>
                      )
                    ) : (
                      <pre className="p-3 rounded bg-neutral-900 border border-neutral-800 font-mono text-neutral-300 text-xs overflow-x-auto whitespace-pre-wrap">
                        {artifactContent}
                      </pre>
                    )
                  ) : null}
                </div>
              </div>
            ) : (
              <div className="flex-1 p-4 overflow-y-auto space-y-3">
                {artifacts.length === 0 ? (
                  <div className="text-center py-16 text-neutral-400 text-xs">
                    <Layers className="w-8 h-8 mx-auto mb-2 opacity-40" />
                    <span>No artifacts generated yet.</span>
                  </div>
                ) : (
                  artifacts.map((art) => (
                    <div
                      key={art.id}
                      onClick={() => handleSelectArtifact(art)}
                      className="p-3 bg-neutral-900 border border-neutral-800 hover:border-neutral-700 hover:bg-neutral-850 cursor-pointer rounded-xl space-y-1.5 text-xs transition-all group"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center space-x-2 font-medium text-neutral-200 truncate">
                          <FileText className="w-4 h-4 text-amber-400 shrink-0 group-hover:text-amber-300" />
                          <span className="truncate font-mono">{art.name}</span>
                        </div>
                        <div className="flex items-center space-x-1.5">
                          <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 bg-neutral-800 text-neutral-400 rounded">
                            {art.kind}
                          </span>
                          <Eye className="w-3.5 h-3.5 text-neutral-500 group-hover:text-neutral-300" />
                        </div>
                      </div>
                      <div className="text-[11px] text-neutral-400 font-mono flex items-center justify-between">
                        <span>{art.mime_type}</span>
                        {art.size_bytes ? <span>{Math.round(art.size_bytes / 1024)} KB</span> : null}
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
};
