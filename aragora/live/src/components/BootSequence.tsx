'use client';

import { useState, useEffect, useCallback, useRef } from 'react';

interface BootSequenceProps {
  onComplete: () => void;
  skip?: boolean;
}

const BOOT_LINES = [
  { text: 'ARAGORA SYSTEM v2.0.2', delay: 0, style: 'title' },
  { text: '═══════════════════════════════════════════════', delay: 100, style: 'divider' },
  { text: '', delay: 200, style: 'normal' },
  { text: '[INIT] Loading kernel modules...', delay: 300, style: 'system' },
  { text: '[OK] Multi-agent debate engine', delay: 450, style: 'success' },
  { text: '[OK] ELO rating system', delay: 550, style: 'success' },
  { text: '[OK] Continuum memory (4-tier)', delay: 650, style: 'success' },
  { text: '[OK] Calibration tracker', delay: 750, style: 'success' },
  { text: '[OK] WebSocket streaming', delay: 850, style: 'success' },
  { text: '', delay: 900, style: 'normal' },
  { text: '[INIT] Connecting AI agents...', delay: 950, style: 'system' },
  { text: '', delay: 1000, style: 'normal' },
  { text: '  ┌─ ANTHROPIC ──────────────────────────────┐', delay: 1050, style: 'provider' },
  { text: '  │  Claude Opus 4.5................ READY   │', delay: 1100, style: 'agent' },
  { text: '  │  Claude Sonnet 4................ READY   │', delay: 1150, style: 'agent' },
  { text: '  │  Claude Haiku 3.5............... READY   │', delay: 1200, style: 'agent' },
  { text: '  └──────────────────────────────────────────┘', delay: 1250, style: 'provider' },
  { text: '', delay: 1300, style: 'normal' },
  { text: '  ┌─ OPENAI ─────────────────────────────────┐', delay: 1350, style: 'provider' },
  { text: '  │  GPT-5.2........................ READY   │', delay: 1400, style: 'agent' },
  { text: '  │  GPT-4o......................... READY   │', delay: 1450, style: 'agent' },
  { text: '  │  o1............................. READY   │', delay: 1500, style: 'agent' },
  { text: '  └──────────────────────────────────────────┘', delay: 1550, style: 'provider' },
  { text: '', delay: 1600, style: 'normal' },
  { text: '  ┌─ GOOGLE ─────────────────────────────────┐', delay: 1650, style: 'provider' },
  { text: '  │  Gemini 2.0 Pro................. READY   │', delay: 1700, style: 'agent' },
  { text: '  │  Gemini 2.0 Flash............... READY   │', delay: 1750, style: 'agent' },
  { text: '  └──────────────────────────────────────────┘', delay: 1800, style: 'provider' },
  { text: '', delay: 1850, style: 'normal' },
  { text: '  ┌─ XAI ────────────────────────────────────┐', delay: 1900, style: 'provider' },
  { text: '  │  Grok 4......................... READY   │', delay: 1950, style: 'agent' },
  { text: '  │  Grok 3......................... READY   │', delay: 2000, style: 'agent' },
  { text: '  └──────────────────────────────────────────┘', delay: 2050, style: 'provider' },
  { text: '', delay: 2100, style: 'normal' },
  { text: '  ┌─ MISTRAL ────────────────────────────────┐', delay: 2150, style: 'provider' },
  { text: '  │  Mistral Large 2................ READY   │', delay: 2200, style: 'agent' },
  { text: '  │  Codestral...................... READY   │', delay: 2250, style: 'agent' },
  { text: '  └──────────────────────────────────────────┘', delay: 2300, style: 'provider' },
  { text: '', delay: 2350, style: 'normal' },
  { text: '  ┌─ OPENROUTER (fallback) ──────────────────┐', delay: 2400, style: 'provider' },
  { text: '  │  DeepSeek V3.2.................. READY   │', delay: 2450, style: 'agent' },
  { text: '  │  Qwen 3......................... READY   │', delay: 2500, style: 'agent' },
  { text: '  │  Llama 4 70B.................... READY   │', delay: 2550, style: 'agent' },
  { text: '  │  Yi-Large....................... READY   │', delay: 2600, style: 'agent' },
  { text: '  │  Kimi (Moonshot)................ READY   │', delay: 2650, style: 'agent' },
  { text: '  └──────────────────────────────────────────┘', delay: 2700, style: 'provider' },
  { text: '', delay: 2750, style: 'normal' },
  { text: '[OK] 20+ models across 7 providers online', delay: 2800, style: 'success' },
  { text: '', delay: 2850, style: 'normal' },
  { text: '[INIT] Starting nomic loop...', delay: 2900, style: 'system' },
  { text: '[OK] API endpoints (1285+) mounted', delay: 3000, style: 'success' },
  { text: '[OK] Real-time event streaming active', delay: 3100, style: 'success' },
  { text: '', delay: 3150, style: 'normal' },
  { text: '═══════════════════════════════════════════════', delay: 3200, style: 'divider' },
  { text: 'SYSTEM READY', delay: 3300, style: 'ready' },
  { text: '', delay: 3400, style: 'normal' },
];

export function BootSequence({ onComplete, skip = false }: BootSequenceProps) {
  const [visibleLines, setVisibleLines] = useState<number>(0);
  const [showCursor, setShowCursor] = useState(true);
  const [isComplete, setIsComplete] = useState(false);

  // Guard to prevent onComplete from being called multiple times
  const hasCompletedRef = useRef(false);

  // Handle skip - any key or click skips immediately
  const handleSkip = useCallback(() => {
    if (hasCompletedRef.current) return;
    hasCompletedRef.current = true;
    onComplete();
  }, [onComplete]);

  // Skip boot sequence if requested via prop
  useEffect(() => {
    if (skip) {
      if (hasCompletedRef.current) return;
      hasCompletedRef.current = true;
      onComplete();
    }
  }, [skip, onComplete]);

  // Listen for keypress or click to skip at ANY time
  useEffect(() => {
    if (skip) return;

    const handleKeyDown = (_e: KeyboardEvent) => {
      // Skip on any key
      handleSkip();
    };

    const handleClick = () => {
      handleSkip();
    };

    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('click', handleClick);

    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('click', handleClick);
    };
  }, [skip, handleSkip]);

  // Reveal lines progressively
  useEffect(() => {
    if (skip) return;

    const timers: NodeJS.Timeout[] = [];

    BOOT_LINES.forEach((line, index) => {
      const timer = setTimeout(() => {
        setVisibleLines(index + 1);
        if (index === BOOT_LINES.length - 1) {
          setIsComplete(true);
        }
      }, line.delay);
      timers.push(timer);
    });

    return () => timers.forEach(clearTimeout);
  }, [skip]);

  // Cursor blink
  useEffect(() => {
    const interval = setInterval(() => {
      setShowCursor((prev) => !prev);
    }, 500);
    return () => clearInterval(interval);
  }, []);

  // Auto-continue after completion
  useEffect(() => {
    if (!isComplete) return;

    const autoTimer = setTimeout(() => {
      if (hasCompletedRef.current) return;
      hasCompletedRef.current = true;
      onComplete();
    }, 1500);

    return () => clearTimeout(autoTimer);
  }, [isComplete, onComplete]);

  if (skip) return null;

  const getLineStyle = (style: string) => {
    switch (style) {
      case 'title':
        return 'text-[var(--accent)] font-bold text-lg glow-text';
      case 'divider':
        return 'text-[var(--accent)]/50';
      case 'system':
        return 'text-[var(--acid-cyan)]';
      case 'success':
        return 'text-[var(--accent)]';
      case 'provider':
        return 'text-[var(--acid-cyan)]/70';
      case 'agent':
        return 'text-text/80';
      case 'ready':
        return 'text-[var(--accent)] font-bold glow-text animate-pulse';
      case 'prompt':
        return 'text-[var(--acid-yellow)]';
      default:
        return 'text-text';
    }
  };

  return (
    <div
      className="fixed inset-0 bg-bg z-50 flex items-center justify-center cursor-pointer"
      role="button"
      tabIndex={0}
      aria-label="Boot sequence animation. Press any key or click to skip."
      onClick={handleSkip}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          handleSkip();
        }
      }}
    >
      <div className="max-w-2xl w-full p-8 font-theme-data text-sm">
        {/* Skip hint at top */}
        <div
          className="text-center mb-4 text-[var(--acid-yellow)]/60 text-xs animate-pulse"
          aria-hidden="true"
        >
          Press any key or click to skip...
        </div>

        {BOOT_LINES.slice(0, visibleLines).map((line, index) => (
          <div
            key={index}
            className={`${getLineStyle(line.style)} boot-line`}
            style={{ animationDelay: `${index * 0.02}s` }}
          >
            {line.text}
            {index === visibleLines - 1 && !isComplete && (
              <span className={showCursor ? 'opacity-100' : 'opacity-0'}>_</span>
            )}
          </div>
        ))}

        {isComplete && (
          <div className="mt-4">
            <span className="text-[var(--accent)]">
              {'>'}
              <span className={showCursor ? 'opacity-100' : 'opacity-0'}>_</span>
            </span>
          </div>
        )}
      </div>

      {/* Scanline overlay */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background: `repeating-linear-gradient(
            0deg,
            rgba(0, 0, 0, 0.1),
            rgba(0, 0, 0, 0.1) 1px,
            transparent 1px,
            transparent 2px
          )`,
        }}
      />
    </div>
  );
}

// Mini boot animation for component loading
export function MiniLoader({ text = 'Loading' }: { text?: string }) {
  const [dots, setDots] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setDots((prev) => (prev + 1) % 4);
    }, 300);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex items-center gap-2 font-theme-data text-sm text-[var(--accent)]">
      <span className="animate-pulse">{'>'}</span>
      <span>{text}</span>
      <span className="w-6">{'.'.repeat(dots)}</span>
    </div>
  );
}
