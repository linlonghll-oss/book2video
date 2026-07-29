"use client";

import { useAppStore } from "@/lib/store";
import FolderSidebar from "@/components/FolderSidebar";
import NoteList from "@/components/NoteList";
import NoteDetail from "@/components/NoteDetail";
import ConfigModal from "@/components/ConfigModal";

export default function HomePage() {
  const { currentNoteId, sidebarCollapsed } = useAppStore();

  return (
    <div className="flex h-screen bg-white">
      {/* Col 1: Folders */}
      {!sidebarCollapsed && <FolderSidebar />}

      {/* Col 2: Note list */}
      <div
        className="border-r border-gray-200 flex flex-col shrink-0"
        style={{ width: sidebarCollapsed ? 0 : 260 }}
      >
        {!sidebarCollapsed && <NoteList />}
      </div>

      {/* Col 3: Note detail / workflow */}
      <div className="flex-1 flex flex-col min-w-0">
        {currentNoteId ? (
          <NoteDetail />
        ) : (
          <div className="flex-1 flex items-center justify-center text-gray-300 text-sm">
            选择或新建一条笔记
          </div>
        )}
      </div>

      <ConfigModal />
    </div>
  );
}
