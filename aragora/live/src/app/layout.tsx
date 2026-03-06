import type { Metadata, Viewport } from 'next';
import { JetBrains_Mono, Inter, DM_Serif_Display } from 'next/font/google';
import './globals.css';

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  display: 'swap',
  variable: '--font-jetbrains-mono',
});

const inter = Inter({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  display: 'swap',
  variable: '--font-inter',
});

const dmSerif = DM_Serif_Display({
  subsets: ['latin'],
  weight: ['400'],
  display: 'swap',
  variable: '--font-dm-serif',
});
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { AuthProvider } from '@/context/AuthContext';
import { ToastProvider } from '@/context/ToastContext';
import { ConnectionProvider } from '@/context/ConnectionContext';
import { DebateSelectionProvider } from '@/context/DebateSelectionContext';
import { ProgressiveModeProvider } from '@/context/ProgressiveModeContext';
import { AdaptiveModeProvider } from '@/context/AdaptiveModeContext';
import { LayoutProvider } from '@/context/LayoutContext';
import { RightSidebarProvider } from '@/context/RightSidebarContext';
import { SidebarProvider } from '@/context/SidebarContext';
import { ConfigHealthBanner } from '@/components/ConfigHealthBanner';
import { ConnectionStatusBanner } from '@/components/ConnectionStatusBanner';
import { CommandPaletteProvider } from '@/context/CommandPaletteContext';
import { CommandPalette } from '@/components/command-palette';
import { KeyboardShortcutsProvider } from '@/context/KeyboardShortcutsContext';
import { KeyboardShortcutsHelp } from '@/components/shortcuts';
import { ThemeProvider, themeInitScript } from '@/context/ThemeContext';

export const metadata: Metadata = {
  metadataBase: new URL('https://aragora.ai'),
  title: 'ARAGORA // LIVE',
  description: 'Multiple AI models debate your decisions. Ask any question and get a verdict with confidence scores, minority opinions, and a full audit trail.',
  keywords: ['AI', 'multi-agent', 'AI debate', 'decision making', 'debate', 'consensus', 'LLM', 'aragora', 'Claude', 'GPT', 'Gemini', 'Slack', 'Teams', 'Discord'],
  authors: [{ name: 'Aragora Team' }],
  manifest: '/manifest.json',
  appleWebApp: {
    capable: true,
    statusBarStyle: 'black-translucent',
    title: 'Aragora',
  },
  icons: {
    icon: [
      { url: '/favicon-32.png', sizes: '32x32', type: 'image/png' },
      { url: '/favicon-16.png', sizes: '16x16', type: 'image/png' },
    ],
    shortcut: '/favicon.ico',
    apple: '/icons/icon-152x152.png',
  },
  openGraph: {
    title: 'Aragora — AI Decision Intelligence',
    description: 'Multiple AI models debate your decisions. Confidence scores, minority opinions, and full audit trails.',
    type: 'website',
    siteName: 'Aragora',
    images: [{ url: '/screenshots/debate-desktop.png', width: 1920, height: 1080, alt: 'Aragora AI debate in action' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Aragora — AI Decision Intelligence',
    description: 'Multiple AI models debate your decisions. Confidence scores, minority opinions, and full audit trails.',
    images: ['/screenshots/debate-desktop.png'],
  },
};

// Viewport configuration - separate export in Next.js 14+
export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  themeColor: [
    { media: '(prefers-color-scheme: dark)', color: '#0a0a0a' },
    { media: '(prefers-color-scheme: light)', color: '#faf9f6' },
  ],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${jetbrainsMono.variable} ${inter.variable} ${dmSerif.variable}`} suppressHydrationWarning>
      <head>
        {/* Build SHA for deploy verification */}
        <meta name="aragora-build-sha" content={process.env.NEXT_PUBLIC_BUILD_SHA || 'unknown'} />
        <meta name="aragora-build-time" content={process.env.NEXT_PUBLIC_BUILD_TIME || ''} />
        {/* SSR-safe theme initialization - prevents flash of wrong theme */}
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="theme-transition">
        {/* Configuration health banner - shows warnings for missing env vars */}
        <ConfigHealthBanner />
        <ConnectionStatusBanner />
        {/* Skip to main content link for keyboard/screen reader users */}
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-50 focus:bg-background focus:text-accent focus:px-4 focus:py-2 focus:border focus:border-accent"
        >
          Skip to main content
        </a>
        <ThemeProvider>
          <AuthProvider>
            <ConnectionProvider>
              <DebateSelectionProvider>
                <ProgressiveModeProvider>
                  <AdaptiveModeProvider>
                    <SidebarProvider>
                      <LayoutProvider>
                        <RightSidebarProvider>
                          <CommandPaletteProvider>
                            <KeyboardShortcutsProvider>
                              <ToastProvider>
                                <ErrorBoundary>
                                  <CommandPalette />
                                  <KeyboardShortcutsHelp />
                                  {children}
                                </ErrorBoundary>
                              </ToastProvider>
                            </KeyboardShortcutsProvider>
                          </CommandPaletteProvider>
                        </RightSidebarProvider>
                      </LayoutProvider>
                    </SidebarProvider>
                  </AdaptiveModeProvider>
                </ProgressiveModeProvider>
              </DebateSelectionProvider>
            </ConnectionProvider>
          </AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
