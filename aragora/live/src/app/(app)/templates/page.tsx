'use client';

import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { TemplatePicker } from '@/components/templates/TemplatePicker';

export default function TemplatesPage() {
  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Hero */}
        <div className="border-b border-[var(--accent)]/20 bg-surface/30">
          <div className="container mx-auto px-4 py-12 text-center">
            <h1 className="text-3xl md:text-4xl font-theme-data text-[var(--accent)] mb-4">
              {'>'} DEBATE TEMPLATES
            </h1>
            <p className="text-text-muted font-theme-data max-w-2xl mx-auto">
              25 pre-built templates across 8 verticals. Choose a template, customize it for your
              context, and let AI agents stress-test your thinking.
            </p>
          </div>
        </div>

        <div className="container mx-auto px-4 py-8">
          <TemplatePicker />
        </div>
      </main>
    </>
  );
}
