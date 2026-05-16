import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { useAuthStore } from '@/features/auth/store';
import { CollabSocket } from '@/lib/collabSocket';
import type { CollabIncomingMessage } from '@/lib/collabSocket';
import { useDesignerStore } from '@/features/survey-designer/store';

/**
 * Connects to the collaboration WebSocket for the given survey, syncs
 * server events into the Zustand store, and triggers TanStack Query
 * refetches on remote saves.  Returns the live socket so callers can
 * acquire/release focus locks.
 */
export function useCollabSocket(surveyId: string | undefined) {
    const queryClient = useQueryClient();
    const setStatus = useDesignerStore((s) => s.setCollabStatus);
    const setConnId = useDesignerStore((s) => s.setCollabConnectionId);
    const setSnapshot = useDesignerStore((s) => s.setCollaboratorsSnapshot);
    const upsert = useDesignerStore((s) => s.upsertCollaborator);
    const remove = useDesignerStore((s) => s.removeCollaborator);
    const setFocus = useDesignerStore((s) => s.setCollaboratorFocus);
    const reset = useDesignerStore((s) => s.resetCollaboration);
    const currentUserId = useAuthStore((s) => s.user?.id);

    const socketRef = useRef<CollabSocket | null>(null);

    useEffect(() => {
        if (!surveyId) return;

        const socket = new CollabSocket({
            surveyId,
            getToken: () => useAuthStore.getState().accessToken,
            onStatusChange: (next) => setStatus(next),
            onMessage: (msg: CollabIncomingMessage) => {
                switch (msg.type) {
                    case 'auth.ok':
                        setConnId(msg.connection_id);
                        break;
                    case 'presence.snapshot':
                        setSnapshot(msg.users);
                        break;
                    case 'presence.join':
                        upsert(msg.user);
                        break;
                    case 'presence.leave':
                        remove(msg.connection_id);
                        break;
                    case 'focus.update':
                        setFocus(msg.connection_id, {
                            focused_question_id: msg.question_id,
                            focus_expires_at: msg.expires_at,
                            display_name: msg.display_name,
                            color: msg.color,
                            user_id: msg.user_id,
                        });
                        break;
                    case 'survey.saved':
                        // Skip our own saves — the mutation already updated the cache.
                        if (msg.actor_user_id === currentUserId) {
                            break;
                        }
                        queryClient.invalidateQueries({
                            queryKey: ['survey', surveyId],
                        });
                        queryClient.invalidateQueries({
                            queryKey: ['surveyVersions', surveyId],
                        });
                        toast.info(`协作者已保存新版本 v${msg.version}，正在同步…`);
                        break;
                    case 'error':
                        if (msg.code === '4401' || msg.code === '4403') {
                            toast.error(msg.detail || '协作连接被拒绝');
                        }
                        break;
                    case 'heartbeat.ack':
                    case 'pong':
                        break;
                }
            },
        });

        socketRef.current = socket;
        socket.open();

        return () => {
            socket.close();
            socketRef.current = null;
            reset();
        };
        // We intentionally avoid re-running on unrelated state changes.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [surveyId]);

    return socketRef;
}
