import React from 'react';
import { useCockpitStore } from '../store/useCockpitStore';
import { wsService } from '../services/websocket';
import { ShieldAlert, Check, X, Terminal, FileEdit, AlertCircle } from 'lucide-react';

export const ApprovalModal: React.FC = () => {
  const pendingApproval = useCockpitStore((s) => s.pendingApproval);
  const pendingApprovals = useCockpitStore((s) => s.pendingApprovals);
  const policyPreset = useCockpitStore((s) => s.settings.policy_preset);

  if (!pendingApproval) return null;

  const handleDecision = (decision: 'approved' | 'rejected') => {
    wsService.respondApproval(pendingApproval.id, decision);
    useCockpitStore.getState().dequeueApproval(pendingApproval.id);
  };

  const isCommand = pendingApproval.sdk_tool_name === 'run_command';
  const isFileChange =
    pendingApproval.sdk_tool_name === 'create_file' ||
    pendingApproval.sdk_tool_name === 'edit_file';

  const queueCount = pendingApprovals ? pendingApprovals.length : 1;

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-xs flex items-center justify-center z-50 p-4">
      <div className="bg-neutral-900 border border-amber-500/40 rounded-2xl max-w-xl w-full p-6 shadow-2xl space-y-4">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div className="flex items-center space-x-3 text-amber-400">
            <div className="p-2 bg-amber-500/20 rounded-xl border border-amber-500/30">
              <ShieldAlert className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <h3 className="text-base font-semibold text-neutral-100">
                  Action Requires Approval
                </h3>
                {queueCount > 1 && (
                  <span className="px-2 py-0.5 text-xs rounded-full bg-amber-500/20 text-amber-300 font-mono border border-amber-500/30">
                    {queueCount} pending
                  </span>
                )}
              </div>
              <p className="text-xs text-neutral-400">
                Antigravity is requesting permission to execute an external tool.
              </p>
            </div>
          </div>
          {policyPreset && (
            <span className="px-2.5 py-1 text-xs rounded-lg bg-neutral-800 text-neutral-300 border border-neutral-700 font-mono shrink-0">
              policy: {policyPreset}
            </span>
          )}
        </div>

        {/* Reason / Policy Context */}
        {pendingApproval.reason && (
          <div className="flex items-start space-x-2 bg-amber-950/30 border border-amber-500/20 rounded-xl p-3 text-xs text-amber-200/90 leading-relaxed">
            <AlertCircle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
            <div>
              <span className="font-semibold text-amber-300">Reason: </span>
              <span>{pendingApproval.reason}</span>
            </div>
          </div>
        )}

        {/* Tool Details */}
        <div className="bg-neutral-950 rounded-xl border border-neutral-800 p-4 space-y-2">
          <div className="flex items-center space-x-2 text-xs font-mono text-neutral-300">
            {isCommand ? (
              <Terminal className="w-4 h-4 text-amber-400 shrink-0" />
            ) : isFileChange ? (
              <FileEdit className="w-4 h-4 text-blue-400 shrink-0" />
            ) : null}
            <span className="font-semibold text-neutral-200">
              {pendingApproval.sdk_tool_name}
            </span>
          </div>

          <div className="max-h-60 overflow-y-auto font-mono text-xs text-neutral-300 bg-neutral-900/90 p-3 rounded-lg border border-neutral-800/80 whitespace-pre-wrap">
            {pendingApproval.args.command ? (
              <div>
                <span className="text-neutral-400 select-none">$ </span>
                <span className="text-emerald-300 font-bold">
                  {String(pendingApproval.args.command)}
                </span>
              </div>
            ) : (
              JSON.stringify(pendingApproval.args, null, 2)
            )}
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center justify-end space-x-3 pt-2">
          <button
            onClick={() => handleDecision('rejected')}
            className="flex items-center space-x-1.5 px-4 py-2 rounded-xl bg-neutral-800 text-neutral-300 hover:bg-rose-950 hover:text-rose-300 border border-neutral-700 hover:border-rose-700 text-xs font-medium transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
            <span>Reject</span>
          </button>

          <button
            onClick={() => handleDecision('approved')}
            className="flex items-center space-x-1.5 px-4 py-2 rounded-xl bg-emerald-600 text-white hover:bg-emerald-500 text-xs font-medium transition-colors shadow-lg shadow-emerald-950 cursor-pointer"
          >
            <Check className="w-4 h-4" />
            <span>Approve & Proceed</span>
          </button>
        </div>
      </div>
    </div>
  );
};
