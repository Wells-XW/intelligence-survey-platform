import { useMemo } from 'react';
import { Wifi, WifiOff, Loader2 } from 'lucide-react';

import { useDesignerStore } from '@/features/survey-designer/store';
import { useAuthStore } from '@/features/auth/store';

interface CollaboratorAvatarsProps {
    /** Maximum avatars to render before collapsing into a "+N" badge. */
    maxVisible?: number;
}

function initials(name: string): string {
    if (!name) return '?';
    const trimmed = name.trim();
    // For Chinese names, use the last 1-2 characters.
    if (/[\u4e00-\u9fa5]/.test(trimmed)) {
        return trimmed.slice(-2);
    }
    // Otherwise, first letter of first 2 words.
    const parts = trimmed.split(/\s+/).filter(Boolean);
    return parts
        .slice(0, 2)
        .map((p) => p[0])
        .join('')
        .toUpperCase();
}

export function CollaboratorAvatars({ maxVisible = 5 }: CollaboratorAvatarsProps) {
    const collaborators = useDesignerStore((s) => s.collaborators);
    const myConnectionId = useDesignerStore((s) => s.collabConnectionId);
    const status = useDesignerStore((s) => s.collabStatus);
    const myUserId = useAuthStore((s) => s.user?.id);

    const sorted = useMemo(() => {
        const all = Object.values(collaborators);
        // Put self first, then sort by join time.
        return all.sort((a, b) => {
            if (a.connection_id === myConnectionId) return -1;
            if (b.connection_id === myConnectionId) return 1;
            return a.joined_at.localeCompare(b.joined_at);
        });
    }, [collaborators, myConnectionId]);

    // Deduplicate by user_id so two browser tabs from the same user collapse
    // to one avatar (still highlight current user).
    const unique = useMemo(() => {
        const seen = new Set<string>();
        const result: typeof sorted = [];
        for (const c of sorted) {
            if (seen.has(c.user_id)) continue;
            seen.add(c.user_id);
            result.push(c);
        }
        return result;
    }, [sorted]);

    const visible = unique.slice(0, maxVisible);
    const overflow = unique.length - visible.length;

    return (
        <div className="flex items-center gap-2">
            <div className="flex -space-x-2">
                {visible.map((user) => {
                    const isMe = user.user_id === myUserId;
                    return (
                        <div
                            key={user.connection_id}
                            className="relative flex h-7 w-7 items-center justify-center rounded-full border-2 border-white text-xs font-medium text-white shadow-sm"
                            style={{ backgroundColor: user.color }}
                            title={`${user.display_name}${isMe ? '（你）' : ''}${user.focused_question_id ? ` · 正在编辑题目` : ''
                                }`}
                        >
                            {initials(user.display_name)}
                            {user.focused_question_id && (
                                <span
                                    className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border border-white"
                                    style={{ backgroundColor: '#22C55E' }}
                                    aria-label="正在编辑"
                                />
                            )}
                        </div>
                    );
                })}
                {overflow > 0 && (
                    <div
                        className="flex h-7 w-7 items-center justify-center rounded-full border-2 border-white bg-muted text-xs font-medium text-muted-foreground shadow-sm"
                        title={`还有 ${overflow} 位协作者在线`}
                    >
                        +{overflow}
                    </div>
                )}
            </div>
            <ConnectionStatusBadge status={status} />
        </div>
    );
}

function ConnectionStatusBadge({ status }: { status: string }) {
    if (status === 'open') {
        return (
            <span
                className="flex items-center gap-1 text-xs text-green-600"
                title="实时协作已连接"
            >
                <Wifi className="h-3.5 w-3.5" />
            </span>
        );
    }
    if (status === 'connecting' || status === 'reconnecting') {
        return (
            <span
                className="flex items-center gap-1 text-xs text-amber-600"
                title={status === 'reconnecting' ? '正在重连…' : '正在连接…'}
            >
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
            </span>
        );
    }
    if (status === 'closed' || status === 'idle') {
        return (
            <span
                className="flex items-center gap-1 text-xs text-muted-foreground"
                title="未连接到实时协作"
            >
                <WifiOff className="h-3.5 w-3.5" />
            </span>
        );
    }
    return null;
}
