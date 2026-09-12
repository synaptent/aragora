/**
 * Selectors for Knowledge Explorer Store
 */

import type { KnowledgeExplorerStore } from './types';

// Basic selectors
export const selectQuery = (state: KnowledgeExplorerStore) => state.query;
export const selectBrowser = (state: KnowledgeExplorerStore) => state.browser;
export const selectGraph = (state: KnowledgeExplorerStore) => state.graph;
export const selectDetailPanel = (state: KnowledgeExplorerStore) => state.detailPanel;
export const selectRelationshipEditor = (state: KnowledgeExplorerStore) => state.relationshipEditor;
export const selectNodeEditor = (state: KnowledgeExplorerStore) => state.nodeEditor;
export const selectStats = (state: KnowledgeExplorerStore) => state.stats;
export const selectActiveTab = (state: KnowledgeExplorerStore) => state.activeTab;

// Computed selectors
export const selectBrowserFiltersActive = (state: KnowledgeExplorerStore) => {
  const { filters } = state.browser;
  return (
    filters.nodeTypes.length > 0 ||
    filters.minConfidence > 0 ||
    filters.tier !== null ||
    filters.topics.length > 0 ||
    filters.dateFrom !== undefined ||
    filters.dateTo !== undefined
  );
};

export const selectGraphHasData = (state: KnowledgeExplorerStore) => {
  return state.graph.nodes.length > 0;
};

export const selectIsAnyPanelOpen = (state: KnowledgeExplorerStore) => {
  return state.detailPanel.isOpen || state.relationshipEditor.isOpen || state.nodeEditor.isOpen;
};
