'use client';

import { useEffect, useRef, useState } from 'react';

interface MatrixRainProps {
  opacity?: number;
  speed?: number;
  density?: number;
  color?: string;
}

export function MatrixRain({
  opacity = 0.03,
  speed = 1,
  density = 0.02,
  color = '#39ff14',
}: MatrixRainProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;

    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Set canvas size
    const resize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };
    resize();
    window.addEventListener('resize', resize);

    // Characters to use (mix of ASCII and katakana-like symbols)
    const chars = 'ARAGORA01アイウエオカキクケコ><{}[]|/\\-=+*#@$%&'.split('');

    // Columns
    const fontSize = 14;
    const columns = Math.floor(canvas.width / fontSize);

    // Drops - one per column
    const drops: number[] = Array(columns).fill(1);

    // Initialize random starting positions
    for (let i = 0; i < drops.length; i++) {
      drops[i] = Math.random() * -100;
    }

    // Draw function
    const draw = () => {
      // Fade effect
      ctx.fillStyle = 'rgba(10, 10, 10, 0.05)';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      // Set color and font
      ctx.fillStyle = color;
      ctx.font = `${fontSize}px JetBrains Mono, monospace`;

      // Draw characters
      for (let i = 0; i < drops.length; i++) {
        // Random character
        const char = chars[Math.floor(Math.random() * chars.length)];

        // x = column number * font size
        const x = i * fontSize;
        // y = drop position * font size
        const y = drops[i] * fontSize;

        // Only draw if on screen and random density check
        if (y > 0 && Math.random() < 0.8) {
          // Varying opacity for depth effect
          const charOpacity = Math.random() * 0.5 + 0.5;
          ctx.fillStyle = color.replace(')', `, ${charOpacity})`).replace('rgb', 'rgba');
          ctx.fillText(char, x, y);
        }

        // Reset drop to top with random delay
        if (y > canvas.height && Math.random() > 0.975) {
          drops[i] = 0;
        }

        // Move drop down
        drops[i] += speed * (0.5 + Math.random() * 0.5);
      }
    };

    // Animation loop
    let animationId: number;
    const animate = () => {
      draw();
      animationId = requestAnimationFrame(animate);
    };

    // Start with delay for performance
    const timeout = setTimeout(() => {
      animate();
    }, 100);

    return () => {
      window.removeEventListener('resize', resize);
      clearTimeout(timeout);
      cancelAnimationFrame(animationId);
    };
  }, [mounted, speed, density, color]);

  if (!mounted) return null;

  return (
    <canvas ref={canvasRef} className="fixed inset-0 pointer-events-none z-0" style={{ opacity }} />
  );
}

// Simpler CSS-based scanlines for performance
export function Scanlines({ opacity = 0.03 }: { opacity?: number }) {
  return (
    <div
      className="fixed inset-0 pointer-events-none z-[9999]"
      style={{
        background: `repeating-linear-gradient(
          0deg,
          rgba(0, 0, 0, ${opacity}),
          rgba(0, 0, 0, ${opacity}) 1px,
          transparent 1px,
          transparent 2px
        )`,
      }}
    />
  );
}

// CRT corner vignette effect (reduced intensity)
export function CRTVignette() {
  return (
    <div
      className="fixed inset-0 pointer-events-none z-[9998]"
      style={{
        background: `radial-gradient(
          ellipse at center,
          transparent 0%,
          transparent 60%,
          rgba(0, 0, 0, 0.15) 100%
        )`,
      }}
    />
  );
}

// Subtle flicker effect wrapper
export function FlickerWrapper({ children }: { children: React.ReactNode }) {
  return <div className="crt-flicker">{children}</div>;
}
