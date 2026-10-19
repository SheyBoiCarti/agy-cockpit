import React, { useState, useEffect, useRef } from 'react';
import { useCockpitStore } from '../store/useCockpitStore';
import { wsService } from '../services/websocket';
import { X, Save, Key, Shield, Sparkles } from 'lucide-react';
import { usePanelFocus } from './usePanelFocus';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({ isOpen, onClose }) => {
  const panelRef = usePanelFocus(isOpen, '(min-width: 0px)', onClose);
  const settings = useCockpitStore((s) => s.settings);
  const models = useCockpitStore((s) => s.models);

  const [token, setToken] = useState(localStorage.getItem('agy_token') || '');
  const [policyPreset, setPolicyPreset] = useState(settings.policy_preset);
  const [defaultModel, setDefaultModel] = useState(settings.default_model);

  const dirty = useRef(false);
  useEffect(() => { if (!isOpen) dirty.current = false; }, [isOpen]);
  useEffect(() => {
    if (isOpen && !dirty.current) {
      setToken(localStorage.getItem('agy_token') || '');
      setPolicyPreset(settings.policy_preset);
      setDefaultModel(settings.default_model);
    }
  }, [isOpen, settings.policy_preset, settings.default_model]);
  if (!isOpen) return null;

  const handleSave = () => {
    if (token !== (localStorage.getItem('agy_token') || '')) { wsService.setToken(token); onClose(); return; }
    wsService.sendCommand('update_settings', {
      policy_preset: policyPreset,
      default_model: defaultModel,
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/75 backdrop-blur-xs flex items-center justify-center z-50 p-4">
      <section ref={panelRef} role="dialog" aria-modal="true" aria-label="Cockpit Settings" tabIndex={-1} className="bg-neutral-900 border border-neutral-700 rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-5">
        <div className="flex items-center justify-between border-b border-neutral-800 pb-3">
          <h3 className="text-base font-semibold text-neutral-100">Cockpit Settings</h3>
          <button onClick={onClose} className="text-neutral-400 hover:text-neutral-200">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="space-y-4 text-xs">
          {/* Launch Token */}
          <div>
            <label className="flex items-center space-x-1.5 font-medium text-neutral-300 mb-1.5">
              <Key className="w-3.5 h-3.5 text-amber-400" />
              <span>Launch Authorization Token</span>
            </label>
            <input
              type="password"
              value={token}
              onChange={(e) => { dirty.current = true; setToken(e.target.value); }}
              placeholder="Session security token"
              className="w-full bg-neutral-950 border border-neutral-700 rounded-lg px-3 py-2 text-xs font-mono text-neutral-200 focus:outline-none focus:border-indigo-500"
            />
          </div>

          {/* Default Policy */}
          <div>
            <label className="flex items-center space-x-1.5 font-medium text-neutral-300 mb-1.5">
              <Shield className="w-3.5 h-3.5 text-blue-400" />
              <span>Default Tool Policy Preset</span>
            </label>
            <select
              value={policyPreset}
              onChange={(e) => { dirty.current = true; setPolicyPreset(e.target.value); }}
              className="w-full bg-neutral-950 border border-neutral-700 rounded-lg px-3 py-2 text-xs text-neutral-200 focus:outline-none focus:border-indigo-500"
            >
              <option value="request-review">Review Sensitive Tools (Default)</option>
              <option value="always-proceed">Always Proceed (Auto-approve tools)</option>
              <option value="strict">Strict (Ask approval for all state modifications)</option>
            </select>
          </div>

          {/* Default Model */}
          <div>
            <label className="flex items-center space-x-1.5 font-medium text-neutral-300 mb-1.5">
              <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
              <span>Default Gemini Model</span>
            </label>
            <select
              aria-label="Default model"
              value={defaultModel}
              onChange={(e) => { dirty.current = true; setDefaultModel(e.target.value); }}
              className="w-full bg-neutral-950 border border-neutral-700 rounded-lg px-3 py-2 text-xs text-neutral-200 focus:outline-none focus:border-indigo-500"
            >
              {!models.some(m => m.slug === defaultModel) && <option disabled value={defaultModel}>{defaultModel} (unavailable)</option>}
              {models.map((m) => (
                <option key={m.slug} value={m.slug}>
                  {m.label} ({m.slug})
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="flex items-center justify-end space-x-2 pt-3 border-t border-neutral-800">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl text-xs text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="flex items-center space-x-1.5 px-4 py-2 rounded-xl bg-indigo-600 text-white hover:bg-indigo-500 text-xs font-medium"
          >
            <Save className="w-3.5 h-3.5" />
            <span>Save Changes</span>
          </button>
        </div>
      </section>
    </div>
  );
};
