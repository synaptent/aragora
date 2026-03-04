'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useTheme } from '@/context/ThemeContext';
import { Logo } from '@/components/Logo';
import { ThemeSelector } from './ThemeSelector';

const NAV_LINKS = [
  { href: '#how-it-works', label: 'How it works', anchor: true },
  { href: '/quickstart', label: 'Quickstart', anchor: false },
  { href: '/docs', label: 'Docs', anchor: false },
  { href: '/oracle', label: 'Oracle', anchor: false },
  { href: '/pricing', label: 'Pricing', anchor: false },
  { href: '/login', label: 'Log in', anchor: false },
];

export function Header() {
  const { theme } = useTheme();
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  // Close menu on route change
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  // Close on Escape
  useEffect(() => {
    if (!mobileOpen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMobileOpen(false);
    };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [mobileOpen]);

  // Prevent body scroll when menu open
  useEffect(() => {
    if (mobileOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => { document.body.style.overflow = ''; };
  }, [mobileOpen]);

  const toggleMenu = useCallback(() => setMobileOpen((o) => !o), []);

  const bgColor = theme === 'dark'
    ? 'rgba(10,10,10,0.85)'
    : theme === 'professional'
      ? 'rgba(255,255,255,0.85)'
      : 'rgba(250,249,247,0.85)';

  return (
    <>
      <header
        className="sticky top-0 z-50 backdrop-blur-sm"
        style={{
          backgroundColor: bgColor,
          borderBottom: '1px solid var(--border)',
          fontFamily: 'var(--font-landing)',
        }}
      >
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between">
          {/* Logo mark + Wordmark */}
          <div className="flex items-center gap-3">
            <Logo size="lg" pixelSize={28} />
            <Link href="/landing" className="flex items-center">
              <span
                className="font-bold"
                style={{
                  color: 'var(--accent)',
                  fontSize: '14px',
                  fontFamily: "'JetBrains Mono', monospace",
                  letterSpacing: '0.15em',
                }}
              >
                {'> ARAGORA'}
              </span>
            </Link>
          </div>

          {/* Desktop nav + Theme selector */}
          <div className="flex items-center gap-6">
            <nav className="hidden sm:flex items-center gap-5">
              {NAV_LINKS.map((link) =>
                link.anchor ? (
                  <a
                    key={link.href}
                    href={link.href}
                    className="text-sm transition-colors hover:opacity-80"
                    style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-landing)' }}
                  >
                    {link.label}
                  </a>
                ) : (
                  <Link
                    key={link.href}
                    href={link.href}
                    className="text-sm transition-colors hover:opacity-80"
                    style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-landing)' }}
                  >
                    {link.label}
                  </Link>
                ),
              )}
            </nav>
            <ThemeSelector />

            {/* Mobile hamburger */}
            <button
              className="sm:hidden flex flex-col justify-center items-center w-8 h-8 gap-[5px] cursor-pointer"
              onClick={toggleMenu}
              aria-label={mobileOpen ? 'Close menu' : 'Open menu'}
              aria-expanded={mobileOpen}
              style={{ background: 'none', border: 'none', padding: 0 }}
            >
              <span
                className="block w-5 h-[1.5px] transition-all duration-200 origin-center"
                style={{
                  backgroundColor: 'var(--text-muted)',
                  transform: mobileOpen ? 'translateY(3.25px) rotate(45deg)' : 'none',
                }}
              />
              <span
                className="block w-5 h-[1.5px] transition-all duration-200 origin-center"
                style={{
                  backgroundColor: 'var(--text-muted)',
                  transform: mobileOpen ? 'translateY(-3.25px) rotate(-45deg)' : 'none',
                }}
              />
            </button>
          </div>
        </div>
      </header>

      {/* Mobile nav overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 sm:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden="true"
          style={{ backgroundColor: 'rgba(0,0,0,0.3)' }}
        />
      )}

      {/* Mobile nav panel */}
      <div
        className="fixed left-0 right-0 z-45 sm:hidden overflow-hidden transition-all duration-250 ease-out"
        style={{
          top: '57px', // header height
          maxHeight: mobileOpen ? '400px' : '0',
          opacity: mobileOpen ? 1 : 0,
          backgroundColor: bgColor,
          backdropFilter: 'blur(12px)',
          WebkitBackdropFilter: 'blur(12px)',
          borderBottom: mobileOpen ? '1px solid var(--border)' : 'none',
          zIndex: 45,
        }}
      >
        <nav
          className="max-w-5xl mx-auto px-4 py-4 flex flex-col gap-1"
          style={{ fontFamily: 'var(--font-landing)' }}
        >
          {NAV_LINKS.map((link) => {
            const isActive = !link.anchor && pathname === link.href;
            const linkStyle = {
              color: isActive ? 'var(--accent)' : 'var(--text-muted)',
              fontFamily: 'var(--font-landing)',
              fontSize: '15px',
              padding: '12px 8px',
              borderRadius: 'var(--radius-card)',
              backgroundColor: isActive ? 'var(--surface)' : 'transparent',
              display: 'block',
              transition: 'background-color 0.15s, color 0.15s',
            };

            return link.anchor ? (
              <a
                key={link.href}
                href={link.href}
                onClick={() => setMobileOpen(false)}
                style={linkStyle}
              >
                {link.label}
              </a>
            ) : (
              <Link
                key={link.href}
                href={link.href}
                onClick={() => setMobileOpen(false)}
                style={linkStyle}
              >
                {link.label}
              </Link>
            );
          })}

          {/* Divider */}
          <div style={{ height: '1px', backgroundColor: 'var(--border)', margin: '4px 8px' }} />

          {/* Sign up CTA */}
          <Link
            href="/signup"
            onClick={() => setMobileOpen(false)}
            className="text-center font-semibold transition-opacity hover:opacity-80"
            style={{
              fontSize: '14px',
              fontFamily: 'var(--font-landing)',
              borderRadius: 'var(--radius-button)',
              backgroundColor: 'var(--accent)',
              color: 'var(--bg)',
              padding: '12px 24px',
              margin: '4px 8px',
            }}
          >
            Sign up free
          </Link>
        </nav>
      </div>
    </>
  );
}
