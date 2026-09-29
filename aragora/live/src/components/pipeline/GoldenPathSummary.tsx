'use client';

import { PIPELINE_STAGE_CONFIG, type PipelineStageType } from '@/components/pipeline-canvas/types';

export interface GoldenPathCard {
  stage: PipelineStageType;
  title: string;
  detail: string;
  meta?: string;
}

export interface GoldenPathSummaryProps {
  heading: string;
  summary: string;
  cards: GoldenPathCard[];
  sourceLabel?: string;
  signals?: string[];
}

function hexToRgba(hex: string, alpha: number): string {
  const normalized = hex.replace('#', '');
  const full =
    normalized.length === 3
      ? normalized
          .split('')
          .map((char) => char + char)
          .join('')
      : normalized;

  if (full.length !== 6) {
    return `rgba(148, 163, 184, ${alpha})`;
  }

  const red = Number.parseInt(full.slice(0, 2), 16);
  const green = Number.parseInt(full.slice(2, 4), 16);
  const blue = Number.parseInt(full.slice(4, 6), 16);
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

export function GoldenPathSummary({
  heading,
  summary,
  cards,
  sourceLabel,
  signals = [],
}: GoldenPathSummaryProps) {
  return (
    <section className="rounded-xl border border-border bg-surface/70 p-4 md:p-5">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="space-y-1">
          <p className="text-[11px] font-theme-data uppercase tracking-[0.28em] text-text-muted">
            Golden Path
          </p>
          <h2 className="text-lg font-theme-data font-bold text-text">{heading}</h2>
          <p className="max-w-3xl text-sm font-theme-data text-text-muted">{summary}</p>
        </div>

        {sourceLabel && (
          <span className="inline-flex items-center rounded-full border border-border px-3 py-1 text-[11px] font-theme-data uppercase tracking-wide text-text-muted">
            {sourceLabel}
          </span>
        )}
      </div>

      {signals.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {signals.slice(0, 3).map((signal) => (
            <span
              key={signal}
              className="rounded-full border border-border bg-bg/70 px-3 py-1 text-[11px] font-theme-data text-text-muted"
            >
              {signal}
            </span>
          ))}
        </div>
      )}

      <div className="mt-4 grid grid-cols-1 gap-3 xl:grid-cols-4">
        {cards.map((card, index) => {
          const config = PIPELINE_STAGE_CONFIG[card.stage];
          const borderColor = hexToRgba(config.primary, 0.45);
          const stageGlow = `linear-gradient(180deg, ${hexToRgba(config.primary, 0.18)} 0%, ${hexToRgba(config.accent, 0.08)} 100%)`;

          return (
            <article
              key={`${card.stage}-${card.title}`}
              className="rounded-lg border p-4"
              style={{ borderColor, background: stageGlow }}
            >
              <div className="flex items-center justify-between gap-3">
                <span
                  className="text-[11px] font-theme-data uppercase tracking-[0.22em]"
                  style={{ color: config.secondary }}
                >
                  {String(index + 1).padStart(2, '0')} {config.label}
                </span>
                <span
                  className="text-xs font-theme-data uppercase tracking-wide"
                  style={{ color: config.primary }}
                >
                  {card.stage}
                </span>
              </div>

              <h3 className="mt-3 text-sm font-theme-data font-bold text-text">{card.title}</h3>
              <p className="mt-2 text-sm font-theme-data leading-6 text-text-muted">
                {card.detail}
              </p>

              {card.meta && (
                <p className="mt-3 text-[11px] font-theme-data uppercase tracking-wide text-text">
                  {card.meta}
                </p>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}

export default GoldenPathSummary;
