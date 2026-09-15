import type { Metadata } from 'next';
import Link from 'next/link';
import './globals.css';

export const metadata: Metadata = {
  title: 'Aragora - Multi-Agent Debate Platform',
  description: 'Orchestrate AI debates for defensible decisions',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <nav className="navbar">
          <Link href="/" className="logo">Aragora</Link>
          <div className="nav-links">
            <Link href="/debates">Debates</Link>
            <Link href="/debates/new">New Debate</Link>
          </div>
        </nav>
        <main className="container">
          {children}
        </main>
      </body>
    </html>
  );
}
