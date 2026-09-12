/**
 * Knowledge Explorer Store
 *
 * Zustand store for managing knowledge exploration state including:
 * - Query/search state
 * - Node browser state
 * - Graph visualization state
 * - Detail panels and editors
 */

'use client';

import { create } from 'zustand';
import { devtools, subscribeWithSelector } from 'zustand/middleware';

// Import types
import type {
  KnowledgeNode,
  KnowledgeRelationship,
  GraphNode,
  GraphEdge,
  NodeFilters,
  MoundStats,
  SortField,
  KnowledgeExplorerStore,
} from './types';

// Import constants
import {
  defaultFilters,
  initialQueryState,
  initialBrowserState,
  initialGraphState,
  initialDetailPanelState,
  initialRelationshipEditorState,
  initialNodeEditorState,
} from './constants';

// Re-export types and selectors
export * from './types';
export * from './selectors';

// Store implementation
export const useKnowledgeExplorerStore = create<KnowledgeExplorerStore>()(
  devtools(
    subscribeWithSelector((set) => ({
      // Initial state
      query: { ...initialQueryState },
      browser: { ...initialBrowserState },
      graph: { ...initialGraphState },
      detailPanel: { ...initialDetailPanelState },
      relationshipEditor: { ...initialRelationshipEditorState },
      nodeEditor: { ...initialNodeEditorState },
      stats: null,
      statsLoading: false,
      activeTab: 'search',

      // Query operations
      setQueryText: (text: string) =>
        set((state) => ({ query: { ...state.query, text } }), false, 'setQueryText'),

      setQueryExecuting: (executing: boolean) =>
        set(
          (state) => ({ query: { ...state.query, isExecuting: executing, error: null } }),
          false,
          'setQueryExecuting',
        ),

      setQueryResults: (results: KnowledgeNode[], total?: number) =>
        set(
          (state) => ({
            query: {
              ...state.query,
              results,
              total: total ?? results.length,
              isExecuting: false,
              error: null,
            },
          }),
          false,
          'setQueryResults',
        ),

      setQueryError: (error: string | null) =>
        set(
          (state) => ({ query: { ...state.query, error, isExecuting: false } }),
          false,
          'setQueryError',
        ),

      clearQueryResults: () =>
        set(
          (state) => ({ query: { ...state.query, results: [], total: 0, error: null } }),
          false,
          'clearQueryResults',
        ),

      // Browser operations
      setBrowserNodes: (nodes: KnowledgeNode[], total?: number) =>
        set(
          (state) => ({
            browser: {
              ...state.browser,
              nodes,
              totalNodes: total ?? nodes.length,
              isLoading: false,
              error: null,
            },
          }),
          false,
          'setBrowserNodes',
        ),

      setBrowserLoading: (loading: boolean) =>
        set(
          (state) => ({ browser: { ...state.browser, isLoading: loading } }),
          false,
          'setBrowserLoading',
        ),

      setBrowserError: (error: string | null) =>
        set(
          (state) => ({ browser: { ...state.browser, error, isLoading: false } }),
          false,
          'setBrowserError',
        ),

      selectBrowserNode: (id: string | null) =>
        set(
          (state) => ({ browser: { ...state.browser, selectedNodeId: id } }),
          false,
          'selectBrowserNode',
        ),

      setFilters: (filters: Partial<NodeFilters>) =>
        set(
          (state) => ({
            browser: {
              ...state.browser,
              filters: { ...state.browser.filters, ...filters },
              page: 0,
            },
          }),
          false,
          'setFilters',
        ),

      resetFilters: () =>
        set(
          (state) => ({ browser: { ...state.browser, filters: { ...defaultFilters }, page: 0 } }),
          false,
          'resetFilters',
        ),

      setSortBy: (field: SortField) =>
        set(
          (state) => ({ browser: { ...state.browser, sortBy: field, page: 0 } }),
          false,
          'setSortBy',
        ),

      toggleSortDirection: () =>
        set(
          (state) => ({
            browser: {
              ...state.browser,
              sortDirection: state.browser.sortDirection === 'asc' ? 'desc' : 'asc',
              page: 0,
            },
          }),
          false,
          'toggleSortDirection',
        ),

      setPage: (page: number) =>
        set((state) => ({ browser: { ...state.browser, page } }), false, 'setPage'),

      setPageSize: (size: number) =>
        set(
          (state) => ({ browser: { ...state.browser, pageSize: size, page: 0 } }),
          false,
          'setPageSize',
        ),

      // Graph operations
      setGraphRoot: (nodeId: string | null) =>
        set((state) => ({ graph: { ...state.graph, rootNodeId: nodeId } }), false, 'setGraphRoot'),

      setGraphDepth: (depth: number) =>
        set(
          (state) => ({ graph: { ...state.graph, depth: Math.max(1, Math.min(5, depth)) } }),
          false,
          'setGraphDepth',
        ),

      setGraphDirection: (direction: 'outgoing' | 'incoming' | 'both') =>
        set((state) => ({ graph: { ...state.graph, direction } }), false, 'setGraphDirection'),

      setGraphData: (nodes: GraphNode[], edges: GraphEdge[]) =>
        set(
          (state) => ({ graph: { ...state.graph, nodes, edges, isLoading: false, error: null } }),
          false,
          'setGraphData',
        ),

      setGraphLoading: (loading: boolean) =>
        set(
          (state) => ({ graph: { ...state.graph, isLoading: loading } }),
          false,
          'setGraphLoading',
        ),

      setGraphError: (error: string | null) =>
        set(
          (state) => ({ graph: { ...state.graph, error, isLoading: false } }),
          false,
          'setGraphError',
        ),

      selectGraphNode: (id: string | null) =>
        set(
          (state) => ({ graph: { ...state.graph, selectedNodeId: id } }),
          false,
          'selectGraphNode',
        ),

      hoverGraphNode: (id: string | null) =>
        set((state) => ({ graph: { ...state.graph, hoveredNodeId: id } }), false, 'hoverGraphNode'),

      setGraphZoom: (zoom: number) =>
        set(
          (state) => ({ graph: { ...state.graph, zoom: Math.max(0.1, Math.min(4, zoom)) } }),
          false,
          'setGraphZoom',
        ),

      setGraphPan: (x: number, y: number) =>
        set((state) => ({ graph: { ...state.graph, panX: x, panY: y } }), false, 'setGraphPan'),

      updateNodePosition: (id: string, x: number, y: number) =>
        set(
          (state) => ({
            graph: {
              ...state.graph,
              nodes: state.graph.nodes.map((node) =>
                node.id === id ? { ...node, x, y, fx: x, fy: y } : node,
              ),
            },
          }),
          false,
          'updateNodePosition',
        ),

      clearGraph: () =>
        set(
          (state) => ({
            graph: {
              ...initialGraphState,
              depth: state.graph.depth,
              direction: state.graph.direction,
            },
          }),
          false,
          'clearGraph',
        ),

      // Detail panel operations
      openDetailPanel: (nodeId: string) =>
        set(
          { detailPanel: { isOpen: true, nodeId, node: null, relationships: [], isLoading: true } },
          false,
          'openDetailPanel',
        ),

      closeDetailPanel: () =>
        set({ detailPanel: { ...initialDetailPanelState } }, false, 'closeDetailPanel'),

      setDetailNode: (node: KnowledgeNode | null) =>
        set(
          (state) => ({ detailPanel: { ...state.detailPanel, node, isLoading: false } }),
          false,
          'setDetailNode',
        ),

      setDetailRelationships: (relationships: KnowledgeRelationship[]) =>
        set(
          (state) => ({ detailPanel: { ...state.detailPanel, relationships } }),
          false,
          'setDetailRelationships',
        ),

      setDetailLoading: (loading: boolean) =>
        set(
          (state) => ({ detailPanel: { ...state.detailPanel, isLoading: loading } }),
          false,
          'setDetailLoading',
        ),

      // Relationship editor operations
      openRelationshipEditor: (fromId: string, toId: string | null = null) =>
        set(
          {
            relationshipEditor: {
              isOpen: true,
              fromNodeId: fromId,
              toNodeId: toId,
              editingRelationship: null,
            },
          },
          false,
          'openRelationshipEditor',
        ),

      closeRelationshipEditor: () =>
        set(
          { relationshipEditor: { ...initialRelationshipEditorState } },
          false,
          'closeRelationshipEditor',
        ),

      setEditingRelationship: (relationship: KnowledgeRelationship | null) =>
        set(
          (state) => ({
            relationshipEditor: { ...state.relationshipEditor, editingRelationship: relationship },
          }),
          false,
          'setEditingRelationship',
        ),

      // Node editor operations
      openNodeEditor: (node: KnowledgeNode | null = null) =>
        set(
          { nodeEditor: { isOpen: true, editingNode: node, isNew: node === null } },
          false,
          'openNodeEditor',
        ),

      closeNodeEditor: () =>
        set({ nodeEditor: { ...initialNodeEditorState } }, false, 'closeNodeEditor'),

      // Statistics
      setStats: (stats: MoundStats | null) =>
        set({ stats, statsLoading: false }, false, 'setStats'),

      setStatsLoading: (loading: boolean) =>
        set({ statsLoading: loading }, false, 'setStatsLoading'),

      // Tab navigation
      setActiveTab: (
        tab:
          | 'search'
          | 'browse'
          | 'graph'
          | 'stale'
          | 'shared'
          | 'federation'
          | 'quality'
          | 'adapters'
          | 'contradictions',
      ) => set({ activeTab: tab }, false, 'setActiveTab'),

      // Reset
      resetExplorer: () =>
        set(
          {
            query: { ...initialQueryState },
            browser: { ...initialBrowserState },
            graph: { ...initialGraphState },
            detailPanel: { ...initialDetailPanelState },
            relationshipEditor: { ...initialRelationshipEditorState },
            nodeEditor: { ...initialNodeEditorState },
            stats: null,
            statsLoading: false,
            activeTab: 'search',
          },
          false,
          'resetExplorer',
        ),
    })),
    { name: 'knowledge-explorer-store' },
  ),
);
