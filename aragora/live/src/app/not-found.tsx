import Link from 'next/link';

export default function NotFound() {
  return (
    <div className="min-h-screen bg-bg flex items-center justify-center p-4">
      <div className="max-w-md w-full border border-warning bg-surface p-6 font-theme-data">
        <div className="text-center mb-6">
          <div className="text-warning text-4xl mb-3">404</div>
          <h1 className="text-warning font-bold text-lg mb-2">PAGE NOT FOUND</h1>
          <p className="text-text-muted text-sm">This page doesn&apos;t exist or has been moved.</p>
        </div>

        <div className="bg-bg border border-border p-4 mb-6 text-sm">
          <div className="mb-3 text-text font-bold text-xs">POPULAR PAGES</div>
          <ul className="space-y-2">
            <li>
              <Link href="/" className="text-[var(--accent)] hover:underline">
                Home — Run a free debate
              </Link>
            </li>
            <li>
              <Link href="/oracle" className="text-[var(--accent)] hover:underline">
                Oracle — Live streaming mode
              </Link>
            </li>
            <li>
              <Link href="/debates" className="text-[var(--accent)] hover:underline">
                Debates — Past decisions
              </Link>
            </li>
            <li>
              <Link href="/dashboard" className="text-[var(--accent)] hover:underline">
                Dashboard — Your account
              </Link>
            </li>
          </ul>
        </div>

        <Link
          href="/"
          className="block w-full border border-[var(--accent)] text-[var(--accent)] py-2 px-4 hover:bg-[var(--accent)] hover:text-bg transition-colors font-bold text-center text-sm"
        >
          GO HOME
        </Link>
      </div>
    </div>
  );
}
