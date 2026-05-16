import { useMemo } from 'react';
import { Lock } from 'lucide-react';

import { useDesignerStore } from '@/features/survey-designer/store';
import { useAuthStore } from '@/features/auth/store';

/**
 * Floating banner pinned to the bottom of the editor that lists which
 * questions are currently being edited by other collaborators.
 *
 * SurveyJS Creator renders questions inside a shadow-DOM-ish iframe-like
 * structure that makes per-question DOM injection brittle.  A single
 * banner is the simplest reliable affordance.
 */
export function QuestionLockOverlay() {
    const collaborators = useDesignerStore((s) => s.collaborators);
    const myUserId = useAuthStore((s) => s.user?.id);

    const focusedByOthers = useMemo(
        () =>
            Object.values(collaborators).filter(
                (c) => c.user_id !== myUserId && c.focused_question_id,
            ),
        [collaborators, myUserId],
    );

    if (focusedByOthers.length === 0) return null;

    return (
        <div className="pointer-events-none absolute bottom-4 left-1/2 -translate-x-1/2 z-30">
            <div className="pointer-events-auto flex flex-col gap-1 rounded-lg border bg-white/95 px-3 py-2 shadow-lg backdrop-blur">
                {focusedByOthers.map((c) => (
                    <div
                        key={c.connection_id}
                        className="flex items-center gap-2 text-xs"
                    >
                        <Lock
                            className="h-3 w-3"
                            style={{ color: c.color }}
                        />
                        <span className="font-medium" style={{ color: c.color }}>
                            {c.display_name}
                        </span>
                        <span className="text-muted-foreground">
                            正在编辑题目 <code className="rounded bg-muted px-1 text-[11px]">
                                {c.focused_question_id}
                            </code>
                        </span>
                    </div>
                ))}
            </div>
        </div>
    );
}
