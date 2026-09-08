import React, { useEffect, useState } from 'react';
import { wsService } from './services/websocket';
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
