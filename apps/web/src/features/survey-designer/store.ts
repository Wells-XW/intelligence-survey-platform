import { create } from 'zustand';

import type {
  CollabSocketStatus,
  CollaboratorPresence,
} from '@/lib/collabSocket';

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

  // ── Real-time collaboration state ────────────────────────────────
  /** Connection id assigned by the server (null until auth.ok). */
  collabConnectionId: string | null;
  /** Connection lifecycle status. */
  collabStatus: CollabSocketStatus;
  /** Live presence keyed by connection_id (one user can have multiple tabs). */
  collaborators: Record<string, CollaboratorPresence>;

  setDirty: (dirty: boolean) => void;
  setSelectedQuestion: (id: string | null) => void;
  toggleAiPanel: () => void;
  setShareDialogOpen: (open: boolean) => void;
  setVersionPanelOpen: (open: boolean) => void;
  setConflictDialogOpen: (open: boolean) => void;
  setConflictInfo: (info: { expectedVersion: number; serverVersion: number } | null) => void;

  // Collaboration mutations (called from useCollabSocket)
  setCollabConnectionId: (id: string | null) => void;
  setCollabStatus: (status: CollabSocketStatus) => void;
  setCollaboratorsSnapshot: (users: CollaboratorPresence[]) => void;
  upsertCollaborator: (user: CollaboratorPresence) => void;
  removeCollaborator: (connectionId: string) => void;
  setCollaboratorFocus: (
    connectionId: string,
    update: Pick<
      CollaboratorPresence,
      'focused_question_id' | 'focus_expires_at'
    > & { display_name?: string; color?: string; user_id?: string },
  ) => void;
  resetCollaboration: () => void;
}

export const useDesignerStore = create<DesignerState>((set) => ({
  isDirty: false,
  selectedQuestionId: null,
  isAiPanelOpen: false,

  isShareDialogOpen: false,
  isVersionPanelOpen: false,
  isConflictDialogOpen: false,
  conflictInfo: null,

  collabConnectionId: null,
  collabStatus: 'idle',
  collaborators: {},

  setDirty: (dirty) => set({ isDirty: dirty }),
  setSelectedQuestion: (id) => set({ selectedQuestionId: id }),
  toggleAiPanel: () => set((s) => ({ isAiPanelOpen: !s.isAiPanelOpen })),
  setShareDialogOpen: (open) => set({ isShareDialogOpen: open }),
  setVersionPanelOpen: (open) => set({ isVersionPanelOpen: open }),
  setConflictDialogOpen: (open) => set({ isConflictDialogOpen: open }),
  setConflictInfo: (info) => set({ conflictInfo: info }),

  setCollabConnectionId: (id) => set({ collabConnectionId: id }),
  setCollabStatus: (status) => set({ collabStatus: status }),

  setCollaboratorsSnapshot: (users) =>
    set(() => ({
      collaborators: Object.fromEntries(users.map((u) => [u.connection_id, u])),
    })),

  upsertCollaborator: (user) =>
    set((state) => ({
      collaborators: { ...state.collaborators, [user.connection_id]: user },
    })),

  removeCollaborator: (connectionId) =>
    set((state) => {
      if (!state.collaborators[connectionId]) return state;
      const next = { ...state.collaborators };
      delete next[connectionId];
      return { collaborators: next };
    }),

  setCollaboratorFocus: (connectionId, update) =>
    set((state) => {
      const existing = state.collaborators[connectionId];
      if (!existing) {
        // Server sent a focus.update for someone we haven't seen yet —
        // synthesize a minimal presence record so the UI can render.
        if (!update.user_id || !update.display_name || !update.color) {
          return state;
        }
        return {
          collaborators: {
            ...state.collaborators,
            [connectionId]: {
              connection_id: connectionId,
              user_id: update.user_id,
              display_name: update.display_name,
              color: update.color,
              focused_question_id: update.focused_question_id,
              focus_expires_at: update.focus_expires_at,
              joined_at: new Date().toISOString(),
            },
          },
        };
      }
      return {
        collaborators: {
          ...state.collaborators,
          [connectionId]: {
            ...existing,
            focused_question_id: update.focused_question_id,
            focus_expires_at: update.focus_expires_at,
          },
        },
      };
    }),

  resetCollaboration: () =>
    set({
      collabConnectionId: null,
      collabStatus: 'idle',
      collaborators: {},
    }),
}));
