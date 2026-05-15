import { create } from 'zustand';

interface DesignerState {
  /** Whether the survey JSON has unsaved changes */
  isDirty: boolean;
  /** ID of the currently selected question in the editor */
  selectedQuestionId: string | null;
  /** Whether the AI assistant panel is open */
  isAiPanelOpen: boolean;

  // Collaboration & version UI toggles
  isShareDialogOpen: boolean;
  isVersionPanelOpen: boolean;
  isConflictDialogOpen: boolean;
  conflictInfo: { expectedVersion: number; serverVersion: number } | null;

  setDirty: (dirty: boolean) => void;
  setSelectedQuestion: (id: string | null) => void;
  toggleAiPanel: () => void;
  setShareDialogOpen: (open: boolean) => void;
  setVersionPanelOpen: (open: boolean) => void;
  setConflictDialogOpen: (open: boolean) => void;
  setConflictInfo: (info: { expectedVersion: number; serverVersion: number } | null) => void;
}

export const useDesignerStore = create<DesignerState>((set) => ({
  isDirty: false,
  selectedQuestionId: null,
  isAiPanelOpen: false,

  isShareDialogOpen: false,
  isVersionPanelOpen: false,
  isConflictDialogOpen: false,
  conflictInfo: null,

  setDirty: (dirty) => set({ isDirty: dirty }),
  setSelectedQuestion: (id) => set({ selectedQuestionId: id }),
  toggleAiPanel: () => set((s) => ({ isAiPanelOpen: !s.isAiPanelOpen })),
  setShareDialogOpen: (open) => set({ isShareDialogOpen: open }),
  setVersionPanelOpen: (open) => set({ isVersionPanelOpen: open }),
  setConflictDialogOpen: (open) => set({ isConflictDialogOpen: open }),
  setConflictInfo: (info) => set({ conflictInfo: info }),
}));
