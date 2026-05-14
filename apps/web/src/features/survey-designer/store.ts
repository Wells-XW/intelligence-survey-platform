import { create } from 'zustand';

interface DesignerState {
  /** Whether the survey JSON has unsaved changes */
  isDirty: boolean;
  /** ID of the currently selected question in the editor */
  selectedQuestionId: string | null;
  /** Whether the AI assistant panel is open */
  isAiPanelOpen: boolean;

  setDirty: (dirty: boolean) => void;
  setSelectedQuestion: (id: string | null) => void;
  toggleAiPanel: () => void;
}

export const useDesignerStore = create<DesignerState>((set) => ({
  isDirty: false,
  selectedQuestionId: null,
  isAiPanelOpen: false,

  setDirty: (dirty) => set({ isDirty: dirty }),
  setSelectedQuestion: (id) => set({ selectedQuestionId: id }),
  toggleAiPanel: () => set((s) => ({ isAiPanelOpen: !s.isAiPanelOpen })),
}));
