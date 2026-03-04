'use client';

import { useTheme } from '@/context/ThemeContext';
import { Header } from './Header';
import { HeroSection } from './HeroSection';
import { HowItWorksSection } from './HowItWorksSection';
import { ProblemSection } from './ProblemSection';
import { FeatureShowcase } from './FeatureShowcase';
import { IntegrationsGrid } from './IntegrationsGrid';
import { OracleSection } from './OracleSection';
import { LiveDemoSection } from './LiveDemoSection';
import { PricingSection } from './PricingSection';
import { Footer } from './Footer';

export function LandingPage() {
  const { theme } = useTheme();

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
      <Header />
      <HeroSection />
      <HowItWorksSection />
      <ProblemSection />
      <FeatureShowcase />
      <IntegrationsGrid />
      <OracleSection />
      <LiveDemoSection />
      <PricingSection />
      <Footer />
    </div>
  );
}
