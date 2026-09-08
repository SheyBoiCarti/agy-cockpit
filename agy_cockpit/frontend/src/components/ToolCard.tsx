import React, { useState } from 'react';
import { ToolExecution } from '../types/models';
import { useCockpitStore } from '../store/useCockpitStore';
import { wsService } from '../services/websocket';
import {
  Terminal,
  FileCode,
  CheckCircle2,
  XCircle,
  Loader2,
  ChevronDown,
  ChevronRight,
  ExternalLink,
} from 'lucide-react';

interface ToolCardProps {
  tool: ToolExecution;
}

export const ToolCard: React.FC<ToolCardProps> = ({ tool }) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const setActiveDrawerTab = useCockpitStore((s) => s.setActiveDrawerTab);

  const isRunning = tool.state === 'started';
  const isSuccess = tool.state === 'completed' && tool.success;
  const isFailed = tool.state === 'failed' || (tool.state === 'completed' && !tool.success);

  const isCommand = tool.sdk_tool_name === 'run_command';
  const isFileEdit = tool.sdk_tool_name === 'create_file' || tool.sdk_tool_name === 'edit_file';

  const handleOpenDrawer = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (isCommand) {
      setActiveDrawerTab('terminal');
    } else if (isFileEdit) {
      const path = (tool.args.target_path || tool.args.file_path || tool.args.path) as string;
      if (path) {
        wsService.requestFileDiff(path);
      }
      setActiveDrawerTab('diffs');
    }
  };

  return (
    <div className="my-2 rounded-lg border border-neutral-800 bg-neutral-900/70 overflow-hidden text-sm transition-colors">
      <div
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-neutral-800/50 select-none"
      >
        <div className="flex items-center space-x-2 truncate">
          {isRunning && <Loader2 className="w-4 h-4 animate-spin text-amber-400 shrink-0" />}
          {isSuccess && <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />}
          {isFailed && <XCircle className="w-4 h-4 text-rose-400 shrink-0" />}

          {isCommand ? (
            <Terminal className="w-4 h-4 text-neutral-400 shrink-0" />
          ) : isFileEdit ? (
            <FileCode className="w-4 h-4 text-neutral-400 shrink-0" />
          ) : null}

          <span className="font-mono font-medium text-neutral-200">
            {tool.sdk_tool_name}
          </span>

          {/* Quick inline preview of primary arg */}
          {tool.args && (
            <span className="text-neutral-400 text-xs truncate max-w-md font-mono">
              {(tool.args.command ||
                tool.args.file_path ||
                tool.args.target_path ||
                tool.args.directory_path ||
                tool.args.query ||
                '') as string}
            </span>
          )}
        </div>

        <div className="flex items-center space-x-2">
          {(isCommand || isFileEdit) && (
            <button
              onClick={handleOpenDrawer}
              className="flex items-center space-x-1 px-2 py-0.5 text-xs text-neutral-400 hover:text-neutral-100 hover:bg-neutral-700/60 rounded"
              title={isCommand ? 'View Terminal Logs' : 'View Diff'}
            >
              <span>{isCommand ? 'Terminal' : 'Diff'}</span>
              <ExternalLink className="w-3 h-3" />
            </button>
          )}

          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-neutral-400" />
          ) : (
            <ChevronRight className="w-4 h-4 text-neutral-400" />
          )}
        </div>
      </div>

      {isExpanded && (
        <div className="px-3 py-2.5 border-t border-neutral-800/60 bg-neutral-950/60 font-mono text-xs text-neutral-300 space-y-2">
          <div>
            <div className="text-neutral-400 font-semibold mb-1">Arguments:</div>
            <pre className="bg-neutral-900 p-2 rounded border border-neutral-800 overflow-x-auto whitespace-pre-wrap">
              {JSON.stringify(tool.args, null, 2)}
            </pre>
          </div>

          {tool.output_summary && (
            <div>
              <div className="text-neutral-400 font-semibold mb-1">Result:</div>
              <div className="bg-neutral-900 p-2 rounded border border-neutral-800 text-neutral-200 whitespace-pre-wrap">
                {tool.output_summary}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
