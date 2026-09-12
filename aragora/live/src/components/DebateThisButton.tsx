'use client';

import { useState } from 'react';
import { DebateThisModal } from './DebateThisModal';

export interface DebateThisButtonProps {
  question: string;
  context?: string;
  source?: 'pulse' | 'receipt' | 'pipeline' | 'dashboard' | string;
  variant?: 'icon' | 'button' | 'inline';
  className?: string;
}

export function DebateThisButton({
  question,
  context,
  source,
  variant = 'button',
  className = '',
}: DebateThisButtonProps) {
  const [isOpen, setIsOpen] = useState(false);

  if (variant === 'icon') {
    return (
      <>
        <button
          onClick={(e) => {
            e.stopPropagation();
            setIsOpen(true);
          }}
          className={`w-8 h-8 flex items-center justify-center text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/30 rounded hover:bg-[var(--acid-cyan)]/10 hover:border-[var(--acid-cyan)] transition-all ${className}`}
          title="Debate This"
          aria-label="Debate This"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          >
            <path d="M2 8h12M8 2v12M4 4l8 8M12 4l-8 8" />
          </svg>
        </button>
        {isOpen && (
          <DebateThisModal
            question={question}
            context={context}
            source={source}
            onClose={() => setIsOpen(false)}
          />
        )}
      </>
    );
  }

  if (variant === 'inline') {
    return (
      <>
        <button
          onClick={(e) => {
            e.stopPropagation();
            setIsOpen(true);
          }}
          className={`text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] underline underline-offset-2 transition-colors ${className}`}
        >
          Debate This
        </button>
        {isOpen && (
          <DebateThisModal
            question={question}
            context={context}
            source={source}
            onClose={() => setIsOpen(false)}
          />
        )}
      </>
    );
  }

  // Default: 'button' variant
  return (
    <>
      <button
        onClick={(e) => {
          e.stopPropagation();
          setIsOpen(true);
        }}
        className={`px-3 py-1 text-xs font-theme-data text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/50 hover:bg-[var(--acid-cyan)]/10 hover:border-[var(--acid-cyan)] transition-all duration-200 rounded ${className}`}
      >
        DEBATE THIS
      </button>
      {isOpen && (
        <DebateThisModal
          question={question}
          context={context}
          source={source}
          onClose={() => setIsOpen(false)}
        />
      )}
    </>
  );
}

export default DebateThisButton;
