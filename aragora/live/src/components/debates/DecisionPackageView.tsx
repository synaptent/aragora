'use client';

interface DecisionPackage {
  status: string;
  debate_status: 'pending' | 'running' | 'blocked' | 'failed' | 'completed';
  debate_status_source: 'live' | 'synthetic';
  synthetic: boolean;
  explanation: string;
  agents: string[];
  rounds: number;
  consensus_reached: boolean;
  confidence: number;
  total_cost: number;
  cost_breakdown: Array<{ agent: string; tokens: number; cost: number }>;
  next_steps: Array<{ action: string; priority: 'high' | 'medium' | 'low' }>;
  provider_names: string[];
  provider_hints: string[];
  provider_routing: {
    routing_applied: boolean;
    routing_strategy: string;
    routed_agent_names: string[];
    provider_matches: Record<string, string>;
    provider_hint_scores: Record<string, number>;
  } | null;
  duration_seconds: number;
}

interface DecisionPackageViewProps {
  pkg: DecisionPackage;
}

export function DecisionPackageView({ pkg }: DecisionPackageViewProps) {
  const synthetic = pkg.synthetic || pkg.debate_status_source === 'synthetic';
  const truthLabel = synthetic ? 'SIMULATED' : 'LIVE';
  const truthDescription = synthetic
    ? 'Mock or demo path; not a live provider-backed debate.'
    : 'Provider-backed debate execution recorded from the live path.';
  const debateStatusLabel = pkg.debate_status.replace(/_/g, ' ').toUpperCase();

  return (
    <div className="space-y-4">
      <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-xs font-theme-data text-[var(--text-muted)] mb-2">
              TRUTH STATUS
            </div>
            <div className="flex flex-wrap gap-2">
              <span
                className={`px-2 py-1 text-xs font-theme-data border ${
                  synthetic
                    ? 'text-[var(--warning)] border-[var(--warning)]/40 bg-[var(--warning)]/10'
                    : 'text-[var(--acid-green)] border-[var(--acid-green)]/30 bg-[var(--acid-green)]/10'
                }`}
              >
                {truthLabel}
              </span>
              <span className="px-2 py-1 text-xs font-theme-data text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/10">
                {debateStatusLabel}
              </span>
            </div>
          </div>
          <p className="text-xs font-theme-data text-[var(--text-muted)] max-w-sm">
            {truthDescription}
          </p>
        </div>
      </div>

      {/* Explanation Panel */}
      {pkg.explanation && (
        <div className="bg-[var(--surface)] border border-[var(--border)] p-5">
          <div className="text-xs font-theme-data text-[var(--acid-green)] mb-3">
            {'>'} EXPLANATION
          </div>
          <p className="text-sm font-theme-data text-[var(--text)] whitespace-pre-wrap leading-relaxed">
            {pkg.explanation}
          </p>
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
          <div className="text-xs font-theme-data text-[var(--text-muted)] mb-1">AGENTS</div>
          <div className="text-lg font-theme-data text-[var(--acid-green)]">
            {pkg.agents.length}
          </div>
          <div className="text-xs font-theme-data text-[var(--text-muted)] mt-1 truncate">
            {pkg.agents.slice(0, 3).join(', ')}
            {pkg.agents.length > 3 ? ` +${pkg.agents.length - 3}` : ''}
          </div>
        </div>
        <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
          <div className="text-xs font-theme-data text-[var(--text-muted)] mb-1">ROUNDS</div>
          <div className="text-lg font-theme-data text-[var(--acid-cyan)]">{pkg.rounds}</div>
          <div className="text-xs font-theme-data text-[var(--text-muted)] mt-1">
            {pkg.consensus_reached ? 'Converged' : 'Divergent'}
          </div>
        </div>
        <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
          <div className="text-xs font-theme-data text-[var(--text-muted)] mb-1">COST</div>
          <div className="text-lg font-theme-data text-[var(--text)]">
            ${typeof pkg.total_cost === 'number' ? pkg.total_cost.toFixed(4) : '--'}
          </div>
          <div className="text-xs font-theme-data text-[var(--text-muted)] mt-1">
            {pkg.cost_breakdown?.length ?? 0} agents billed
          </div>
        </div>
        <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
          <div className="text-xs font-theme-data text-[var(--text-muted)] mb-1">DURATION</div>
          <div className="text-lg font-theme-data text-[var(--text)]">
            {pkg.duration_seconds ? `${Math.round(pkg.duration_seconds)}s` : '--'}
          </div>
          <div className="text-xs font-theme-data text-[var(--text-muted)] mt-1">wall clock</div>
        </div>
      </div>

      {/* Participating Agents */}
      {pkg.agents.length > 0 && (
        <div className="bg-[var(--surface)] border border-[var(--border)] p-5">
          <div className="text-xs font-theme-data text-[var(--acid-green)] mb-3">
            {'>'} PARTICIPATING AGENTS
          </div>
          <div className="flex flex-wrap gap-2">
            {pkg.agents.map((agent, i) => (
              <span
                key={i}
                className="px-2 py-1 text-xs font-theme-data bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30"
              >
                {agent}
              </span>
            ))}
          </div>
        </div>
      )}

      {(pkg.provider_names.length > 0 || pkg.provider_routing) && (
        <div className="bg-[var(--surface)] border border-[var(--acid-cyan)]/30 p-5">
          <div className="text-xs font-theme-data text-[var(--acid-cyan)] mb-3">
            {'>'} PROVIDER ROUTING
          </div>

          {pkg.provider_names.length > 0 && (
            <div className="mb-4">
              <div className="text-[10px] font-theme-data text-[var(--text-muted)] mb-2">
                SELECTED PROVIDERS
              </div>
              <div className="flex flex-wrap gap-2">
                {pkg.provider_names.map((provider) => (
                  <span
                    key={provider}
                    className="px-2 py-1 text-xs font-theme-data bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/30"
                  >
                    {provider}
                  </span>
                ))}
              </div>
            </div>
          )}

          {pkg.provider_routing && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="bg-[var(--bg)] border border-[var(--border)] p-3">
                  <div className="text-[10px] font-theme-data text-[var(--text-muted)] mb-1">
                    ROUTING APPLIED
                  </div>
                  <div className="text-sm font-theme-data text-[var(--text)]">
                    {pkg.provider_routing.routing_applied ? 'Yes' : 'No'}
                  </div>
                </div>
                <div className="bg-[var(--bg)] border border-[var(--border)] p-3">
                  <div className="text-[10px] font-theme-data text-[var(--text-muted)] mb-1">
                    STRATEGY
                  </div>
                  <div className="text-sm font-theme-data text-[var(--text)] break-words">
                    {pkg.provider_routing.routing_strategy || 'Not reported'}
                  </div>
                </div>
                <div className="bg-[var(--bg)] border border-[var(--border)] p-3">
                  <div className="text-[10px] font-theme-data text-[var(--text-muted)] mb-1">
                    ROUTED AGENTS
                  </div>
                  <div className="text-sm font-theme-data text-[var(--text)]">
                    {pkg.provider_routing.routed_agent_names.length > 0
                      ? pkg.provider_routing.routed_agent_names.join(', ')
                      : 'Not reported'}
                  </div>
                </div>
              </div>

              {Object.keys(pkg.provider_routing.provider_matches).length > 0 && (
                <div>
                  <div className="text-[10px] font-theme-data text-[var(--text-muted)] mb-2">
                    AGENT TO PROVIDER
                  </div>
                  <div className="space-y-2">
                    {Object.entries(pkg.provider_routing.provider_matches).map(
                      ([agent, provider]) => (
                        <div
                          key={agent}
                          className="flex flex-wrap items-center justify-between gap-2 bg-[var(--bg)] border border-[var(--border)] p-3"
                        >
                          <span className="text-sm font-theme-data text-[var(--text)]">
                            {agent}
                          </span>
                          <span className="text-xs font-theme-data text-[var(--acid-cyan)]">
                            {provider}
                          </span>
                        </div>
                      ),
                    )}
                  </div>
                </div>
              )}

              {Object.keys(pkg.provider_routing.provider_hint_scores).length > 0 && (
                <div>
                  <div className="text-[10px] font-theme-data text-[var(--text-muted)] mb-2">
                    ROUTING SCORES
                  </div>
                  <div className="space-y-2">
                    {Object.entries(pkg.provider_routing.provider_hint_scores).map(
                      ([provider, score]) => (
                        <div
                          key={provider}
                          className="flex flex-wrap items-center justify-between gap-2 bg-[var(--bg)] border border-[var(--border)] p-3"
                        >
                          <span className="text-sm font-theme-data text-[var(--text)]">
                            {provider}
                          </span>
                          <span className="text-xs font-theme-data text-[var(--acid-cyan)]">
                            {score.toFixed(2)}
                          </span>
                        </div>
                      ),
                    )}
                  </div>
                </div>
              )}

              {pkg.provider_hints.length > 0 && (
                <div>
                  <div className="text-[10px] font-theme-data text-[var(--text-muted)] mb-2">
                    ROUTER HINTS
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {pkg.provider_hints.map((hint) => (
                      <span
                        key={hint}
                        className="px-2 py-1 text-xs font-theme-data bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30"
                      >
                        {hint}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Next Steps */}
      {pkg.next_steps && pkg.next_steps.length > 0 && (
        <div className="bg-[var(--surface)] border border-[var(--acid-cyan)]/30 p-5">
          <div className="text-xs font-theme-data text-[var(--acid-cyan)] mb-3">
            {'>'} RECOMMENDED NEXT STEPS
          </div>
          <div className="space-y-2">
            {pkg.next_steps.map((step, i) => (
              <div key={i} className="flex items-start gap-2">
                <span className="text-xs font-theme-data text-[var(--acid-cyan)] mt-0.5">
                  {String(i + 1).padStart(2, '0')}.
                </span>
                <span
                  className={`text-[10px] font-theme-data mt-0.5 px-1 border ${
                    step.priority === 'high'
                      ? 'text-[var(--warning)] border-[var(--warning)]/40'
                      : step.priority === 'low'
                        ? 'text-[var(--text-muted)] border-[var(--border)]'
                        : 'text-[var(--acid-cyan)] border-[var(--acid-cyan)]/30'
                  }`}
                >
                  {step.priority.toUpperCase()}
                </span>
                <p className="text-sm font-theme-data text-[var(--text)]">{step.action}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
