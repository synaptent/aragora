'use client';

import { memo, useState, useCallback } from 'react';
import { AutomationLevelSelector, type AutomationLevel } from './AutomationLevelSelector';

export interface BrainDumpEditorProps {
  onLaunch: (text: string, automationLevel: AutomationLevel) => Promise<string | null>;
  preview?: { themes: string[]; ideaCount: number; urgencySignals: string[]; isLoading: boolean };
  onTextChange?: (text: string) => void;
  disabled?: boolean;
}

const THEME_COLORS: Record<string, string> = {
  performance: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  security: 'bg-red-500/20 text-red-400 border-red-500/30',
  ux: 'bg-pink-500/20 text-pink-400 border-pink-500/30',
  reliability: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  scalability: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  testing: 'bg-violet-500/20 text-violet-400 border-violet-500/30',
  documentation: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
  infrastructure: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
  data: 'bg-indigo-500/20 text-indigo-400 border-indigo-500/30',
  integration: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
};

export const BrainDumpEditor = memo(function BrainDumpEditor({
  onLaunch,
  preview,
  onTextChange,
  disabled,
}: BrainDumpEditorProps) {
  const [text, setText] = useState('');
  const [automationLevel, setAutomationLevel] = useState<AutomationLevel>('guided');
  const [isLaunching, setIsLaunching] = useState(false);

  const handleTextChange = useCallback(
    (value: string) => {
      setText(value);
      onTextChange?.(value);
    },
    [onTextChange],
  );

  const handleLaunch = useCallback(async () => {
    if (!text.trim() || isLaunching) return;
    setIsLaunching(true);
    try {
      await onLaunch(text, automationLevel);
    } finally {
      setIsLaunching(false);
    }
  }, [text, automationLevel, isLaunching, onLaunch]);

  const hasContent = text.trim().length > 0;

  return (
    <div className="flex flex-col h-full bg-[var(--bg)] border border-[var(--border)] rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border)]">
        <div className="flex items-center gap-2">
          <span className="text-base">🧠</span>
          <h3 className="text-sm font-theme-data font-bold text-[var(--text)]">Brain Dump</h3>
        </div>
        {preview && !preview.isLoading && preview.ideaCount > 0 && (
          <span className="text-xs font-theme-data text-[var(--text-muted)]">
            ~{preview.ideaCount} ideas detected
          </span>
        )}
      </div>

      {/* Editor area */}
      <div className="flex-1 p-4">
        <textarea
          className="w-full h-full min-h-[200px] bg-transparent text-[var(--text)] text-sm font-theme-data
                     placeholder:text-[var(--text-muted)] resize-none focus:outline-none"
          placeholder="Paste your ideas, thoughts, goals, concerns, brainstorms...&#10;&#10;Use any format: bullets, numbered lists, paragraphs, or free-flowing prose.&#10;AI will extract ideas, detect themes, and organize them into actionable goals."
          value={text}
          onChange={(e) => handleTextChange(e.target.value)}
          disabled={disabled || isLaunching}
          data-testid="brain-dump-textarea"
        />
      </div>

      {/* Theme chips */}
      {preview && preview.themes.length > 0 && (
        <div className="px-4 py-2 border-t border-[var(--border)]">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-xs text-[var(--text-muted)] mr-1">Themes:</span>
            {preview.themes.map((theme) => (
              <span
                key={theme}
                className={`px-2 py-0.5 text-xs font-theme-data rounded-full border ${
                  THEME_COLORS[theme] || 'bg-gray-500/20 text-gray-400 border-gray-500/30'
                }`}
              >
                {theme}
              </span>
            ))}
            {preview.isLoading && (
              <span className="text-xs text-[var(--text-muted)] animate-pulse">analyzing...</span>
            )}
          </div>
          {preview.urgencySignals.length > 0 && (
            <div className="flex items-center gap-1.5 mt-1.5">
              <span className="text-xs text-amber-400">⚡ Urgency:</span>
              {preview.urgencySignals.map((signal, i) => (
                <span
                  key={i}
                  className="px-1.5 py-0.5 text-xs font-theme-data bg-amber-500/20 text-amber-400 rounded"
                >
                  {signal}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Controls */}
      <div className="px-4 py-3 border-t border-[var(--border)] flex items-end gap-4">
        <div className="flex-1">
          <AutomationLevelSelector value={automationLevel} onChange={setAutomationLevel} />
        </div>
        <button
          className={`px-4 py-2 text-sm font-theme-data rounded-lg transition-all
            ${
              hasContent && !isLaunching
                ? 'bg-[var(--acid-green)] text-black hover:opacity-90 cursor-pointer'
                : 'bg-gray-600 text-gray-400 cursor-not-allowed'
            }
          `}
          onClick={handleLaunch}
          disabled={!hasContent || isLaunching || disabled}
          data-testid="brain-dump-launch"
        >
          {isLaunching ? 'Launching...' : 'Launch Pipeline →'}
        </button>
      </div>
    </div>
  );
});

export default BrainDumpEditor;
