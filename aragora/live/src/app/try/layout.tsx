import Link from 'next/link';

export default function TryLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[var(--bg)] text-[var(--text)]">
      {/* Minimal Header */}
      <header className="h-12 border-b border-[var(--acid-green)]/20 bg-[var(--surface)]/50 flex items-center justify-between px-4">
        <Link href="/" className="flex items-center gap-2">
          <span className="text-sm font-theme-data font-bold text-[var(--acid-green)]">
            ARAGORA
          </span>
          <span className="text-xs font-theme-data text-[var(--text-muted)]">{'// LIVE'}</span>
        </Link>
        <div className="flex items-center gap-2">
          <Link
            href="/login"
            className="px-3 py-1 text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
          >
            SIGN IN
          </Link>
          <Link
            href="/signup"
            className="px-3 py-1 text-xs font-theme-data bg-[var(--acid-green)] text-[var(--bg)] hover:bg-[var(--acid-green)]/80 transition-colors font-bold"
          >
            SIGN UP FREE
          </Link>
        </div>
      </header>

      <main>{children}</main>
    </div>
  );
}
