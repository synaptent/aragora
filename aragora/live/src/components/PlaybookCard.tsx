'use client';

import type { Playbook } from '@/hooks/usePlaybooks';

// ---------------------------------------------------------------------------
// Vertical / category color mapping
// ---------------------------------------------------------------------------

const CATEGORY_COLORS: Record<string, { bg: string; text: string; border: string; badge: string }> =
  {
    healthcare: {
      bg: 'bg-blue-500/10',
      text: 'text-blue-400',
      border: 'border-blue-500/30',
      badge: 'bg-blue-500/20 text-blue-300 border-blue-500/40',
    },
    finance: {
      bg: 'bg-emerald-500/10',
      text: 'text-emerald-400',
      border: 'border-emerald-500/30',
      badge: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
    },
    legal: {
      bg: 'bg-purple-500/10',
      text: 'text-purple-400',
      border: 'border-purple-500/30',
      badge: 'bg-purple-500/20 text-purple-300 border-purple-500/40',
    },
    compliance: {
      bg: 'bg-amber-500/10',
      text: 'text-amber-400',
      border: 'border-amber-500/30',
      badge: 'bg-amber-500/20 text-amber-300 border-amber-500/40',
    },
    engineering: {
      bg: 'bg-cyan-500/10',
      text: 'text-cyan-400',
      border: 'border-cyan-500/30',
      badge: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40',
    },
    general: {
      bg: 'bg-[var(--acid-green)]/10',
      text: 'text-[var(--acid-green)]',
      border: 'border-[var(--acid-green)]/30',
      badge: 'bg-[var(--acid-green)]/20 text-[var(--acid-green)] border-[var(--acid-green)]/40',
    },
  };

function getCategoryColors(category: string) {
  return CATEGORY_COLORS[category] ?? CATEGORY_COLORS.general;
}

const CATEGORY_ICONS: Record<string, string> = {
  healthcare: '+',
  finance: '$',
  legal: '!',
  compliance: '~',
  engineering: '#',
  general: '>',
};

// ---------------------------------------------------------------------------
// PlaybookCard component
// ---------------------------------------------------------------------------

interface PlaybookCardProps {
  playbook: Playbook;
  onLaunch: (playbook: Playbook) => void;
}

export function PlaybookCard({ playbook, onLaunch }: PlaybookCardProps) {
  const colors = getCategoryColors(playbook.category);
  const icon = CATEGORY_ICONS[playbook.category] ?? '>';

  return (
    <div
      className={`bg-[var(--surface)] border ${colors.border} p-5 hover:border-opacity-80 transition-all group cursor-pointer`}
      onClick={() => onLaunch(playbook)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onLaunch(playbook);
        }
      }}
    >
      {/* Header row: category badge + step count */}
      <div className="flex items-center justify-between mb-3">
        <span
          className={`px-2 py-0.5 text-[10px] font-theme-data uppercase border ${colors.badge}`}
        >
          {icon} {playbook.category}
        </span>
        <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
          {playbook.steps.length} step{playbook.steps.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Name */}
      <h3
        className={`text-sm font-theme-data font-bold mb-2 ${colors.text} group-hover:brightness-125 transition-all`}
      >
        {playbook.name}
      </h3>

      {/* Description */}
      <p className="text-xs font-theme-data text-[var(--text-muted)] mb-4 line-clamp-2 leading-relaxed">
        {playbook.description}
      </p>

      {/* Meta row */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        {/* Agents range */}
        <span className="text-[10px] font-theme-data text-[var(--text-muted)] bg-[var(--bg)] px-1.5 py-0.5 border border-[var(--border)]">
          {playbook.min_agents}-{playbook.max_agents} agents
        </span>

        {/* Rounds */}
        <span className="text-[10px] font-theme-data text-[var(--text-muted)] bg-[var(--bg)] px-1.5 py-0.5 border border-[var(--border)]">
          {playbook.max_rounds} rounds
        </span>

        {/* Consensus threshold */}
        <span className="text-[10px] font-theme-data text-[var(--text-muted)] bg-[var(--bg)] px-1.5 py-0.5 border border-[var(--border)]">
          {Math.round(playbook.consensus_threshold * 100)}% consensus
        </span>

        {/* Compliance artifacts count */}
        {playbook.compliance_artifacts.length > 0 && (
          <span className="text-[10px] font-theme-data text-amber-400 bg-amber-500/10 px-1.5 py-0.5 border border-amber-500/30">
            {playbook.compliance_artifacts.length} artifact
            {playbook.compliance_artifacts.length !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* Tags */}
      {playbook.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-4">
          {playbook.tags.slice(0, 4).map((tag) => (
            <span
              key={tag}
              className="text-[10px] font-theme-data text-[var(--text-muted)] opacity-60"
            >
              #{tag}
            </span>
          ))}
          {playbook.tags.length > 4 && (
            <span className="text-[10px] font-theme-data text-[var(--text-muted)] opacity-40">
              +{playbook.tags.length - 4}
            </span>
          )}
        </div>
      )}

      {/* Launch button */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          onLaunch(playbook);
        }}
        className={`w-full px-3 py-2 text-xs font-theme-data text-center border transition-colors ${colors.bg} ${colors.text} ${colors.border} hover:brightness-125`}
      >
        LAUNCH PLAYBOOK
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// PlaybookDetailModal component
// ---------------------------------------------------------------------------

interface PlaybookDetailModalProps {
  playbook: Playbook;
  onClose: () => void;
  onRun: (input: string) => void;
  launching: boolean;
  launchError: string | null;
}

export function PlaybookDetailModal({
  playbook,
  onClose,
  onRun,
  launching,
  launchError,
}: PlaybookDetailModalProps) {
  const colors = getCategoryColors(playbook.category);
  const icon = CATEGORY_ICONS[playbook.category] ?? '>';

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const formData = new FormData(e.currentTarget);
    const input = (formData.get('input') as string)?.trim();
    if (input) {
      onRun(input);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="relative w-full max-w-2xl max-h-[90vh] overflow-y-auto bg-[var(--bg)] border border-[var(--border)] mx-4">
        {/* Header */}
        <div className={`flex items-center justify-between p-4 border-b ${colors.border}`}>
          <div className="flex items-center gap-3">
            <span
              className={`px-2 py-0.5 text-[10px] font-theme-data uppercase border ${colors.badge}`}
            >
              {icon} {playbook.category}
            </span>
            <h2 className={`text-lg font-theme-data font-bold ${colors.text}`}>{playbook.name}</h2>
          </div>
          <button
            onClick={onClose}
            className="text-[var(--text-muted)] hover:text-[var(--text)] transition-colors p-1 font-theme-data text-xl"
            aria-label="Close"
          >
            &times;
          </button>
        </div>

        {/* Body */}
        <div className="p-5 space-y-6">
          {/* Description */}
          <p className="text-sm font-theme-data text-[var(--text-muted)] leading-relaxed">
            {playbook.description}
          </p>

          {/* Configuration summary */}
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-[var(--surface)] border border-[var(--border)] p-3">
              <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase mb-1">
                Agents
              </div>
              <div className="text-sm font-theme-data text-[var(--text)]">
                {playbook.min_agents}-{playbook.max_agents} ({playbook.agent_selection_strategy})
              </div>
            </div>
            <div className="bg-[var(--surface)] border border-[var(--border)] p-3">
              <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase mb-1">
                Rounds
              </div>
              <div className="text-sm font-theme-data text-[var(--text)]">
                {playbook.max_rounds} max, {Math.round(playbook.consensus_threshold * 100)}%
                threshold
              </div>
            </div>
            <div className="bg-[var(--surface)] border border-[var(--border)] p-3">
              <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase mb-1">
                Template
              </div>
              <div className="text-sm font-theme-data text-[var(--text)]">
                {playbook.template_name}
              </div>
            </div>
            <div className="bg-[var(--surface)] border border-[var(--border)] p-3">
              <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase mb-1">
                Output
              </div>
              <div className="text-sm font-theme-data text-[var(--text)]">
                {playbook.output_format} &rarr; {playbook.output_channels.join(', ') || 'none'}
              </div>
            </div>
          </div>

          {/* Required agent types */}
          {playbook.required_agent_types.length > 0 && (
            <div>
              <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase mb-2">
                Required Agent Types
              </div>
              <div className="flex flex-wrap gap-1">
                {playbook.required_agent_types.map((t) => (
                  <span
                    key={t}
                    className="px-2 py-0.5 text-[10px] font-theme-data bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/30"
                  >
                    {t}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Compliance artifacts */}
          {playbook.compliance_artifacts.length > 0 && (
            <div>
              <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase mb-2">
                Compliance Artifacts
              </div>
              <div className="flex flex-wrap gap-1">
                {playbook.compliance_artifacts.map((a) => (
                  <span
                    key={a}
                    className="px-2 py-0.5 text-[10px] font-theme-data bg-amber-500/10 text-amber-400 border border-amber-500/30"
                  >
                    {a}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Steps */}
          <div>
            <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase mb-2">
              Playbook Steps ({playbook.steps.length})
            </div>
            <div className="space-y-1">
              {playbook.steps.map((step, i) => (
                <div
                  key={step.name}
                  className="flex items-center gap-3 bg-[var(--surface)] border border-[var(--border)] px-3 py-2"
                >
                  <span
                    className={`text-xs font-theme-data font-bold ${colors.text} w-5 text-right`}
                  >
                    {i + 1}
                  </span>
                  <span className="text-xs font-theme-data text-[var(--text)]">{step.name}</span>
                  <span className="text-[10px] font-theme-data text-[var(--text-muted)] ml-auto uppercase">
                    {step.action}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Approval gates */}
          {playbook.approval_gates.length > 0 && (
            <div>
              <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase mb-2">
                Approval Gates
              </div>
              <div className="space-y-1">
                {playbook.approval_gates.map((gate) => (
                  <div
                    key={gate.name}
                    className="bg-[var(--surface)] border border-amber-500/20 px-3 py-2"
                  >
                    <div className="text-xs font-theme-data text-amber-400">{gate.name}</div>
                    <div className="text-[10px] font-theme-data text-[var(--text-muted)]">
                      {gate.description} (role: {gate.required_role}, timeout: {gate.timeout_hours}
                      h)
                      {gate.auto_approve_if_consensus && (
                        <span className="text-emerald-400 ml-2">[auto-approve on consensus]</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Launch form */}
          <form onSubmit={handleSubmit} className="border-t border-[var(--border)] pt-4">
            <label className="block text-xs font-theme-data text-[var(--text-muted)] mb-2">
              Describe the decision or question for this playbook:
            </label>
            <textarea
              name="input"
              rows={3}
              required
              className="w-full bg-[var(--surface)] border border-[var(--border)] p-3 text-sm font-theme-data text-[var(--text)] resize-none focus:outline-none focus:border-[var(--acid-green)]/50"
              placeholder={
                playbook.steps[0]?.config?.question_template
                  ? String(playbook.steps[0].config.question_template).replace(/\{[^}]+\}/g, '...')
                  : 'Enter your question or topic...'
              }
            />

            {launchError && (
              <p className="text-xs font-theme-data text-red-400 mt-2">{launchError}</p>
            )}

            <div className="flex items-center justify-end gap-3 mt-3">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
              >
                CANCEL
              </button>
              <button
                type="submit"
                disabled={launching}
                className={`px-6 py-2 text-xs font-theme-data border transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${colors.bg} ${colors.text} ${colors.border} hover:brightness-125`}
              >
                {launching ? 'LAUNCHING...' : 'RUN PLAYBOOK'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}

export default PlaybookCard;
