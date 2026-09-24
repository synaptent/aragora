export interface ToolParameter {
  name: string;
  type: string;
  required: boolean;
  description: string;
}

export interface MCPTool {
  name: string;
  description: string;
  category: string;
  parameters: ToolParameter[];
}

export interface ToolCategory {
  name: string;
  icon: string;
  description: string;
  tools: MCPTool[];
}

export const TOOL_CATEGORIES: ToolCategory[] = [
  {
    name: 'Debate',
    icon: '!',
    description: 'Start and manage multi-agent debates',
    tools: [
      {
        name: 'start_debate',
        description: 'Start a new multi-agent debate on a given topic',
        category: 'Debate',
        parameters: [
          {
            name: 'question',
            type: 'string',
            required: true,
            description: 'The question or topic to debate',
          },
          {
            name: 'agents',
            type: 'string[]',
            required: false,
            description: 'List of agent names to include',
          },
          {
            name: 'rounds',
            type: 'number',
            required: false,
            description: 'Number of debate rounds (default: 3)',
          },
          {
            name: 'protocol',
            type: 'string',
            required: false,
            description: 'Debate protocol: majority, unanimous, supermajority',
          },
        ],
      },
      {
        name: 'get_debate_status',
        description: 'Get the current status and progress of an active debate',
        category: 'Debate',
        parameters: [
          {
            name: 'debate_id',
            type: 'string',
            required: true,
            description: 'The debate identifier',
          },
        ],
      },
      {
        name: 'list_debates',
        description: 'List recent debates with their outcomes and metadata',
        category: 'Debate',
        parameters: [
          {
            name: 'limit',
            type: 'number',
            required: false,
            description: 'Maximum results to return (default: 20)',
          },
          {
            name: 'status',
            type: 'string',
            required: false,
            description: 'Filter by status: active, completed, failed',
          },
        ],
      },
      {
        name: 'vote_on_debate',
        description: 'Cast a human vote on an active debate round',
        category: 'Debate',
        parameters: [
          {
            name: 'debate_id',
            type: 'string',
            required: true,
            description: 'The debate to vote on',
          },
          { name: 'choice', type: 'string', required: true, description: 'Your vote choice' },
          {
            name: 'intensity',
            type: 'number',
            required: false,
            description: 'Vote intensity 1-10 (default: 5)',
          },
        ],
      },
      {
        name: 'get_debate_result',
        description: 'Get the final result and decision receipt for a completed debate',
        category: 'Debate',
        parameters: [
          {
            name: 'debate_id',
            type: 'string',
            required: true,
            description: 'The debate identifier',
          },
          {
            name: 'include_receipt',
            type: 'boolean',
            required: false,
            description: 'Include cryptographic receipt',
          },
        ],
      },
    ],
  },
  {
    name: 'Agent',
    icon: '&',
    description: 'Manage and inspect AI agents',
    tools: [
      {
        name: 'list_agents',
        description: 'List all available AI agents with their capabilities and ELO ratings',
        category: 'Agent',
        parameters: [
          {
            name: 'sort_by',
            type: 'string',
            required: false,
            description: 'Sort field: elo, name, wins (default: elo)',
          },
          {
            name: 'limit',
            type: 'number',
            required: false,
            description: 'Maximum agents to return',
          },
        ],
      },
      {
        name: 'get_agent_profile',
        description: 'Get detailed profile and debate history for a specific agent',
        category: 'Agent',
        parameters: [
          {
            name: 'agent_name',
            type: 'string',
            required: true,
            description: 'The agent identifier',
          },
        ],
      },
      {
        name: 'breed_agents',
        description: 'Evolve new agent configurations by breeding parent agents',
        category: 'Agent',
        parameters: [
          {
            name: 'parent_agents',
            type: 'string[]',
            required: true,
            description: 'Names of parent agents to breed',
          },
          {
            name: 'mutation_rate',
            type: 'number',
            required: false,
            description: 'Mutation rate 0.0-1.0 (default: 0.1)',
          },
        ],
      },
      {
        name: 'get_agent_lineage',
        description: 'Retrieve the evolutionary lineage tree for an agent',
        category: 'Agent',
        parameters: [
          {
            name: 'agent_name',
            type: 'string',
            required: true,
            description: 'The agent to trace lineage for',
          },
          {
            name: 'depth',
            type: 'number',
            required: false,
            description: 'Max generations to traverse (default: 5)',
          },
        ],
      },
    ],
  },
  {
    name: 'Memory',
    icon: '=',
    description: 'Multi-tier memory system operations',
    tools: [
      {
        name: 'query_memory',
        description: 'Search across fast, medium, slow, and glacial memory tiers',
        category: 'Memory',
        parameters: [
          {
            name: 'query',
            type: 'string',
            required: true,
            description: 'Natural language search query',
          },
          {
            name: 'tier',
            type: 'string',
            required: false,
            description: 'Target tier: fast, medium, slow, glacial (default: all)',
          },
          {
            name: 'limit',
            type: 'number',
            required: false,
            description: 'Maximum results to return',
          },
        ],
      },
      {
        name: 'store_memory',
        description: 'Store content in a specific memory tier with metadata',
        category: 'Memory',
        parameters: [
          { name: 'content', type: 'string', required: true, description: 'The content to store' },
          {
            name: 'tier',
            type: 'string',
            required: true,
            description: 'Target tier: fast, medium, slow, glacial',
          },
          {
            name: 'metadata',
            type: 'object',
            required: false,
            description: 'Additional metadata key-value pairs',
          },
        ],
      },
      {
        name: 'get_memory_pressure',
        description: 'Check memory utilization and pressure metrics across all tiers',
        category: 'Memory',
        parameters: [],
      },
      {
        name: 'consolidate_memories',
        description: 'Trigger memory consolidation to promote or demote entries between tiers',
        category: 'Memory',
        parameters: [
          {
            name: 'source_tier',
            type: 'string',
            required: true,
            description: 'Tier to consolidate from',
          },
          {
            name: 'dry_run',
            type: 'boolean',
            required: false,
            description: 'Preview without applying changes',
          },
        ],
      },
    ],
  },
  {
    name: 'Knowledge',
    icon: '?',
    description: 'Knowledge Mound queries and management',
    tools: [
      {
        name: 'query_knowledge',
        description: 'Search the Knowledge Mound for organizational data and insights',
        category: 'Knowledge',
        parameters: [
          { name: 'query', type: 'string', required: true, description: 'Semantic search query' },
          {
            name: 'adapter',
            type: 'string',
            required: false,
            description: 'Limit to specific adapter (e.g. debate, evidence)',
          },
          {
            name: 'limit',
            type: 'number',
            required: false,
            description: 'Maximum results (default: 10)',
          },
        ],
      },
      {
        name: 'store_knowledge',
        description: 'Persist content to the Knowledge Mound with validation',
        category: 'Knowledge',
        parameters: [
          { name: 'content', type: 'string', required: true, description: 'The content to store' },
          {
            name: 'metadata',
            type: 'object',
            required: false,
            description: 'Tags, source, and classification metadata',
          },
        ],
      },
      {
        name: 'get_knowledge_stats',
        description: 'Retrieve Knowledge Mound statistics across all 34 adapters',
        category: 'Knowledge',
        parameters: [],
      },
      {
        name: 'get_decision_receipt',
        description: 'Retrieve a cryptographic decision receipt by ID',
        category: 'Knowledge',
        parameters: [
          {
            name: 'receipt_id',
            type: 'string',
            required: true,
            description: 'The receipt identifier',
          },
        ],
      },
    ],
  },
  {
    name: 'Verification',
    icon: '^',
    description: 'Consensus proofs and formal verification',
    tools: [
      {
        name: 'verify_consensus',
        description: 'Verify the integrity of a debate consensus using cryptographic proofs',
        category: 'Verification',
        parameters: [
          {
            name: 'debate_id',
            type: 'string',
            required: true,
            description: 'The debate to verify',
          },
        ],
      },
      {
        name: 'generate_proof',
        description: 'Generate a formal verification proof for a debate outcome',
        category: 'Verification',
        parameters: [
          { name: 'debate_id', type: 'string', required: true, description: 'The debate to prove' },
          {
            name: 'backend',
            type: 'string',
            required: false,
            description: 'Verification backend: z3, lean (default: z3)',
          },
        ],
      },
      {
        name: 'get_consensus_proofs',
        description: 'List all consensus proofs for a debate with their verification status',
        category: 'Verification',
        parameters: [
          {
            name: 'debate_id',
            type: 'string',
            required: true,
            description: 'The debate identifier',
          },
        ],
      },
      {
        name: 'verify_receipt',
        description: 'Validate the SHA-256 integrity hash of a decision receipt',
        category: 'Verification',
        parameters: [
          {
            name: 'receipt_id',
            type: 'string',
            required: true,
            description: 'The receipt to verify',
          },
        ],
      },
    ],
  },
  {
    name: 'Workflow',
    icon: '>',
    description: 'DAG-based workflow automation',
    tools: [
      {
        name: 'run_workflow',
        description: 'Execute a workflow template with provided inputs',
        category: 'Workflow',
        parameters: [
          {
            name: 'template_id',
            type: 'string',
            required: true,
            description: 'Workflow template identifier',
          },
          {
            name: 'inputs',
            type: 'object',
            required: true,
            description: 'Input parameters for the workflow',
          },
        ],
      },
      {
        name: 'get_workflow_status',
        description: 'Get the execution status and progress of a running workflow',
        category: 'Workflow',
        parameters: [
          {
            name: 'workflow_id',
            type: 'string',
            required: true,
            description: 'The workflow execution ID',
          },
        ],
      },
      {
        name: 'list_workflow_templates',
        description: 'List available workflow templates across all 6 categories',
        category: 'Workflow',
        parameters: [
          {
            name: 'category',
            type: 'string',
            required: false,
            description: 'Filter by category name',
          },
        ],
      },
      {
        name: 'cancel_workflow',
        description: 'Cancel a running workflow and clean up resources',
        category: 'Workflow',
        parameters: [
          {
            name: 'workflow_id',
            type: 'string',
            required: true,
            description: 'The workflow to cancel',
          },
        ],
      },
    ],
  },
  {
    name: 'Evidence',
    icon: '#',
    description: 'Evidence collection and citation management',
    tools: [
      {
        name: 'search_evidence',
        description: 'Search the evidence corpus for supporting or contradicting data',
        category: 'Evidence',
        parameters: [
          {
            name: 'query',
            type: 'string',
            required: true,
            description: 'Search query for evidence',
          },
          { name: 'source', type: 'string', required: false, description: 'Filter by source type' },
          {
            name: 'limit',
            type: 'number',
            required: false,
            description: 'Maximum results (default: 10)',
          },
        ],
      },
      {
        name: 'cite_evidence',
        description: 'Create a formal citation linking evidence to a debate claim',
        category: 'Evidence',
        parameters: [
          {
            name: 'evidence_id',
            type: 'string',
            required: true,
            description: 'The evidence to cite',
          },
          {
            name: 'context',
            type: 'string',
            required: true,
            description: 'Citation context or claim being supported',
          },
        ],
      },
      {
        name: 'verify_citation',
        description: 'Verify the validity and freshness of an evidence citation',
        category: 'Evidence',
        parameters: [
          {
            name: 'citation_id',
            type: 'string',
            required: true,
            description: 'The citation to verify',
          },
        ],
      },
    ],
  },
  {
    name: 'Platform',
    icon: '@',
    description: 'Agent registry, scheduling, and health monitoring',
    tools: [
      {
        name: 'register_agent',
        description: 'Register an agent in the distributed platform',
        category: 'Platform',
        parameters: [
          {
            name: 'agent_id',
            type: 'string',
            required: true,
            description: 'Unique agent identifier',
          },
          {
            name: 'capabilities',
            type: 'string[]',
            required: true,
            description: 'List of agent capabilities',
          },
        ],
      },
      {
        name: 'get_control_plane_status',
        description: 'Get overall platform health and agent registry summary',
        category: 'Platform',
        parameters: [],
      },
      {
        name: 'submit_task',
        description: 'Submit a task to the priority-based scheduler',
        category: 'Platform',
        parameters: [
          {
            name: 'task_type',
            type: 'string',
            required: true,
            description: 'Type of task to schedule',
          },
          { name: 'payload', type: 'object', required: true, description: 'Task payload data' },
          {
            name: 'priority',
            type: 'number',
            required: false,
            description: 'Priority level 1-10 (default: 5)',
          },
        ],
      },
      {
        name: 'trigger_health_check',
        description: 'Trigger a liveness probe across all registered agents',
        category: 'Platform',
        parameters: [],
      },
    ],
  },
  {
    name: 'Canvas',
    icon: '*',
    description: 'Visual collaboration canvases',
    tools: [
      {
        name: 'canvas_create',
        description: 'Create a new canvas for visual collaboration or argument mapping',
        category: 'Canvas',
        parameters: [
          { name: 'name', type: 'string', required: true, description: 'Canvas name' },
          {
            name: 'type',
            type: 'string',
            required: false,
            description: 'Canvas type: debate, workflow, freeform (default: freeform)',
          },
        ],
      },
      {
        name: 'canvas_add_node',
        description: 'Add a node to an existing canvas',
        category: 'Canvas',
        parameters: [
          {
            name: 'canvas_id',
            type: 'string',
            required: true,
            description: 'The canvas to modify',
          },
          {
            name: 'node_type',
            type: 'string',
            required: true,
            description: 'Node type: claim, evidence, agent, action',
          },
          {
            name: 'data',
            type: 'object',
            required: true,
            description: 'Node content and metadata',
          },
        ],
      },
      {
        name: 'canvas_add_edge',
        description: 'Create an edge linking two canvas nodes',
        category: 'Canvas',
        parameters: [
          {
            name: 'canvas_id',
            type: 'string',
            required: true,
            description: 'The canvas to modify',
          },
          { name: 'source', type: 'string', required: true, description: 'Source node ID' },
          { name: 'target', type: 'string', required: true, description: 'Target node ID' },
        ],
      },
      {
        name: 'canvas_execute_action',
        description: 'Execute an action on a canvas (layout, export, analyze)',
        category: 'Canvas',
        parameters: [
          {
            name: 'canvas_id',
            type: 'string',
            required: true,
            description: 'The canvas to act on',
          },
          {
            name: 'action',
            type: 'string',
            required: true,
            description: 'Action: auto_layout, export_svg, analyze_clusters',
          },
        ],
      },
    ],
  },
  {
    name: 'Pipeline',
    icon: '|',
    description: 'Idea-to-Execution pipeline management',
    tools: [
      {
        name: 'create_pipeline',
        description: 'Create a new pipeline from ideas, brain dump, or debate export',
        category: 'Pipeline',
        parameters: [
          {
            name: 'source',
            type: 'string',
            required: true,
            description: 'Source type: ideas, braindump, debate',
          },
          { name: 'content', type: 'string', required: true, description: 'Raw input content' },
        ],
      },
      {
        name: 'advance_pipeline_stage',
        description: 'Advance a pipeline to the next stage with AI-assisted transitions',
        category: 'Pipeline',
        parameters: [
          {
            name: 'pipeline_id',
            type: 'string',
            required: true,
            description: 'The pipeline identifier',
          },
          {
            name: 'stage',
            type: 'string',
            required: true,
            description: 'Target stage: goals, actions, orchestration',
          },
        ],
      },
      {
        name: 'execute_pipeline',
        description: 'Execute the orchestration stage of a pipeline end-to-end',
        category: 'Pipeline',
        parameters: [
          {
            name: 'pipeline_id',
            type: 'string',
            required: true,
            description: 'The pipeline to execute',
          },
          {
            name: 'dry_run',
            type: 'boolean',
            required: false,
            description: 'Preview execution plan without running',
          },
        ],
      },
      {
        name: 'get_pipeline_status',
        description: 'Get current pipeline stage status and provenance links',
        category: 'Pipeline',
        parameters: [
          {
            name: 'pipeline_id',
            type: 'string',
            required: true,
            description: 'The pipeline identifier',
          },
        ],
      },
    ],
  },
  {
    name: 'Codebase',
    icon: '%',
    description: 'Codebase auditing and analysis tools',
    tools: [
      {
        name: 'run_audit',
        description: 'Run a codebase audit using multi-agent analysis',
        category: 'Codebase',
        parameters: [
          {
            name: 'target',
            type: 'string',
            required: true,
            description: 'File path or directory to audit',
          },
          {
            name: 'audit_type',
            type: 'string',
            required: false,
            description: 'Audit type: security, quality, performance',
          },
        ],
      },
      {
        name: 'run_quick_audit',
        description: 'Run a fast single-pass audit on a code snippet',
        category: 'Codebase',
        parameters: [
          { name: 'content', type: 'string', required: true, description: 'Code content to audit' },
          {
            name: 'language',
            type: 'string',
            required: false,
            description: 'Programming language (auto-detected if omitted)',
          },
        ],
      },
      {
        name: 'get_audit_findings',
        description: 'Retrieve findings from a completed audit session',
        category: 'Codebase',
        parameters: [
          {
            name: 'session_id',
            type: 'string',
            required: true,
            description: 'The audit session identifier',
          },
          {
            name: 'severity',
            type: 'string',
            required: false,
            description: 'Filter by severity: critical, high, medium, low',
          },
        ],
      },
      {
        name: 'run_gauntlet',
        description: 'Stress-test content through adversarial red-team analysis',
        category: 'Codebase',
        parameters: [
          {
            name: 'content',
            type: 'string',
            required: true,
            description: 'Content to stress-test',
          },
          {
            name: 'profile',
            type: 'string',
            required: false,
            description: 'Attack profile: default, aggressive, stealth',
          },
        ],
      },
    ],
  },
  {
    name: 'Self-Improve',
    icon: '~',
    description: 'Nomic Loop self-improvement orchestration',
    tools: [
      {
        name: 'start_improvement_cycle',
        description: 'Launch a self-improvement cycle with goal decomposition',
        category: 'Self-Improve',
        parameters: [
          {
            name: 'goal',
            type: 'string',
            required: true,
            description: 'High-level improvement goal',
          },
          {
            name: 'dry_run',
            type: 'boolean',
            required: false,
            description: 'Preview plan without executing',
          },
          {
            name: 'budget_limit',
            type: 'number',
            required: false,
            description: 'Maximum budget in dollars',
          },
        ],
      },
      {
        name: 'get_improvement_status',
        description: 'Get the status of a running self-improvement cycle',
        category: 'Self-Improve',
        parameters: [
          {
            name: 'cycle_id',
            type: 'string',
            required: true,
            description: 'The improvement cycle ID',
          },
        ],
      },
      {
        name: 'list_improvement_history',
        description: 'List past self-improvement cycles and their outcomes',
        category: 'Self-Improve',
        parameters: [
          {
            name: 'limit',
            type: 'number',
            required: false,
            description: 'Maximum results (default: 10)',
          },
        ],
      },
    ],
  },
];

export const ALL_TOOLS: MCPTool[] = TOOL_CATEGORIES.flatMap((c) => c.tools);
export const TOOL_COUNT = ALL_TOOLS.length;
