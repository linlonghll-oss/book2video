import { create } from "zustand";

interface AppState {
  currentFolderId: number | null;
  currentNoteId: number | null;
  configModalOpen: boolean;
  slideDrawerOpen: boolean;
  sidebarCollapsed: boolean;
  setFolderId: (id: number | null) => void;
  setNoteId: (id: number | null) => void;
  setConfigModalOpen: (open: boolean) => void;
  setSlideDrawerOpen: (open: boolean) => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
}

export const useAppStore = create<AppState>((set) => ({
  currentFolderId: null,
  currentNoteId: null,
  configModalOpen: false,
  slideDrawerOpen: false,
  sidebarCollapsed: false,
  setFolderId: (id) => set({ currentFolderId: id, currentNoteId: null }),
  setNoteId: (id) => set({ currentNoteId: id }),
  setConfigModalOpen: (open) => set({ configModalOpen: open }),
  setSlideDrawerOpen: (open) => set({ slideDrawerOpen: open }),
  setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),
}));
