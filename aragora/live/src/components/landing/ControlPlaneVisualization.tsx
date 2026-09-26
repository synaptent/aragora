'use client';

import { SectionHeader } from './SectionHeader';

const DATA_SOURCES = [
  { icon: '[]', label: 'Documents', count: '25+ formats' },
  { icon: '{}', label: 'APIs', count: 'REST/GraphQL' },
  { icon: '()', label: 'Databases', count: 'SQL/NoSQL' },
  { icon: '<>', label: 'Cloud', count: 'S3/GCS/Azure' },
];

const MODELS = [
  { name: 'Claude', color: 'text-orange-400' },
  { name: 'GPT-4', color: 'text-green-400' },
  { name: 'Gemini', color: 'text-blue-400' },
  { name: 'Mistral', color: 'text-purple-400' },
  { name: '+11 more', color: 'text-text-muted' },
];

const CHANNELS = [
  { icon: '#', label: 'Slack' },
  { icon: '@', label: 'Teams' },
  { icon: '!', label: 'Discord' },
  { icon: '>', label: 'Email' },
  { icon: '+', label: '20 more' },
];

/**
 * ControlPlaneVisualization - Visual diagram showing the control plane architecture.
 *
 * Displays the data flow: Sources → AI Debate → Decisions → Channels
 * to reinforce the orchestration and governance positioning.
 */
export function ControlPlaneVisualization() {
  return (
    <section className="py-12 border-t border-[var(--accent)]/20">
      <div className="container mx-auto px-4">
        <SectionHeader title="PLATFORM ARCHITECTURE" />
        <p className="text-text-muted font-theme-data text-xs text-center mb-8 max-w-xl mx-auto">
          How Aragora connects your data sources, debates your questions, and delivers decisions to
          your channels.
        </p>

        {/* Main Flow Visualization */}
        <div className="max-w-5xl mx-auto">
          {/* Desktop Layout */}
          <div className="hidden md:flex items-stretch justify-center gap-2">
            {/* Data Sources */}
            <div className="flex-1 max-w-[180px]">
              <div className="border border-[var(--acid-cyan)]/40 rounded-lg p-4 bg-surface/30 h-full">
                <div className="text-[var(--acid-cyan)] font-theme-data text-xs font-bold mb-3 text-center">
                  [SOURCES]
                </div>
                <div className="space-y-2">
                  {DATA_SOURCES.map((source) => (
                    <div key={source.label} className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-[var(--acid-cyan)] font-theme-data text-xs">
                          {source.icon}
                        </span>
                        <span className="text-text text-xs font-theme-data">{source.label}</span>
                      </div>
                      <span className="text-text-muted text-[10px] font-theme-data">
                        {source.count}
                      </span>
                    </div>
                  ))}
                </div>
                <div className="mt-3 pt-3 border-t border-border/50 text-center">
                  <span className="text-[var(--acid-cyan)] font-theme-data text-lg font-bold">
                    25+
                  </span>
                  <div className="text-text-muted text-[10px] font-theme-data">formats</div>
                </div>
              </div>
            </div>

            {/* Arrow */}
            <div className="flex items-center px-2">
              <div className="text-[var(--accent)] font-theme-data text-xl animate-pulse">→</div>
            </div>

            {/* Control Plane Core */}
            <div className="flex-1 max-w-[220px]">
              <div className="border-2 border-[var(--accent)]/60 rounded-lg p-4 bg-[var(--accent)]/5 h-full">
                <div className="text-[var(--accent)] font-theme-data text-xs font-bold mb-3 text-center">
                  [PLATFORM]
                </div>

                {/* Orchestration */}
                <div className="bg-surface/50 rounded p-2 mb-2">
                  <div className="text-[var(--accent)] font-theme-data text-[10px] mb-1">
                    ORCHESTRATION
                  </div>
                  <div className="text-text-muted text-[10px] font-theme-data">
                    Route tasks to optimal models
                  </div>
                </div>

                {/* Governance */}
                <div className="bg-surface/50 rounded p-2 mb-2">
                  <div className="text-[var(--acid-yellow)] font-theme-data text-[10px] mb-1">
                    GOVERNANCE
                  </div>
                  <div className="text-text-muted text-[10px] font-theme-data">
                    Enforce policies &amp; compliance
                  </div>
                </div>

                {/* Memory */}
                <div className="bg-surface/50 rounded p-2">
                  <div className="text-[var(--acid-cyan)] font-theme-data text-[10px] mb-1">
                    MEMORY
                  </div>
                  <div className="text-text-muted text-[10px] font-theme-data">
                    4-tier learning continuum
                  </div>
                </div>
              </div>
            </div>

            {/* Arrow */}
            <div className="flex items-center px-2">
              <div className="text-[var(--accent)] font-theme-data text-xl animate-pulse">→</div>
            </div>

            {/* AI Debate Engine */}
            <div className="flex-1 max-w-[180px]">
              <div className="border border-acid-yellow/40 rounded-lg p-4 bg-surface/30 h-full">
                <div className="text-[var(--acid-yellow)] font-theme-data text-xs font-bold mb-3 text-center">
                  [AI DEBATE]
                </div>
                <div className="space-y-1 mb-3">
                  {MODELS.map((model) => (
                    <div key={model.name} className="flex items-center gap-2">
                      <span
                        className={`w-1.5 h-1.5 rounded-full ${model.color.replace('text-', 'bg-')}`}
                      />
                      <span className={`text-xs font-theme-data ${model.color}`}>{model.name}</span>
                    </div>
                  ))}
                </div>
                <div className="pt-3 border-t border-border/50 text-center">
                  <span className="text-[var(--acid-yellow)] font-theme-data text-lg font-bold">
                    15+
                  </span>
                  <div className="text-text-muted text-[10px] font-theme-data">models</div>
                </div>
              </div>
            </div>

            {/* Arrow */}
            <div className="flex items-center px-2">
              <div className="text-[var(--accent)] font-theme-data text-xl animate-pulse">→</div>
            </div>

            {/* Channels */}
            <div className="flex-1 max-w-[180px]">
              <div className="border border-acid-magenta/40 rounded-lg p-4 bg-surface/30 h-full">
                <div className="text-[var(--acid-magenta)] font-theme-data text-xs font-bold mb-3 text-center">
                  [CHANNELS]
                </div>
                <div className="space-y-2">
                  {CHANNELS.map((channel) => (
                    <div key={channel.label} className="flex items-center gap-2">
                      <span className="text-[var(--acid-magenta)] font-theme-data text-xs">
                        {channel.icon}
                      </span>
                      <span className="text-text text-xs font-theme-data">{channel.label}</span>
                    </div>
                  ))}
                </div>
                <div className="mt-3 pt-3 border-t border-border/50 text-center">
                  <span className="text-[var(--acid-magenta)] font-theme-data text-lg font-bold">
                    24+
                  </span>
                  <div className="text-text-muted text-[10px] font-theme-data">integrations</div>
                </div>
              </div>
            </div>
          </div>

          {/* Mobile Layout - Vertical */}
          <div className="md:hidden space-y-4">
            {/* Sources */}
            <div className="border border-[var(--acid-cyan)]/40 rounded-lg p-4 bg-surface/30">
              <div className="text-[var(--acid-cyan)] font-theme-data text-xs font-bold mb-2">
                [SOURCES] 25+ formats
              </div>
              <div className="flex flex-wrap gap-2">
                {DATA_SOURCES.map((s) => (
                  <span key={s.label} className="text-xs font-theme-data text-text-muted">
                    {s.label}
                  </span>
                ))}
              </div>
            </div>

            <div className="text-center text-[var(--accent)] font-theme-data">↓</div>

            {/* Control Plane */}
            <div className="border-2 border-[var(--accent)]/60 rounded-lg p-4 bg-[var(--accent)]/5">
              <div className="text-[var(--accent)] font-theme-data text-xs font-bold mb-2">
                [PLATFORM]
              </div>
              <div className="flex flex-wrap gap-2 text-xs font-theme-data text-text-muted">
                <span>Orchestration</span>
                <span>|</span>
                <span>Governance</span>
                <span>|</span>
                <span>Memory</span>
              </div>
            </div>

            <div className="text-center text-[var(--accent)] font-theme-data">↓</div>

            {/* AI Debate */}
            <div className="border border-acid-yellow/40 rounded-lg p-4 bg-surface/30">
              <div className="text-[var(--acid-yellow)] font-theme-data text-xs font-bold mb-2">
                [AI DEBATE] 15+ models
              </div>
              <div className="flex flex-wrap gap-2">
                {MODELS.slice(0, 4).map((m) => (
                  <span key={m.name} className={`text-xs font-theme-data ${m.color}`}>
                    {m.name}
                  </span>
                ))}
              </div>
            </div>

            <div className="text-center text-[var(--accent)] font-theme-data">↓</div>

            {/* Channels */}
            <div className="border border-acid-magenta/40 rounded-lg p-4 bg-surface/30">
              <div className="text-[var(--acid-magenta)] font-theme-data text-xs font-bold mb-2">
                [CHANNELS] 24+ integrations
              </div>
              <div className="flex flex-wrap gap-2">
                {CHANNELS.slice(0, 4).map((c) => (
                  <span key={c.label} className="text-xs font-theme-data text-text-muted">
                    {c.label}
                  </span>
                ))}
              </div>
            </div>
          </div>

          {/* Output: Decision Receipt */}
          <div className="mt-6 border border-[var(--accent)]/40 rounded-lg p-4 bg-surface/30 max-w-md mx-auto">
            <div className="flex items-center justify-between mb-2">
              <div className="text-[var(--accent)] font-theme-data text-xs font-bold">
                [OUTPUT] DECISION RECEIPT
              </div>
              <span className="px-2 py-0.5 text-[10px] font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] rounded">
                AUDIT-READY
              </span>
            </div>
            <div className="grid grid-cols-3 gap-2 text-center">
              <div>
                <div className="text-[var(--acid-cyan)] text-xs font-theme-data">Verdict</div>
                <div className="text-text-muted text-[10px] font-theme-data">+ Confidence</div>
              </div>
              <div>
                <div className="text-[var(--acid-yellow)] text-xs font-theme-data">Findings</div>
                <div className="text-text-muted text-[10px] font-theme-data">+ Evidence</div>
              </div>
              <div>
                <div className="text-[var(--acid-magenta)] text-xs font-theme-data">Dissent</div>
                <div className="text-text-muted text-[10px] font-theme-data">+ Audit Trail</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

export default ControlPlaneVisualization;
