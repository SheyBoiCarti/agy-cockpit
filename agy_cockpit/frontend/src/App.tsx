import React, { useEffect, useState } from 'react';
import { wsService } from './services/websocket';
import { refreshModels } from './services/models';
import { ModelCatalogBanner } from './components/ModelCatalogBanner';
import { useCockpitStore } from './store/useCockpitStore';
import { Sidebar } from './components/Sidebar';
import { Header } from './components/Header';
import { ChatTimeline } from './components/ChatTimeline';
import { Composer } from './components/Composer';
import { RightDrawer } from './components/RightDrawer';
import { ApprovalModal } from './components/ApprovalModal';
import { SettingsModal } from './components/SettingsModal';
import { NoticeBanner } from './components/NoticeBanner';

export const App: React.FC = () => {
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const sidebarOpen = useCockpitStore(s => s.isSidebarOpen);
  const drawerOpen = useCockpitStore(s => Boolean(s.activeDrawerTab));

  useEffect(() => {
    wsService.connect();

    void refreshModels();
  }, []);

  return (
    <div className="flex h-screen w-screen bg-neutral-950 text-neutral-100 overflow-hidden font-sans">
      {sidebarOpen && <button tabIndex={-1} aria-label="Dismiss navigation" className="fixed inset-0 z-30 bg-black/60 md:hidden" onClick={() => useCockpitStore.getState().setSidebarOpen(false)} />}
      {drawerOpen && <button tabIndex={-1} aria-label="Dismiss auxiliary panel" className="drawer-backdrop fixed inset-0 z-30 bg-black/60" onClick={() => useCockpitStore.getState().setActiveDrawerTab(null)} />}
      {/* Left Sidebar */}
      <Sidebar onOpenSettings={() => setIsSettingsOpen(true)} />

      {/* Main Chat Canvas */}
      <main className="flex-1 flex flex-col min-w-0 h-full relative">
        <Header />
        <NoticeBanner />
        <ModelCatalogBanner />
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
