'use client';

import type { ReactNode } from 'react';

export interface Tab {
  id: string;
  label: string;
  icon?: ReactNode;
}

export interface TabNavigationProps {
  tabs: Tab[];
  activeTab: string;
  onTabChange: (tabId: string) => void;
  variant?: 'default' | 'compact';
  className?: string;
  ariaLabel?: string;
}

export function TabNavigation({
  tabs,
  activeTab,
  onTabChange,
  variant = 'default',
  className = '',
  ariaLabel = 'Tab navigation',
}: TabNavigationProps) {
  const buttonClass = variant === 'compact' ? 'px-2 py-0.5 text-xs' : 'px-3 py-1 text-sm';

  return (
    <div role="tablist" aria-label={ariaLabel} className={`flex gap-1 mb-4 ${className}`}>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          id={`${tab.id}-tab`}
          aria-selected={activeTab === tab.id}
          aria-controls={`${tab.id}-panel`}
          onClick={() => onTabChange(tab.id)}
          className={`${buttonClass} rounded transition-colors flex-1 focus:outline-none focus:ring-2 focus:ring-accent ${
            activeTab === tab.id
              ? 'bg-accent text-bg font-medium'
              : 'text-text-muted hover:text-text'
          }`}
        >
          {tab.icon && <span className="mr-1">{tab.icon}</span>}
          {tab.label}
        </button>
      ))}
    </div>
  );
}
