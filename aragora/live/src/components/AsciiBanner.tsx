'use client';

import { useState, useEffect } from 'react';
import { Logo } from './Logo';

interface AsciiBannerProps {
  subtitle?: string;
  showStatus?: boolean;
  connected?: boolean;
}

export function AsciiBanner({
  subtitle = 'live',
  showStatus = true,
  connected = false,
}: AsciiBannerProps) {
  const [mounted, setMounted] = useState(false);
  const [glitchIndex, setGlitchIndex] = useState(-1);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Occasional glitch effect
  useEffect(() => {
    if (!mounted) return;
    const interval = setInterval(() => {
      if (Math.random() > 0.95) {
        setGlitchIndex(Math.floor(Math.random() * 7));
        setTimeout(() => setGlitchIndex(-1), 100);
      }
    }, 500);
    return () => clearInterval(interval);
  }, [mounted]);

  const lines = [
    '    _    ____      _    ____  ___  ____      _    ',
    '   / \\  |  _ \\    / \\  / ___|/ _ \\|  _ \\    / \\   ',
    '  / _ \\ | |_) |  / _ \\| |  _| | | | |_) |  / _ \\  ',
    ' / ___ \\|  _ <  / ___ \\ |_| | |_| |  _ <  / ___ \\ ',
    '/_/   \\_\\_| \\_\\/_/   \\_\\____|\\___/|_| \\_\\/_/   \\_\\',
  ];

  const glitchChars = ['#', '@', '%', '&', '*', '!', '?'];

  const getGlitchedLine = (line: string, lineIndex: number) => {
    if (glitchIndex !== lineIndex) return line;
    const chars = line.split('');
    const pos = Math.floor(Math.random() * chars.length);
    chars[pos] = glitchChars[Math.floor(Math.random() * glitchChars.length)];
    return chars.join('');
  };

  if (!mounted) {
    return <div className="h-32" />;
  }

  return (
    <div className="relative">
      {/* ASCII Logo */}
      <pre className="font-theme-data text-[10px] sm:text-xs md:text-sm leading-tight text-center select-none">
        {lines.map((line, i) => (
          <div
            key={i}
            className="glow-text-subtle text-[var(--accent)]"
            style={{
              animationDelay: `${i * 0.1}s`,
              opacity: mounted ? 1 : 0,
              transition: `opacity 0.3s ease ${i * 0.1}s`,
            }}
          >
            {getGlitchedLine(line, i)}
          </div>
        ))}
      </pre>

      {/* Subtitle */}
      <div className="text-center mt-2 space-y-1">
        <span className="text-[var(--acid-cyan)] text-xs tracking-[0.5em] uppercase font-bold">
          {subtitle}
        </span>

        {/* Status indicator */}
        {showStatus && (
          <div className="flex items-center justify-center gap-2 text-xs">
            <span
              className={`inline-block w-2 h-2 rounded-full ${
                connected ? 'bg-[var(--accent)] pulse-glow' : 'bg-[var(--crimson)]'
              }`}
            />
            <span className={connected ? 'text-[var(--accent)]' : 'text-[var(--crimson)]'}>
              {connected ? 'CONNECTED' : 'OFFLINE'}
            </span>
          </div>
        )}
      </div>

      {/* Decorative border */}
      <div className="mt-4 text-center text-[var(--accent)]/50 text-xs font-theme-data select-none">
        {'='.repeat(60)}
      </div>
    </div>
  );
}

// Compact version for header - matches [ARAGORA] styling from About page
export function AsciiBannerCompact({
  connected = false,
  showAsciiArt = false,
  showStatus = true,
  showLogo = true,
  onLogoClick,
}: {
  connected?: boolean;
  showAsciiArt?: boolean;
  showStatus?: boolean;
  showLogo?: boolean;
  onLogoClick?: () => void;
}) {
  return (
    <div className="flex items-center gap-3">
      {showLogo && <Logo size="sm" onClick={onLogoClick} />}
      {showAsciiArt && (
        <pre className="font-theme-data text-[8px] leading-none text-[var(--accent)] glow-text-subtle hidden sm:block">
          {`    _    ____
   / \\  |  _ \\
  / _ \\ | |_) |
 / ___ \\|  _ <
/_/   \\_\\_| \\_\\`}
        </pre>
      )}
      <span className="text-[var(--accent)] font-theme-data font-bold">[ARAGORA]</span>
      {showStatus && (
        <span
          className={`w-2 h-2 rounded-full ${
            connected ? 'bg-[var(--accent)] animate-pulse' : 'bg-[var(--crimson)]'
          }`}
        />
      )}
    </div>
  );
}
