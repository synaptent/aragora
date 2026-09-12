'use client';

import { useCallback, useMemo } from 'react';
import {
  useWorkflowBuilderStore,
  type StepType,
  type NodeCategory,
} from '@/store/workflowBuilderStore';

export interface NodePaletteProps {
  /** Callback when a node type is dragged/dropped */
  onDragStart?: (type: StepType) => void;
  /** Callback when node is added (click) */
  onAddNode?: (type: StepType) => void;
  /** Whether to show compact view */
  compact?: boolean;
}

interface NodeTypeInfo {
  type: StepType;
  name: string;
  icon: string;
  description: string;
  category: NodeCategory;
}

const NODE_TYPES: NodeTypeInfo[] = [
  // Agents
  {
    type: 'agent',
    name: 'Agent Step',
    icon: '🤖',
    description: 'Execute an LLM agent',
    category: 'agents',
  },
  {
    type: 'debate',
    name: 'Multi-Agent Debate',
    icon: '💬',
    description: 'Multi-agent debate with consensus',
    category: 'agents',
  },
  {
    type: 'quick_debate',
    name: 'Quick Debate',
    icon: '⚡',
    description: 'Fast 2-agent debate',
    category: 'agents',
  },

  // Control flow
  {
    type: 'parallel',
    name: 'Parallel',
    icon: '⏸',
    description: 'Execute steps in parallel',
    category: 'control',
  },
  {
    type: 'conditional',
    name: 'Condition',
    icon: '❓',
    description: 'Branch based on condition',
    category: 'control',
  },
  {
    type: 'loop',
    name: 'Loop',
    icon: '🔄',
    description: 'Repeat steps until condition',
    category: 'control',
  },
  {
    type: 'human_checkpoint',
    name: 'Human Approval',
    icon: '👤',
    description: 'Wait for human approval',
    category: 'control',
  },

  // Memory
  {
    type: 'memory_read',
    name: 'Read Knowledge',
    icon: '📖',
    description: 'Query knowledge mound',
    category: 'memory',
  },
  {
    type: 'memory_write',
    name: 'Write Knowledge',
    icon: '📝',
    description: 'Store to knowledge mound',
    category: 'memory',
  },

  // Integration
  {
    type: 'task',
    name: 'Task',
    icon: '📋',
    description: 'Execute a custom task',
    category: 'integration',
  },
];

const CATEGORY_INFO: Record<NodeCategory, { name: string; icon: string }> = {
  agents: { name: 'Agents', icon: '🤖' },
  control: { name: 'Control Flow', icon: '🔀' },
  memory: { name: 'Memory', icon: '🧠' },
  integration: { name: 'Integration', icon: '🔌' },
};

/**
 * Palette of node types for adding to the workflow.
 */
export function NodePalette({ onDragStart, onAddNode, compact = false }: NodePaletteProps) {
  const { nodePalette, setSearchQuery, toggleCategory } = useWorkflowBuilderStore();

  const { searchQuery, expandedCategories } = nodePalette;

  // Filter nodes by search
  const filteredNodes = useMemo(() => {
    if (!searchQuery.trim()) return NODE_TYPES;

    const query = searchQuery.toLowerCase();
    return NODE_TYPES.filter(
      (node) =>
        node.name.toLowerCase().includes(query) ||
        node.description.toLowerCase().includes(query) ||
        node.type.toLowerCase().includes(query),
    );
  }, [searchQuery]);

  // Group by category
  const nodesByCategory = useMemo(() => {
    const groups: Record<NodeCategory, NodeTypeInfo[]> = {
      agents: [],
      control: [],
      memory: [],
      integration: [],
    };

    filteredNodes.forEach((node) => {
      groups[node.category].push(node);
    });

    return groups;
  }, [filteredNodes]);

  // Handle drag start
  const handleDragStart = useCallback(
    (e: React.DragEvent, type: StepType) => {
      e.dataTransfer.setData('application/workflow-node', type);
      e.dataTransfer.effectAllowed = 'copy';
      onDragStart?.(type);
    },
    [onDragStart],
  );

  // Handle click to add
  const handleClick = useCallback(
    (type: StepType) => {
      onAddNode?.(type);
    },
    [onAddNode],
  );

  if (compact) {
    // Compact grid view
    return (
      <div className="space-y-2">
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search nodes..."
          className="w-full px-2 py-1 text-xs bg-surface border border-border rounded focus:border-[var(--accent)] focus:outline-none"
        />

        <div className="grid grid-cols-4 gap-1">
          {filteredNodes.map((node) => (
            <button
              key={node.type}
              draggable
              onDragStart={(e) => handleDragStart(e, node.type)}
              onClick={() => handleClick(node.type)}
              className="p-2 text-center bg-surface border border-border rounded hover:border-[var(--accent)] transition-colors cursor-grab active:cursor-grabbing"
              title={`${node.name}: ${node.description}`}
            >
              <div className="text-lg">{node.icon}</div>
              <div className="text-xs text-text-muted truncate">{node.name}</div>
            </button>
          ))}
        </div>
      </div>
    );
  }

  // Full category view
  return (
    <div className="space-y-3">
      {/* Search */}
      <input
        type="text"
        value={searchQuery}
        onChange={(e) => setSearchQuery(e.target.value)}
        placeholder="Search nodes..."
        className="w-full px-3 py-2 text-sm bg-surface border border-border rounded focus:border-[var(--accent)] focus:outline-none"
      />

      {/* Categories */}
      {(Object.keys(nodesByCategory) as NodeCategory[]).map((category) => {
        const nodes = nodesByCategory[category];
        if (nodes.length === 0) return null;

        const info = CATEGORY_INFO[category];
        const isExpanded = expandedCategories.has(category);

        return (
          <div key={category} className="border border-border rounded-lg overflow-hidden">
            {/* Category header */}
            <button
              onClick={() => toggleCategory(category)}
              className="w-full flex items-center justify-between px-3 py-2 bg-surface hover:bg-surface/80 transition-colors"
            >
              <div className="flex items-center gap-2">
                <span>{info.icon}</span>
                <span className="text-sm font-theme-data text-text">{info.name}</span>
                <span className="text-xs text-text-muted">({nodes.length})</span>
              </div>
              <span className="text-text-muted">{isExpanded ? '▼' : '▶'}</span>
            </button>

            {/* Node list */}
            {isExpanded && (
              <div className="p-2 space-y-1 bg-bg/50">
                {nodes.map((node) => (
                  <div
                    key={node.type}
                    draggable
                    onDragStart={(e) => handleDragStart(e, node.type)}
                    onClick={() => handleClick(node.type)}
                    className="flex items-center gap-3 p-2 rounded border border-transparent hover:border-[var(--accent)] hover:bg-surface/50 cursor-grab active:cursor-grabbing transition-all"
                  >
                    <div className="text-xl">{node.icon}</div>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-text">{node.name}</div>
                      <div className="text-xs text-text-muted truncate">{node.description}</div>
                    </div>
                    <div className="text-text-muted text-xs">+</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}

      {/* Help text */}
      <div className="text-xs text-text-muted text-center py-2">
        Drag nodes to canvas or click to add
      </div>
    </div>
  );
}

export default NodePalette;
