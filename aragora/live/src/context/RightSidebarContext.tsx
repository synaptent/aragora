'use client';

import React, { createContext, useContext, useState, useCallback, useMemo, ReactNode } from 'react';

interface RightSidebarContextType {
  // Content
  title: string;
  subtitle?: string;
  statsContent: ReactNode;
  propertiesContent: ReactNode;
  actionsContent: ReactNode;
  activityContent: ReactNode;

  // Methods to set content from pages
  setTitle: (title: string, subtitle?: string) => void;
  setStatsContent: (content: ReactNode) => void;
  setPropertiesContent: (content: ReactNode) => void;
  setActionsContent: (content: ReactNode) => void;
  setActivityContent: (content: ReactNode) => void;

  // Convenience method to set all at once
  setContext: (context: {
    title?: string;
    subtitle?: string;
    statsContent?: ReactNode;
    propertiesContent?: ReactNode;
    actionsContent?: ReactNode;
    activityContent?: ReactNode;
  }) => void;

  // Clear all content
  clearContext: () => void;
}

const RightSidebarContext = createContext<RightSidebarContextType | undefined>(undefined);

export function RightSidebarProvider({ children }: { children: ReactNode }) {
  const [title, setTitleState] = useState('Context');
  const [subtitle, setSubtitle] = useState<string | undefined>();
  const [statsContent, setStatsContentState] = useState<ReactNode>(null);
  const [propertiesContent, setPropertiesContentState] = useState<ReactNode>(null);
  const [actionsContent, setActionsContentState] = useState<ReactNode>(null);
  const [activityContent, setActivityContentState] = useState<ReactNode>(null);

  const setTitle = useCallback((newTitle: string, newSubtitle?: string) => {
    setTitleState(newTitle);
    setSubtitle(newSubtitle);
  }, []);

  const setStatsContent = useCallback((content: ReactNode) => {
    setStatsContentState(content);
  }, []);

  const setPropertiesContent = useCallback((content: ReactNode) => {
    setPropertiesContentState(content);
  }, []);

  const setActionsContent = useCallback((content: ReactNode) => {
    setActionsContentState(content);
  }, []);

  const setActivityContent = useCallback((content: ReactNode) => {
    setActivityContentState(content);
  }, []);

  const setContext = useCallback(
    (context: {
      title?: string;
      subtitle?: string;
      statsContent?: ReactNode;
      propertiesContent?: ReactNode;
      actionsContent?: ReactNode;
      activityContent?: ReactNode;
    }) => {
      if (context.title !== undefined) setTitleState(context.title);
      if (context.subtitle !== undefined) setSubtitle(context.subtitle);
      if (context.statsContent !== undefined) setStatsContentState(context.statsContent);
      if (context.propertiesContent !== undefined)
        setPropertiesContentState(context.propertiesContent);
      if (context.actionsContent !== undefined) setActionsContentState(context.actionsContent);
      if (context.activityContent !== undefined) setActivityContentState(context.activityContent);
    },
    [],
  );

  const clearContext = useCallback(() => {
    setTitleState('Context');
    setSubtitle(undefined);
    setStatsContentState(null);
    setPropertiesContentState(null);
    setActionsContentState(null);
    setActivityContentState(null);
  }, []);

  const value = useMemo<RightSidebarContextType>(
    () => ({
      title,
      subtitle,
      statsContent,
      propertiesContent,
      actionsContent,
      activityContent,
      setTitle,
      setStatsContent,
      setPropertiesContent,
      setActionsContent,
      setActivityContent,
      setContext,
      clearContext,
    }),
    [
      title,
      subtitle,
      statsContent,
      propertiesContent,
      actionsContent,
      activityContent,
      setTitle,
      setStatsContent,
      setPropertiesContent,
      setActionsContent,
      setActivityContent,
      setContext,
      clearContext,
    ],
  );

  return <RightSidebarContext.Provider value={value}>{children}</RightSidebarContext.Provider>;
}

export function useRightSidebar() {
  const context = useContext(RightSidebarContext);
  if (context === undefined) {
    throw new Error('useRightSidebar must be used within a RightSidebarProvider');
  }
  return context;
}
