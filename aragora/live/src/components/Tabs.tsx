'use client';

import { createContext, useContext, useState, useCallback, useMemo, useId } from 'react';

// Context for sharing tab state
interface TabsContextValue {
  activeTab: string;
  setActiveTab: (id: string) => void;
  baseId: string;
}

const TabsContext = createContext<TabsContextValue | null>(null);

function useTabsContext() {
  const context = useContext(TabsContext);
  if (!context) {
    throw new Error('Tab components must be used within a Tabs component');
  }
  return context;
}

// Types for tab configuration
export interface TabConfig {
  id: string;
  label: React.ReactNode;
  /** Optional badge/count to display next to label */
  badge?: React.ReactNode;
  /** Custom active color class (e.g., 'bg-green-500') */
  activeColor?: string;
}

// Main Tabs container
interface TabsProps {
  /** Tab configurations */
  tabs: TabConfig[];
  /** Currently active tab ID (controlled mode) */
  activeTab?: string;
  /** Callback when tab changes */
  onChange?: (tabId: string) => void;
  /** Default active tab (uncontrolled mode) */
  defaultTab?: string;
  /** Additional className for the container */
  className?: string;
  /** Label for accessibility */
  ariaLabel?: string;
  /** Size variant */
  size?: 'sm' | 'md' | 'lg';
  /** Visual variant */
  variant?: 'default' | 'pills' | 'underline';
  children: React.ReactNode;
}

export function Tabs({
  tabs,
  activeTab: controlledActiveTab,
  onChange,
  defaultTab,
  className = '',
  ariaLabel = 'Tabs',
  size = 'md',
  variant = 'default',
  children,
}: TabsProps) {
  const baseId = useId();
  const [uncontrolledActiveTab, setUncontrolledActiveTab] = useState(
    defaultTab || tabs[0]?.id || '',
  );

  const isControlled = controlledActiveTab !== undefined;
  const activeTab = isControlled ? controlledActiveTab : uncontrolledActiveTab;

  const setActiveTab = useCallback(
    (tabId: string) => {
      if (!isControlled) {
        setUncontrolledActiveTab(tabId);
      }
      onChange?.(tabId);
    },
    [isControlled, onChange],
  );

  const contextValue = useMemo(
    () => ({ activeTab, setActiveTab, baseId }),
    [activeTab, setActiveTab, baseId],
  );

  return (
    <TabsContext.Provider value={contextValue}>
      <div className={className}>
        <TabList tabs={tabs} ariaLabel={ariaLabel} size={size} variant={variant} />
        {children}
      </div>
    </TabsContext.Provider>
  );
}

// Tab list container
interface TabListProps {
  tabs: TabConfig[];
  ariaLabel: string;
  size: 'sm' | 'md' | 'lg';
  variant: 'default' | 'pills' | 'underline';
}

function TabList({ tabs, ariaLabel, size, variant }: TabListProps) {
  const { activeTab, setActiveTab, baseId } = useTabsContext();

  const sizeClasses = {
    sm: 'px-2 py-0.5 text-xs',
    md: 'px-3 py-1 text-sm',
    lg: 'px-4 py-2 text-base',
  };

  const containerClasses = {
    default: 'flex space-x-1 bg-bg border border-border rounded p-1',
    pills: 'flex space-x-2',
    underline: 'flex border-b border-border',
  };

  const getTabClasses = (tab: TabConfig, isActive: boolean) => {
    const baseClasses = `${sizeClasses[size]} transition-colors flex-1 focus:outline-none focus:ring-2 focus:ring-accent`;

    if (variant === 'underline') {
      return `${baseClasses} border-b-2 ${
        isActive
          ? `${tab.activeColor || 'border-accent'} text-text font-medium`
          : 'border-transparent text-text-muted hover:text-text hover:border-border'
      }`;
    }

    if (variant === 'pills') {
      return `${baseClasses} rounded-full ${
        isActive
          ? `${tab.activeColor || 'bg-accent'} text-bg font-medium`
          : 'text-text-muted hover:text-text hover:bg-surface'
      }`;
    }

    // Default variant
    return `${baseClasses} rounded ${
      isActive
        ? `${tab.activeColor || 'bg-accent'} text-bg font-medium`
        : 'text-text-muted hover:text-text'
    }`;
  };

  return (
    <div role="tablist" aria-label={ariaLabel} className={`${containerClasses[variant]} mb-4`}>
      {tabs.map((tab) => {
        const isActive = activeTab === tab.id;
        return (
          <button
            key={tab.id}
            role="tab"
            id={`${baseId}-tab-${tab.id}`}
            aria-selected={isActive}
            aria-controls={`${baseId}-panel-${tab.id}`}
            tabIndex={isActive ? 0 : -1}
            onClick={() => setActiveTab(tab.id)}
            className={getTabClasses(tab, isActive)}
          >
            {tab.label}
            {tab.badge !== undefined && <span className="ml-1 opacity-80">({tab.badge})</span>}
          </button>
        );
      })}
    </div>
  );
}

// Tab panel container
interface TabPanelProps {
  tabId: string;
  children: React.ReactNode;
  className?: string;
}

export function TabPanel({ tabId, children, className = '' }: TabPanelProps) {
  const { activeTab, baseId } = useTabsContext();
  const isActive = activeTab === tabId;

  if (!isActive) return null;

  return (
    <div
      role="tabpanel"
      id={`${baseId}-panel-${tabId}`}
      aria-labelledby={`${baseId}-tab-${tabId}`}
      tabIndex={0}
      className={className}
    >
      {children}
    </div>
  );
}

// Simple hook for external tab control
export function useTabs<T extends string>(defaultTab: T) {
  const [activeTab, setActiveTab] = useState<T>(defaultTab);
  return { activeTab, setActiveTab };
}
