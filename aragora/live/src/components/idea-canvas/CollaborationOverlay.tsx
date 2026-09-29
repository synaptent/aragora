'use client';

import type { RemoteCursor } from './types';

interface CollaborationOverlayProps {
  cursors: RemoteCursor[];
  onlineUsers: string[];
}

const CURSOR_COLORS = [
  '#ef4444',
  '#f97316',
  '#eab308',
  '#22c55e',
  '#06b6d4',
  '#3b82f6',
  '#8b5cf6',
  '#ec4899',
];

function getUserColor(userId: string): string {
  let hash = 0;
  for (let i = 0; i < userId.length; i++) {
    hash = ((hash << 5) - hash + userId.charCodeAt(i)) | 0;
  }
  return CURSOR_COLORS[Math.abs(hash) % CURSOR_COLORS.length];
}

/**
 * Overlay showing remote user cursors and presence.
 */
export function CollaborationOverlay({ cursors, onlineUsers }: CollaborationOverlayProps) {
  return (
    <>
      {/* Remote cursors */}
      {cursors.map((cursor) => (
        <div
          key={cursor.userId}
          className="absolute pointer-events-none z-50 transition-all duration-75"
          style={{ left: cursor.position.x, top: cursor.position.y }}
        >
          <div
            className="w-3 h-3 rounded-full"
            style={{ backgroundColor: cursor.color || getUserColor(cursor.userId) }}
          />
          <span
            className="text-[9px] font-theme-data px-1 rounded whitespace-nowrap ml-2"
            style={{ backgroundColor: cursor.color || getUserColor(cursor.userId), color: '#fff' }}
          >
            {cursor.userId.slice(0, 8)}
          </span>
        </div>
      ))}

      {/* Presence panel */}
      {onlineUsers.length > 0 && (
        <div className="absolute top-2 right-2 z-40 bg-[var(--surface)] border border-[var(--border)] rounded px-2 py-1">
          <div className="text-[9px] text-[var(--text-muted)] font-theme-data uppercase tracking-wider mb-1">
            Online ({onlineUsers.length})
          </div>
          <div className="flex gap-1">
            {onlineUsers.slice(0, 5).map((uid) => (
              <div
                key={uid}
                className="w-5 h-5 rounded-full flex items-center justify-center text-[8px] text-white font-bold"
                style={{ backgroundColor: getUserColor(uid) }}
                title={uid}
              >
                {uid[0]?.toUpperCase()}
              </div>
            ))}
            {onlineUsers.length > 5 && (
              <span className="text-[9px] text-[var(--text-muted)] self-center">
                +{onlineUsers.length - 5}
              </span>
            )}
          </div>
        </div>
      )}
    </>
  );
}

export default CollaborationOverlay;
