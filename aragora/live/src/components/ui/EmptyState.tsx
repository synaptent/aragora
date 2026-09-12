'use client';

import React from 'react';

interface EmptyStateProps {
  /** Icon to display (emoji or component) */
  icon?: React.ReactNode;
  /** Main title */
  title: string;
  /** Description text */
  description?: string;
  /** Primary action button */
  action?: { label: string; onClick: () => void };
  /** Secondary action link */
  secondaryAction?: { label: string; href?: string; onClick?: () => void };
  /** Additional CSS classes */
  className?: string;
}

/**
 * Reusable empty state component for when there's no data to display.
 * Provides consistent UX with icon, message, and optional actions.
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  secondaryAction,
  className = '',
}: EmptyStateProps) {
  return (
    <div
      className={`flex flex-col items-center justify-center py-12 px-4 text-center ${className}`}
      role="status"
      aria-label={title}
    >
      {icon && (
        <div className="text-4xl mb-4 opacity-50" aria-hidden="true">
          {icon}
        </div>
      )}

      <h3 className="text-lg font-theme-data text-text-muted mb-2">{title}</h3>

      {description && <p className="text-sm text-text-muted/70 max-w-md mb-6">{description}</p>}

      <div className="flex flex-col sm:flex-row items-center gap-3">
        {action && (
          <button
            onClick={action.onClick}
            className="px-4 py-2 bg-[var(--accent)] text-bg font-theme-data text-sm hover:bg-[var(--accent)]/80 transition-colors"
            aria-label={action.label}
          >
            {'>'} {action.label}
          </button>
        )}

        {secondaryAction &&
          (secondaryAction.href ? (
            <a
              href={secondaryAction.href}
              className="text-sm text-[var(--acid-cyan)] hover:text-[var(--acid-cyan)]/80 font-theme-data underline"
            >
              {secondaryAction.label}
            </a>
          ) : (
            <button
              onClick={secondaryAction.onClick}
              className="text-sm text-[var(--acid-cyan)] hover:text-[var(--acid-cyan)]/80 font-theme-data underline"
            >
              {secondaryAction.label}
            </button>
          ))}
      </div>
    </div>
  );
}

// Pre-configured empty states for common scenarios
export const DebatesEmptyState = ({ onStart }: { onStart?: () => void }) => (
  <EmptyState
    icon="💬"
    title="No debates yet"
    description="Start your first debate to see AI agents discuss and critique ideas."
    action={onStart ? { label: 'START DEBATE', onClick: onStart } : undefined}
  />
);

export const InboxEmptyState = ({ onConfigure }: { onConfigure?: () => void }) => (
  <EmptyState
    icon="📥"
    title="Inbox is empty"
    description="Configure connectors to sync data from external sources like Gmail, Slack, or Jira."
    action={onConfigure ? { label: 'CONFIGURE CONNECTORS', onClick: onConfigure } : undefined}
    secondaryAction={{ label: 'Learn about connectors', href: '/connectors' }}
  />
);

export const KnowledgeEmptyState = ({ onRunDebate }: { onRunDebate?: () => void }) => (
  <EmptyState
    icon="🧠"
    title="Knowledge Mound is empty"
    description="Run debates to populate the knowledge base with conclusions, insights, and verified facts."
    action={onRunDebate ? { label: 'START DEBATE', onClick: onRunDebate } : undefined}
  />
);

export const SearchEmptyState = ({ query }: { query?: string }) => (
  <EmptyState
    icon="🔍"
    title={query ? `No results for "${query}"` : 'No results found'}
    description="Try adjusting your search terms or filters."
  />
);

export const ErrorEmptyState = ({ onRetry }: { onRetry?: () => void }) => (
  <EmptyState
    icon="⚠️"
    title="Something went wrong"
    description="We couldn't load this content. Please try again."
    action={onRetry ? { label: 'RETRY', onClick: onRetry } : undefined}
  />
);

export const AgentsEmptyState = () => (
  <EmptyState
    icon="🤖"
    title="No agents available"
    description="Configure API keys to enable AI agents for debates."
    secondaryAction={{ label: 'Configure API keys', href: '/settings' }}
  />
);

export const MemoryEmptyState = () => (
  <EmptyState
    icon="💾"
    title="No memories stored"
    description="Complete debates to build agent memory and improve future performance."
  />
);

export const MomentsEmptyState = ({ onViewDebates }: { onViewDebates?: () => void }) => (
  <EmptyState
    icon="✨"
    title="No moments yet"
    description="Moments are significant events and achievements captured during debates."
    action={onViewDebates ? { label: 'VIEW DEBATES', onClick: onViewDebates } : undefined}
    secondaryAction={{ label: 'What are moments?', href: '/docs/moments' }}
  />
);

export const WorkflowsEmptyState = ({ onCreate }: { onCreate?: () => void }) => (
  <EmptyState
    icon="🔄"
    title="No workflows yet"
    description="Create automated workflows to orchestrate multi-step debate processes."
    action={onCreate ? { label: 'CREATE WORKFLOW', onClick: onCreate } : undefined}
    secondaryAction={{ label: 'Browse templates', href: '/workflows/builder' }}
  />
);

export const SocialEmptyState = ({ onConnect }: { onConnect?: () => void }) => (
  <EmptyState
    icon="📱"
    title="No social connections"
    description="Connect your social accounts to publish debate results and insights."
    action={onConnect ? { label: 'CONNECT ACCOUNT', onClick: onConnect } : undefined}
  />
);

export const MLEmptyState = ({ onTrain }: { onTrain?: () => void }) => (
  <EmptyState
    icon="🧪"
    title="No ML models trained"
    description="Train machine learning models on your debate data to improve routing and quality."
    action={onTrain ? { label: 'START TRAINING', onClick: onTrain } : undefined}
    secondaryAction={{ label: 'Learn about ML features', href: '/docs/ml' }}
  />
);

export const InsightsEmptyState = ({ onRunDebate }: { onRunDebate?: () => void }) => (
  <EmptyState
    icon="💡"
    title="No insights available"
    description="Run debates to generate insights from agent discussions and conclusions."
    action={onRunDebate ? { label: 'START DEBATE', onClick: onRunDebate } : undefined}
  />
);

export const HistoryEmptyState = () => (
  <EmptyState
    icon="📜"
    title="No history yet"
    description="Your activity history will appear here as you use the platform."
  />
);

export default EmptyState;
