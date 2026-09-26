'use client';

import { BatchDebatePanel } from '@/components/BatchDebatePanel';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';

export default function BatchPage() {
  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />
      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Content */}
        <div className="container mx-auto px-4 py-8">
          {/* Page Title */}
          <div className="mb-6">
            <h1 className="text-xl font-theme-data text-[var(--accent)] mb-2">
              {'>'} BATCH DEBATE OPERATIONS
            </h1>
            <p className="text-sm font-theme-data text-text-muted">
              Submit multiple debates for parallel processing. Monitor progress and view results.
            </p>
          </div>

          {/* Main Panel */}
          <div className="max-w-4xl">
            <BatchDebatePanel />
          </div>

          {/* Help Section */}
          <div className="mt-8 max-w-4xl">
            <details className="group">
              <summary className="text-xs font-theme-data text-text-muted cursor-pointer hover:text-[var(--accent)]">
                [?] BATCH SUBMISSION GUIDE
              </summary>
              <div className="mt-4 p-4 bg-surface/50 border border-[var(--accent)]/20 text-xs font-theme-data text-text-muted space-y-4">
                <div>
                  <div className="text-[var(--accent)] mb-1">TEXT MODE</div>
                  <p>
                    Enter one question per line. Each line becomes a separate debate with default
                    settings.
                  </p>
                </div>
                <div>
                  <div className="text-[var(--accent)] mb-1">JSON MODE</div>
                  <p>For advanced configuration, use JSON format:</p>
                  <pre className="mt-2 p-2 bg-bg rounded overflow-x-auto">
                    {`[
  {
    "question": "What is the best database?",
    "agents": "claude,gpt-4o,gemini",
    "rounds": 3,
    "priority": 1
  },
  {
    "question": "Is AI safe?",
    "agents": "anthropic-api,openai-api"
  }
]`}
                  </pre>
                </div>
                <div>
                  <div className="text-[var(--accent)] mb-1">WEBHOOK NOTIFICATIONS</div>
                  <p>
                    Configure a webhook URL to receive POST notifications when the batch completes.
                  </p>
                </div>
                <div>
                  <div className="text-[var(--accent)] mb-1">LIMITS</div>
                  <ul className="list-disc list-inside">
                    <li>Maximum 1000 items per batch</li>
                    <li>Questions up to 10,000 characters</li>
                    <li>Processing is subject to your plan quota</li>
                  </ul>
                </div>
              </div>
            </details>
          </div>
        </div>
      </main>
    </>
  );
}
