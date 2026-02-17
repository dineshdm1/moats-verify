import { create } from "zustand";
import type { Library, HistoryItem } from "./api";

interface BuildState {
  building: boolean;
  buildProgress: number;
  buildStep: string;
  buildSteps: string[];
  buildError: string | null;
  buildLibraryId: string | null;
}

interface AppState {
  // Sidebar
  sidebarOpen: boolean;
  toggleSidebar: () => void;

  // Active library
  activeLibrary: Library | null;
  setActiveLibrary: (lib: Library | null) => void;

  // Libraries
  libraries: Library[];
  setLibraries: (libs: Library[]) => void;

  // History
  history: HistoryItem[];
  setHistory: (items: HistoryItem[]) => void;

  // Verification state
  isVerifying: boolean;
  verifyProgress: { step: string; percent: number } | null;
  setVerifying: (v: boolean) => void;
  setVerifyProgress: (p: { step: string; percent: number } | null) => void;

  // Build state (global so it persists across navigation)
  build: BuildState;
  setBuild: (b: Partial<BuildState>) => void;
  resetBuild: () => void;
}

const initialBuild: BuildState = {
  building: false,
  buildProgress: 0,
  buildStep: "",
  buildSteps: [],
  buildError: null,
  buildLibraryId: null,
};

export const useAppStore = create<AppState>((set) => ({
  sidebarOpen: true,
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),

  activeLibrary: null,
  setActiveLibrary: (lib) => set({ activeLibrary: lib }),

  libraries: [],
  setLibraries: (libs) => set({ libraries: libs }),

  history: [],
  setHistory: (items) => set({ history: items }),

  isVerifying: false,
  verifyProgress: null,
  setVerifying: (v) => set({ isVerifying: v }),
  setVerifyProgress: (p) => set({ verifyProgress: p }),

  build: initialBuild,
  setBuild: (b) => set((s) => ({ build: { ...s.build, ...b } })),
  resetBuild: () => set({ build: initialBuild }),
}));
