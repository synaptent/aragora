'use client';

import { useTheme } from '@/context/ThemeContext';
import { BACKENDS, useBackend } from '../BackendSelector';
import { Header } from './Header';
import { HeroSection } from './HeroSection';
import { LiveDebatePanel } from './LiveDebatePanel';
import { LiveDemoSection } from './LiveDemoSection';
import { HowItWorksSection } from './HowItWorksSection';
import { ProblemSection } from './ProblemSection';
import { PricingSection } from './PricingSection';
import { Footer } from './Footer';

export interface LandingPageProps {
  /** Optional override for the live preview API base. */
  apiBase?: string;
  /** Optional override for the live preview WebSocket base. */
  wsUrl?: string;
  /** Callback fired when the user clicks "Log in" in the Header. When provided,
   *  this replaces the default Link-based navigation to /login. Useful for the
   *  inline landing page in HomePage where return-URL storage is needed before
   *  the redirect. */
  onEnterDashboard?: () => void;
}

export function LandingPage({ apiBase, wsUrl, onEnterDashboard }: LandingPageProps = {}) {
  const { theme } = useTheme();
  const { config: backendConfig } = useBackend();
  // An empty configured api means same-origin: local dev serves /api through the Next rewrite.
  const livePreviewApiBase = apiBase || (backendConfig.api ?? BACKENDS.production.api);
  const livePreviewWsUrl = wsUrl || backendConfig.ws || BACKENDS.production.ws;

  return (
    <div
      className="min-h-screen"
      style={{
        backgroundColor: 'var(--bg)',
        color: 'var(--text)',
        fontFamily: 'var(--font-landing)',
      }}
      data-landing-theme={theme}
    >
      <Header onLoginClick={onEnterDashboard} />
      <HeroSection />
      <LiveDebatePanel apiBase={livePreviewApiBase} wsUrl={livePreviewWsUrl} />
      <LiveDemoSection />
      <HowItWorksSection />
      <ProblemSection />
      <PricingSection />
      <Footer />
    </div>
  );
}
