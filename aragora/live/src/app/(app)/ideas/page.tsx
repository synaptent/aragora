'use client';

import { useCallback, useEffect, useState } from 'react';
import dynamic from 'next/dynamic';
import type { IdeaCanvasMeta } from '@/components/idea-canvas/types';

const IdeaCanvas = dynamic(() => import('@/components/idea-canvas/IdeaCanvas'), { ssr: false });

const API_BASE = '/api/v1/ideas';

/**
 * /ideas page -- lists canvases or opens a canvas editor.
 */
export default function IdeasPage() {
  const [canvases, setCanvases] = useState<IdeaCanvasMeta[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchCanvases = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(API_BASE);
      if (res.ok) {
        const data = await res.json();
        setCanvases(data.canvases || []);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCanvases();
  }, [fetchCanvases]);

  const createCanvas = async () => {
    const name = `Ideas ${new Date().toLocaleDateString()}`;
    const res = await fetch(API_BASE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    if (res.ok) {
      const data = await res.json();
      setCanvases((prev) => [data, ...prev]);
      setSelectedId(data.id);
    }
  };

  const deleteCanvas = async (id: string) => {
    await fetch(`${API_BASE}/${id}`, { method: 'DELETE' });
    setCanvases((prev) => prev.filter((c) => c.id !== id));
    if (selectedId === id) setSelectedId(null);
  };

  // ── Canvas editor view ───────────────────────────────────────
  if (selectedId) {
    return (
      <div className="h-full flex flex-col">
        {/* Header */}
        <div className="flex items-center gap-3 px-4 py-2 border-b border-[var(--border)] bg-[var(--bg)]">
          <button
            onClick={() => setSelectedId(null)}
            className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--text)]"
          >
            &lt; Back
          </button>
          <span className="text-xs font-theme-data text-[var(--text)]">
            {canvases.find((c) => c.id === selectedId)?.name || 'Idea Canvas'}
          </span>
        </div>
        <div className="flex-1">
          <IdeaCanvas canvasId={selectedId} />
        </div>
      </div>
    );
  }

  // ── Canvas list view ─────────────────────────────────────────
  return (
    <div className="p-6 max-w-4xl mx-auto font-theme-data">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-[var(--text)]">Idea Canvas</h1>
          <p className="text-xs text-[var(--text-muted)] mt-1">
            Stage 1 of the Idea-to-Execution Pipeline
          </p>
        </div>
        <button
          onClick={createCanvas}
          className="px-4 py-2 text-xs rounded bg-[var(--acid-green)]/20 border border-[var(--acid-green)] text-[var(--acid-green)] hover:bg-[var(--acid-green)]/30 transition-colors"
        >
          + New Canvas
        </button>
      </div>

      {loading && <p className="text-xs text-[var(--text-muted)]">Loading...</p>}

      {!loading && canvases.length === 0 && (
        <div className="text-center py-12">
          <p className="text-sm text-[var(--text-muted)] mb-4">
            No idea canvases yet. Create one to start organizing your ideas.
          </p>
          <button
            onClick={createCanvas}
            className="px-4 py-2 text-xs rounded bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] hover:border-[var(--acid-green)] transition-colors"
          >
            Create your first canvas
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {canvases.map((canvas) => (
          <div
            key={canvas.id}
            className="group p-4 rounded-lg border border-[var(--border)] bg-[var(--surface)] hover:border-[var(--acid-green)] transition-colors cursor-pointer"
            onClick={() => setSelectedId(canvas.id)}
          >
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-bold text-[var(--text)] truncate">{canvas.name}</h3>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  deleteCanvas(canvas.id);
                }}
                className="text-[10px] text-[var(--text-muted)] hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
              >
                delete
              </button>
            </div>
            {canvas.description && (
              <p className="text-[10px] text-[var(--text-muted)] line-clamp-2 mb-2">
                {canvas.description}
              </p>
            )}
            <div className="text-[9px] text-[var(--text-muted)]">
              {new Date(canvas.updated_at).toLocaleDateString()}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
