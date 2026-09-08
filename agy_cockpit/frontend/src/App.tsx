import React, { useEffect, useState } from 'react';
import { wsService } from './services/websocket';
import { useCockpitStore } from './store/useCockpitStore';
import { Sidebar } from './components/Sidebar';
import { Header } from './components/Header';
import { ChatTimeline } from './components/ChatTimeline';
import { Composer } from './components/Composer';
import { RightDrawer } from './components/RightDrawer';
import { ApprovalModal } from './components/ApprovalModal';
import { SettingsModal } from './components/SettingsModal';

export const App: React.FC = () => {
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  useEffect(() => {
    wsService.connect();

    // Fetch dynamic model catalog
    const token = localStorage.getItem('agy_token') || '';
    fetch('/api/models', {
      headers: token ? { 'x-antigravity-token': token } : {},
    })
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((data) => {
        if (data.models && Array.isArray(data.models)) {
          useCockpitStore.getState().setModels(data.models);
        }
      })
      .catch((err) => console.warn('Failed to load dynamic models', err));
  }, []);

  return (
    <div className="flex h-screen w-screen bg-neutral-950 text-neutral-100 overflow-hidden font-sans">
      {/* Left Sidebar */}
      <Sidebar onOpenSettings={() => setIsSettingsOpen(true)} />

      {/* Main Chat Canvas */}
      <main className="flex-1 flex flex-col min-w-0 h-full relative">
        <Header />
        <ChatTimeline />
        <Composer />
      </main>

      {/* Right Drawer (Diffs, Terminal, Subagents, Artifacts) */}
      <RightDrawer />

      {/* Overlays */}
      <ApprovalModal />
      <SettingsModal isOpen={isSettingsOpen} onClose={() => setIsSettingsOpen(false)} />
    </div>
  );
};

export default App;
