'use client';

import { useState } from 'react';

export interface MCPTool {
  name: string;
  description: string;
  category: MCPCategory;
  params: string[];
}

export type MCPCategory =
  | 'debate'
  | 'gauntlet'
  | 'agent'
  | 'memory'
  | 'knowledge'
  | 'audit'
  | 'workflow'
  | 'evidence'
  | 'verification'
  | 'control-plane'
  | 'integration'
  | 'canvas';

const CATEGORY_META: Record<MCPCategory, { label: string; icon: string }> = {
  debate: { label: 'Debate', icon: '!' },
  gauntlet: { label: 'Gauntlet', icon: '%' },
  agent: { label: 'Agents', icon: '&' },
  memory: { label: 'Memory', icon: '=' },
  knowledge: { label: 'Knowledge', icon: '?' },
  audit: { label: 'Audit', icon: '|' },
  workflow: { label: 'Workflow', icon: '>' },
  evidence: { label: 'Evidence', icon: '#' },
  verification: { label: 'Verification', icon: '^' },
  'control-plane': { label: 'Platform', icon: '@' },
  integration: { label: 'Integrations', icon: '<' },
  canvas: { label: 'Canvas', icon: '*' },
};

/**
 * Catalog of Aragora MCP tools, mirrored from aragora/mcp/tools.py TOOLS_METADATA.
 */
export const MCP_TOOLS: MCPTool[] = [
  // Debate
  {
    name: 'run_debate',
    description: 'Run a multi-agent AI debate on a topic',
    category: 'debate',
    params: ['question', 'agents', 'rounds', 'consensus'],
  },
  {
    name: 'get_debate',
    description: 'Get results of a previous debate',
    category: 'debate',
    params: ['debate_id'],
  },
  {
    name: 'search_debates',
    description: 'Search debates by topic, date, or agents',
    category: 'debate',
    params: ['query', 'agent', 'start_date', 'end_date', 'limit'],
  },
  {
    name: 'fork_debate',
    description: 'Fork an existing debate to explore alternative conclusions',
    category: 'debate',
    params: ['debate_id', 'fork_point'],
  },
  {
    name: 'get_forks',
    description: 'List all forks of a debate',
    category: 'debate',
    params: ['debate_id'],
  },

  // Gauntlet
  {
    name: 'run_gauntlet',
    description: 'Stress-test content through adversarial analysis',
    category: 'gauntlet',
    params: ['content', 'content_type', 'profile'],
  },

  // Agents
  { name: 'list_agents', description: 'List available AI agents', category: 'agent', params: [] },
  {
    name: 'get_agent_history',
    description: 'Get agent debate history and performance stats',
    category: 'agent',
    params: ['agent_name'],
  },
  {
    name: 'get_agent_lineage',
    description: 'Get evolutionary lineage of an agent',
    category: 'agent',
    params: ['agent_name'],
  },
  {
    name: 'breed_agents',
    description: 'Evolve new agent configurations through breeding',
    category: 'agent',
    params: ['parent_agents'],
  },

  // Memory
  {
    name: 'query_memory',
    description: 'Query the multi-tier memory system',
    category: 'memory',
    params: ['query', 'tier', 'limit'],
  },
  {
    name: 'store_memory',
    description: 'Store information in memory tiers',
    category: 'memory',
    params: ['content', 'tier', 'metadata'],
  },
  {
    name: 'get_memory_pressure',
    description: 'Check memory pressure across tiers',
    category: 'memory',
    params: [],
  },

  // Knowledge
  {
    name: 'query_knowledge',
    description: 'Query the Knowledge Mound for organizational data',
    category: 'knowledge',
    params: ['query', 'limit'],
  },
  {
    name: 'store_knowledge',
    description: 'Store data in the Knowledge Mound',
    category: 'knowledge',
    params: ['content', 'metadata'],
  },
  {
    name: 'get_knowledge_stats',
    description: 'Get Knowledge Mound statistics',
    category: 'knowledge',
    params: [],
  },
  {
    name: 'get_decision_receipt',
    description: 'Retrieve a decision receipt by ID',
    category: 'knowledge',
    params: ['receipt_id'],
  },
  {
    name: 'verify_decision_receipt',
    description: 'Verify the integrity of a decision receipt',
    category: 'knowledge',
    params: ['receipt_id'],
  },
  {
    name: 'build_decision_integrity',
    description: 'Build decision integrity summary',
    category: 'knowledge',
    params: ['debate_id'],
  },

  // Audit
  {
    name: 'list_audit_presets',
    description: 'List available audit presets',
    category: 'audit',
    params: [],
  },
  {
    name: 'list_audit_types',
    description: 'List supported audit types',
    category: 'audit',
    params: [],
  },
  {
    name: 'create_audit_session',
    description: 'Create a new audit session',
    category: 'audit',
    params: ['audit_type', 'target'],
  },
  {
    name: 'run_audit',
    description: 'Run an audit analysis',
    category: 'audit',
    params: ['session_id'],
  },
  {
    name: 'get_audit_status',
    description: 'Get audit session status',
    category: 'audit',
    params: ['session_id'],
  },
  {
    name: 'get_audit_findings',
    description: 'Get findings from an audit session',
    category: 'audit',
    params: ['session_id'],
  },
  {
    name: 'update_finding_status',
    description: 'Update the status of an audit finding',
    category: 'audit',
    params: ['finding_id', 'status'],
  },
  {
    name: 'run_quick_audit',
    description: 'Run a quick one-shot audit',
    category: 'audit',
    params: ['content', 'audit_type'],
  },

  // Evidence
  {
    name: 'search_evidence',
    description: 'Search evidence corpus',
    category: 'evidence',
    params: ['query', 'source', 'limit'],
  },
  {
    name: 'cite_evidence',
    description: 'Create an evidence citation',
    category: 'evidence',
    params: ['evidence_id', 'context'],
  },
  {
    name: 'verify_citation',
    description: 'Verify an evidence citation',
    category: 'evidence',
    params: ['citation_id'],
  },

  // Verification
  {
    name: 'get_consensus_proofs',
    description: 'Get consensus proofs for a debate',
    category: 'verification',
    params: ['debate_id'],
  },
  {
    name: 'verify_consensus',
    description: 'Verify consensus integrity',
    category: 'verification',
    params: ['debate_id'],
  },
  {
    name: 'generate_proof',
    description: 'Generate a verification proof',
    category: 'verification',
    params: ['debate_id'],
  },
  {
    name: 'verify_plan',
    description: 'Verify a decision plan',
    category: 'verification',
    params: ['plan_id'],
  },
  {
    name: 'get_receipt',
    description: 'Get a verification receipt',
    category: 'verification',
    params: ['receipt_id'],
  },

  // Workflow
  {
    name: 'run_workflow',
    description: 'Run a workflow template',
    category: 'workflow',
    params: ['template_id', 'inputs'],
  },
  {
    name: 'get_workflow_status',
    description: 'Get workflow execution status',
    category: 'workflow',
    params: ['workflow_id'],
  },
  {
    name: 'list_workflow_templates',
    description: 'List available workflow templates',
    category: 'workflow',
    params: [],
  },
  {
    name: 'cancel_workflow',
    description: 'Cancel a running workflow',
    category: 'workflow',
    params: ['workflow_id'],
  },

  // Trending
  {
    name: 'list_trending_topics',
    description: 'List trending topics from Pulse',
    category: 'integration',
    params: ['limit'],
  },

  // External integrations
  {
    name: 'trigger_external_webhook',
    description: 'Trigger an external webhook',
    category: 'integration',
    params: ['url', 'payload'],
  },
  {
    name: 'list_integrations',
    description: 'List configured integrations',
    category: 'integration',
    params: [],
  },
  {
    name: 'test_integration',
    description: 'Test an integration connection',
    category: 'integration',
    params: ['integration_id'],
  },
  {
    name: 'get_integration_events',
    description: 'Get recent events from an integration',
    category: 'integration',
    params: ['integration_id', 'limit'],
  },

  // Platform
  {
    name: 'register_agent',
    description: 'Register an agent in the platform',
    category: 'control-plane',
    params: ['agent_id', 'capabilities'],
  },
  {
    name: 'unregister_agent',
    description: 'Unregister an agent',
    category: 'control-plane',
    params: ['agent_id'],
  },
  {
    name: 'list_registered_agents',
    description: 'List agents in the platform',
    category: 'control-plane',
    params: [],
  },
  {
    name: 'get_agent_health',
    description: 'Get health status of a registered agent',
    category: 'control-plane',
    params: ['agent_id'],
  },
  {
    name: 'submit_task',
    description: 'Submit a task to the scheduler',
    category: 'control-plane',
    params: ['task_type', 'payload'],
  },
  {
    name: 'get_task_status',
    description: 'Get task execution status',
    category: 'control-plane',
    params: ['task_id'],
  },
  {
    name: 'cancel_task',
    description: 'Cancel a pending task',
    category: 'control-plane',
    params: ['task_id'],
  },
  {
    name: 'list_pending_tasks',
    description: 'List pending tasks in the queue',
    category: 'control-plane',
    params: [],
  },
  {
    name: 'get_control_plane_status',
    description: 'Get overall platform status',
    category: 'control-plane',
    params: [],
  },
  {
    name: 'trigger_health_check',
    description: 'Trigger a health check across agents',
    category: 'control-plane',
    params: [],
  },
  {
    name: 'get_resource_utilization',
    description: 'Get resource utilization metrics',
    category: 'control-plane',
    params: [],
  },

  // Canvas
  {
    name: 'canvas_create',
    description: 'Create a new canvas for visual collaboration',
    category: 'canvas',
    params: ['name', 'type'],
  },
  {
    name: 'canvas_get',
    description: 'Get canvas state',
    category: 'canvas',
    params: ['canvas_id'],
  },
  {
    name: 'canvas_add_node',
    description: 'Add a node to a canvas',
    category: 'canvas',
    params: ['canvas_id', 'node_type', 'data'],
  },
  {
    name: 'canvas_add_edge',
    description: 'Add an edge between canvas nodes',
    category: 'canvas',
    params: ['canvas_id', 'source', 'target'],
  },
  {
    name: 'canvas_execute_action',
    description: 'Execute an action on a canvas',
    category: 'canvas',
    params: ['canvas_id', 'action'],
  },
  { name: 'canvas_list', description: 'List all canvases', category: 'canvas', params: [] },
  {
    name: 'canvas_delete_node',
    description: 'Delete a node from a canvas',
    category: 'canvas',
    params: ['canvas_id', 'node_id'],
  },
];

interface ToolCatalogProps {
  compact?: boolean;
}

export function ToolCatalog({ compact }: ToolCatalogProps) {
  const [search, setSearch] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<MCPCategory | 'all'>('all');

  const categories = Object.keys(CATEGORY_META) as MCPCategory[];

  const filteredTools = MCP_TOOLS.filter((tool) => {
    if (selectedCategory !== 'all' && tool.category !== selectedCategory) return false;
    if (search) {
      const q = search.toLowerCase();
      return tool.name.toLowerCase().includes(q) || tool.description.toLowerCase().includes(q);
    }
    return true;
  });

  // Group by category
  const grouped = new Map<MCPCategory, MCPTool[]>();
  for (const tool of filteredTools) {
    const list = grouped.get(tool.category) || [];
    list.push(tool);
    grouped.set(tool.category, list);
  }

  return (
    <div className="space-y-6">
      {/* Search + Filter */}
      {!compact && (
        <div className="space-y-3">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search tools..."
            className="w-full bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] px-4 py-2 font-theme-data text-sm placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--acid-green)] transition-colors"
          />
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => setSelectedCategory('all')}
              className={`px-3 py-1 text-xs font-theme-data border transition-colors ${
                selectedCategory === 'all'
                  ? 'text-[var(--acid-green)] border-[var(--acid-green)] bg-[var(--acid-green)]/10'
                  : 'text-[var(--text-muted)] border-[var(--border)] hover:border-[var(--acid-green)]/50'
              }`}
            >
              ALL ({MCP_TOOLS.length})
            </button>
            {categories.map((cat) => {
              const meta = CATEGORY_META[cat];
              const count = MCP_TOOLS.filter((t) => t.category === cat).length;
              return (
                <button
                  key={cat}
                  onClick={() => setSelectedCategory(cat)}
                  className={`px-3 py-1 text-xs font-theme-data border transition-colors ${
                    selectedCategory === cat
                      ? 'text-[var(--acid-green)] border-[var(--acid-green)] bg-[var(--acid-green)]/10'
                      : 'text-[var(--text-muted)] border-[var(--border)] hover:border-[var(--acid-green)]/50'
                  }`}
                >
                  {meta.icon} {meta.label} ({count})
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Tool count */}
      <div className="text-xs font-theme-data text-[var(--text-muted)]">
        {filteredTools.length} tool{filteredTools.length !== 1 ? 's' : ''} found
      </div>

      {/* Tool grid by category */}
      <div className="space-y-6">
        {[...grouped.entries()].map(([category, tools]) => {
          const meta = CATEGORY_META[category];
          return (
            <div key={category}>
              <h3 className="text-xs font-theme-data text-[var(--acid-cyan)] uppercase tracking-wider mb-2 flex items-center gap-2">
                <span>{meta.icon}</span>
                {meta.label}
                <span className="text-[var(--text-muted)]">({tools.length})</span>
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {tools.map((tool) => (
                  <div
                    key={tool.name}
                    className="border border-[var(--border)] bg-[var(--surface)] p-3 hover:border-[var(--acid-green)]/30 transition-colors"
                  >
                    <div className="text-sm font-theme-data text-[var(--acid-green)] font-bold">
                      {tool.name}
                    </div>
                    <div className="text-xs font-theme-data text-[var(--text-muted)] mt-1">
                      {tool.description}
                    </div>
                    {tool.params.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-2">
                        {tool.params.map((p) => (
                          <span
                            key={p}
                            className="px-1.5 py-0.5 text-[10px] font-theme-data bg-[var(--bg)] text-[var(--text-muted)] border border-[var(--border)]"
                          >
                            {p}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
