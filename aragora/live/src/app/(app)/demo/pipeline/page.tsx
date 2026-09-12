'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import Link from 'next/link';
import { API_BASE_URL } from '@/config';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type DemoStep = 'input' | 'goals' | 'tasks' | 'orchestrate' | 'complete';

interface PipelineNode {
  id: string;
  stage: string;
  label: string;
  metadata: Record<string, unknown>;
  derived_from: string[];
  hash: string;
}

interface PipelineEdge {
  source: string;
  target: string;
  edge_type: string;
}

interface TransitionResult {
  nodes: PipelineNode[];
  edges: PipelineEdge[];
  provenance: Record<string, unknown>;
}

interface StageData {
  ideas: PipelineNode[];
  goals: PipelineNode[];
  tasks: PipelineNode[];
  agents: PipelineNode[];
  edges: PipelineEdge[];
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STEPS: { key: DemoStep; label: string; number: number }[] = [
  { key: 'input', label: 'PASTE IDEAS', number: 1 },
  { key: 'goals', label: 'GENERATE GOALS', number: 2 },
  { key: 'tasks', label: 'PLAN ACTIONS', number: 3 },
  { key: 'orchestrate', label: 'ORCHESTRATE', number: 4 },
];

const STAGE_COLORS: Record<
  string,
  { border: string; bg: string; text: string; glow: string; badge: string }
> = {
  idea: {
    border: 'border-blue-500/60',
    bg: 'bg-blue-500/10',
    text: 'text-blue-400',
    glow: 'shadow-[0_0_12px_rgba(59,130,246,0.2)]',
    badge: 'bg-blue-500/20 text-blue-300 border-blue-500/40',
  },
  goal: {
    border: 'border-emerald-500/60',
    bg: 'bg-emerald-500/10',
    text: 'text-emerald-400',
    glow: 'shadow-[0_0_12px_rgba(16,185,129,0.2)]',
    badge: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
  },
  action: {
    border: 'border-amber-500/60',
    bg: 'bg-amber-500/10',
    text: 'text-amber-400',
    glow: 'shadow-[0_0_12px_rgba(245,158,11,0.2)]',
    badge: 'bg-amber-500/20 text-amber-300 border-amber-500/40',
  },
  orchestration: {
    border: 'border-purple-500/60',
    bg: 'bg-purple-500/10',
    text: 'text-purple-400',
    glow: 'shadow-[0_0_12px_rgba(139,92,246,0.2)]',
    badge: 'bg-purple-500/20 text-purple-300 border-purple-500/40',
  },
};

const STAGE_LABELS: Record<string, string> = {
  idea: 'IDEA',
  goal: 'GOAL',
  action: 'TASK',
  orchestration: 'AGENT',
};

const AGENT_TYPE_LABELS: Record<string, string> = {
  research_agent: 'Researcher',
  code_agent: 'Implementer',
  review_agent: 'Reviewer',
  general_agent: 'General',
  agent: 'Agent',
};

const PRESET_IDEAS = [
  'Build a customer feedback dashboard\nAutomate weekly reports\nImprove onboarding flow\nAdd real-time notifications\nCreate API documentation',
  'Migrate database to PostgreSQL\nImplement caching layer\nSet up CI/CD pipeline\nAdd monitoring and alerting\nOptimize API response times',
  'Launch mobile app MVP\nDesign user authentication\nBuild payment integration\nCreate admin panel\nSet up analytics tracking',
];

// ---------------------------------------------------------------------------
// Fallback demo data (used when API is unavailable)
// ---------------------------------------------------------------------------

function buildFallbackData(): StageData {
  const ideas: PipelineNode[] = [
    {
      id: 'idea-f1a2b3c4',
      stage: 'idea',
      label: 'Build a customer feedback dashboard',
      metadata: {},
      derived_from: [],
      hash: 'a1b2c3d4e5f6g7h8',
    },
    {
      id: 'idea-d5e6f7g8',
      stage: 'idea',
      label: 'Automate weekly reports',
      metadata: {},
      derived_from: [],
      hash: 'b2c3d4e5f6g7h8i9',
    },
    {
      id: 'idea-h9i0j1k2',
      stage: 'idea',
      label: 'Improve onboarding flow',
      metadata: {},
      derived_from: [],
      hash: 'c3d4e5f6g7h8i9j0',
    },
    {
      id: 'idea-l3m4n5o6',
      stage: 'idea',
      label: 'Add real-time notifications',
      metadata: {},
      derived_from: [],
      hash: 'd4e5f6g7h8i9j0k1',
    },
    {
      id: 'idea-p7q8r9s0',
      stage: 'idea',
      label: 'Create API documentation',
      metadata: {},
      derived_from: [],
      hash: 'e5f6g7h8i9j0k1l2',
    },
  ];

  const goals: PipelineNode[] = [
    {
      id: 'goal-a1b2c3d4',
      stage: 'goal',
      label: 'Achieve: Build a customer feedback dashboard',
      metadata: {
        objective: 'Build a customer feedback dashboard',
        key_results: ['Build a customer feedback dashboard', 'Automate weekly reports'],
      },
      derived_from: ['idea-f1a2b3c4', 'idea-d5e6f7g8'],
      hash: 'f6g7h8i9j0k1l2m3',
    },
    {
      id: 'goal-e5f6g7h8',
      stage: 'goal',
      label: 'Achieve: Improve onboarding flow',
      metadata: {
        objective: 'Improve onboarding flow',
        key_results: ['Improve onboarding flow', 'Add real-time notifications'],
      },
      derived_from: ['idea-h9i0j1k2', 'idea-l3m4n5o6'],
      hash: 'g7h8i9j0k1l2m3n4',
    },
    {
      id: 'goal-i9j0k1l2',
      stage: 'goal',
      label: 'Achieve: Create API documentation',
      metadata: {
        objective: 'Create API documentation',
        key_results: ['Create API documentation'],
      },
      derived_from: ['idea-p7q8r9s0'],
      hash: 'h8i9j0k1l2m3n4o5',
    },
  ];

  const tasks: PipelineNode[] = [
    {
      id: 'task-m3n4o5p6',
      stage: 'action',
      label: 'Build a customer feedback dashboard',
      metadata: {
        assignee_type: 'researcher',
        priority: 'high',
        estimated_effort: 'medium',
        source_goal_id: 'goal-a1b2c3d4',
      },
      derived_from: ['goal-a1b2c3d4'],
      hash: 'i9j0k1l2m3n4o5p6',
    },
    {
      id: 'task-q7r8s9t0',
      stage: 'action',
      label: 'Automate weekly reports',
      metadata: {
        assignee_type: 'implementer',
        priority: 'medium',
        estimated_effort: 'medium',
        source_goal_id: 'goal-a1b2c3d4',
      },
      derived_from: ['goal-a1b2c3d4'],
      hash: 'j0k1l2m3n4o5p6q7',
    },
    {
      id: 'task-u1v2w3x4',
      stage: 'action',
      label: 'Improve onboarding flow',
      metadata: {
        assignee_type: 'researcher',
        priority: 'high',
        estimated_effort: 'medium',
        source_goal_id: 'goal-e5f6g7h8',
      },
      derived_from: ['goal-e5f6g7h8'],
      hash: 'k1l2m3n4o5p6q7r8',
    },
    {
      id: 'task-y5z6a7b8',
      stage: 'action',
      label: 'Add real-time notifications',
      metadata: {
        assignee_type: 'implementer',
        priority: 'medium',
        estimated_effort: 'medium',
        source_goal_id: 'goal-e5f6g7h8',
      },
      derived_from: ['goal-e5f6g7h8'],
      hash: 'l2m3n4o5p6q7r8s9',
    },
    {
      id: 'task-c9d0e1f2',
      stage: 'action',
      label: 'Create API documentation',
      metadata: {
        assignee_type: 'reviewer',
        priority: 'high',
        estimated_effort: 'medium',
        source_goal_id: 'goal-i9j0k1l2',
      },
      derived_from: ['goal-i9j0k1l2'],
      hash: 'm3n4o5p6q7r8s9t0',
    },
  ];

  const agents: PipelineNode[] = [
    {
      id: 'orch-g3h4i5j6',
      stage: 'orchestration',
      label: 'Build a customer feedback dashboard',
      metadata: {
        agent_type: 'research_agent',
        execution_mode: 'parallel',
        source_task_id: 'task-m3n4o5p6',
      },
      derived_from: ['task-m3n4o5p6'],
      hash: 'n4o5p6q7r8s9t0u1',
    },
    {
      id: 'orch-k7l8m9n0',
      stage: 'orchestration',
      label: 'Automate weekly reports',
      metadata: {
        agent_type: 'code_agent',
        execution_mode: 'parallel',
        source_task_id: 'task-q7r8s9t0',
      },
      derived_from: ['task-q7r8s9t0'],
      hash: 'o5p6q7r8s9t0u1v2',
    },
    {
      id: 'orch-o1p2q3r4',
      stage: 'orchestration',
      label: 'Improve onboarding flow',
      metadata: {
        agent_type: 'research_agent',
        execution_mode: 'parallel',
        source_task_id: 'task-u1v2w3x4',
      },
      derived_from: ['task-u1v2w3x4'],
      hash: 'p6q7r8s9t0u1v2w3',
    },
    {
      id: 'orch-s5t6u7v8',
      stage: 'orchestration',
      label: 'Add real-time notifications',
      metadata: {
        agent_type: 'code_agent',
        execution_mode: 'parallel',
        source_task_id: 'task-y5z6a7b8',
      },
      derived_from: ['task-y5z6a7b8'],
      hash: 'q7r8s9t0u1v2w3x4',
    },
    {
      id: 'orch-w9x0y1z2',
      stage: 'orchestration',
      label: 'Create API documentation',
      metadata: {
        agent_type: 'review_agent',
        execution_mode: 'parallel',
        source_task_id: 'task-c9d0e1f2',
      },
      derived_from: ['task-c9d0e1f2'],
      hash: 'r8s9t0u1v2w3x4y5',
    },
  ];

  const edges: PipelineEdge[] = [
    // Ideas -> Goals
    { source: 'idea-f1a2b3c4', target: 'goal-a1b2c3d4', edge_type: 'derives' },
    { source: 'idea-d5e6f7g8', target: 'goal-a1b2c3d4', edge_type: 'derives' },
    { source: 'idea-h9i0j1k2', target: 'goal-e5f6g7h8', edge_type: 'derives' },
    { source: 'idea-l3m4n5o6', target: 'goal-e5f6g7h8', edge_type: 'derives' },
    { source: 'idea-p7q8r9s0', target: 'goal-i9j0k1l2', edge_type: 'derives' },
    // Goals -> Tasks
    { source: 'goal-a1b2c3d4', target: 'task-m3n4o5p6', edge_type: 'decomposes' },
    { source: 'goal-a1b2c3d4', target: 'task-q7r8s9t0', edge_type: 'decomposes' },
    { source: 'goal-e5f6g7h8', target: 'task-u1v2w3x4', edge_type: 'decomposes' },
    { source: 'goal-e5f6g7h8', target: 'task-y5z6a7b8', edge_type: 'decomposes' },
    { source: 'goal-i9j0k1l2', target: 'task-c9d0e1f2', edge_type: 'decomposes' },
    // Tasks -> Agents
    { source: 'task-m3n4o5p6', target: 'orch-g3h4i5j6', edge_type: 'triggers' },
    { source: 'task-q7r8s9t0', target: 'orch-k7l8m9n0', edge_type: 'triggers' },
    { source: 'task-u1v2w3x4', target: 'orch-o1p2q3r4', edge_type: 'triggers' },
    { source: 'task-y5z6a7b8', target: 'orch-s5t6u7v8', edge_type: 'triggers' },
    { source: 'task-c9d0e1f2', target: 'orch-w9x0y1z2', edge_type: 'triggers' },
  ];

  return { ideas, goals, tasks, agents, edges };
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function callTransition(
  endpoint: string,
  body: Record<string, unknown>,
): Promise<TransitionResult | null> {
  try {
    const url = `${API_BASE_URL}/api/v1/pipeline/transitions/${endpoint}`;
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StepIndicator({ currentStep }: { currentStep: DemoStep }) {
  const currentIndex = STEPS.findIndex((s) => s.key === currentStep);
  const isComplete = currentStep === 'complete';

  return (
    <div className="flex items-center gap-1 sm:gap-2 overflow-x-auto pb-2 sm:pb-0">
      {STEPS.map((step, i) => {
        const isActive = step.key === currentStep;
        const isDone = isComplete || i < currentIndex;
        const isFuture = !isComplete && i > currentIndex;

        return (
          <div key={step.key} className="flex items-center gap-1 sm:gap-2 shrink-0">
            {i > 0 && (
              <div
                className="w-4 sm:w-8 h-px transition-colors duration-500"
                style={{
                  backgroundColor: isDone
                    ? 'var(--acid-green)'
                    : isFuture
                      ? 'var(--border)'
                      : 'var(--acid-green)',
                }}
              />
            )}
            <div
              className={`
                flex items-center gap-1.5 px-2 sm:px-3 py-1 text-xs font-theme-data border transition-all duration-500 whitespace-nowrap
                ${
                  isActive
                    ? 'border-[var(--acid-green)] bg-[var(--acid-green)]/20 text-[var(--acid-green)] shadow-[0_0_10px_var(--acid-green)/30]'
                    : isDone
                      ? 'border-[var(--acid-green)]/50 bg-[var(--acid-green)]/10 text-[var(--acid-green)]/80'
                      : 'border-[var(--border)] text-[var(--text-muted)]'
                }
              `}
            >
              <span className="font-bold">{isDone ? '\u2713' : step.number}</span>
              <span className="hidden sm:inline">{step.label}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function PipelineNodeCard({ node, animDelay }: { node: PipelineNode; animDelay: number }) {
  const colors = STAGE_COLORS[node.stage] || STAGE_COLORS.idea;
  const stageLabel = STAGE_LABELS[node.stage] || node.stage.toUpperCase();
  const agentType = node.metadata?.agent_type as string | undefined;
  const agentLabel = agentType ? AGENT_TYPE_LABELS[agentType] || agentType : null;
  const priority = node.metadata?.priority as string | undefined;

  return (
    <div
      className={`
        p-3 border ${colors.border} ${colors.bg} ${colors.glow}
        transition-all duration-500 animate-fade-in
      `}
      style={{
        animationDelay: `${animDelay}ms`,
        animationFillMode: 'backwards',
        opacity: 0,
        animation: `fade-in 0.4s ease-out ${animDelay}ms forwards`,
      }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <span
              className={`px-1.5 py-0.5 text-[10px] font-theme-data font-bold border ${colors.badge}`}
            >
              {stageLabel}
            </span>
            {agentLabel && (
              <span className="px-1.5 py-0.5 text-[10px] font-theme-data bg-purple-500/20 text-purple-300 border border-purple-500/40">
                {agentLabel}
              </span>
            )}
            {priority && (
              <span
                className={`px-1.5 py-0.5 text-[10px] font-theme-data border ${
                  priority === 'high'
                    ? 'bg-red-500/20 text-red-300 border-red-500/40'
                    : 'bg-gray-500/20 text-gray-300 border-gray-500/40'
                }`}
              >
                {priority.toUpperCase()}
              </span>
            )}
          </div>
          <p className={`text-sm font-theme-data ${colors.text} leading-snug truncate`}>
            {node.label}
          </p>
        </div>
      </div>
      {node.hash && (
        <div className="mt-2 text-[10px] font-theme-data text-[var(--text-muted)]/40">
          #{node.hash.slice(0, 12)}
        </div>
      )}
    </div>
  );
}

function StageSection({
  title,
  titleColor,
  dotColor,
  nodes,
  baseDelay,
}: {
  title: string;
  titleColor: string;
  dotColor: string;
  nodes: PipelineNode[];
  baseDelay: number;
}) {
  return (
    <div className="space-y-2">
      <h2
        className={`text-sm font-theme-data uppercase tracking-wider flex items-center gap-2 ${titleColor}`}
      >
        <span className={`w-1.5 h-1.5 rounded-full ${dotColor}`} />
        {title}
        <span className="text-[var(--text-muted)] text-xs normal-case tracking-normal">
          ({nodes.length})
        </span>
      </h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
        {nodes.map((node, i) => (
          <PipelineNodeCard key={node.id} node={node} animDelay={baseDelay + i * 80} />
        ))}
      </div>
    </div>
  );
}

function StageArrows({ color }: { color: string }) {
  return (
    <div className="flex justify-center py-2">
      <div className="flex items-center gap-2">
        <div className={`h-px w-8 ${color}`} />
        <div className={`w-2 h-2 rotate-45 border-t-2 border-r-2 ${color}`} />
        <div className={`h-px w-8 ${color}`} />
        <div className={`w-2 h-2 rotate-45 border-t-2 border-r-2 ${color}`} />
        <div className={`h-px w-8 ${color}`} />
      </div>
    </div>
  );
}

function ProvenanceSummary({ provenance }: { provenance: Record<string, unknown> }) {
  const method = provenance.method ? String(provenance.method) : null;
  const sourceCount = provenance.source_count != null ? String(provenance.source_count) : null;
  const outputCount = provenance.output_count != null ? String(provenance.output_count) : null;

  return (
    <div className="text-[10px] font-theme-data text-[var(--text-muted)]/60 flex items-center gap-3 flex-wrap">
      {method && <span>method: {method}</span>}
      {sourceCount && <span>in: {sourceCount}</span>}
      {outputCount && <span>out: {outputCount}</span>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page Component
// ---------------------------------------------------------------------------

export default function PipelineDemoPage() {
  const [step, setStep] = useState<DemoStep>('input');
  const [ideaText, setIdeaText] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [usedFallback, setUsedFallback] = useState(false);

  const [stageData, setStageData] = useState<StageData>({
    ideas: [],
    goals: [],
    tasks: [],
    agents: [],
    edges: [],
  });

  const [provenances, setProvenances] = useState<Record<string, unknown>[]>([]);
  const [elapsedMs, setElapsedMs] = useState(0);
  const startTimeRef = useRef<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const resultsRef = useRef<HTMLDivElement>(null);

  // Timer effect
  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const startTimer = useCallback(() => {
    startTimeRef.current = Date.now();
    setElapsedMs(0);
    timerRef.current = setInterval(() => {
      if (startTimeRef.current) {
        setElapsedMs(Date.now() - startTimeRef.current);
      }
    }, 50);
  }, []);

  const stopTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const scrollToResults = useCallback(() => {
    setTimeout(() => {
      resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 100);
  }, []);

  // Parse ideas from text input
  const parseIdeas = useCallback((text: string): PipelineNode[] => {
    const lines = text
      .split(/[\n,]/)
      .map((l) => l.trim())
      .filter((l) => l.length > 0);

    return lines.map((label, i) => ({
      id: `idea-input-${i}`,
      stage: 'idea',
      label,
      metadata: {},
      derived_from: [],
      hash: '',
    }));
  }, []);

  // Step 1 -> Step 2: Generate goals from ideas
  const handleGenerateGoals = useCallback(async () => {
    const ideas = parseIdeas(ideaText);
    if (ideas.length === 0) return;

    setLoading(true);
    setError(null);
    setUsedFallback(false);
    startTimer();

    // Store ideas in state
    setStageData((prev) => ({ ...prev, ideas, goals: [], tasks: [], agents: [], edges: [] }));
    setStep('goals');
    scrollToResults();

    const apiIdeas = ideas.map((idea) => ({ id: idea.id, label: idea.label }));

    const result = await callTransition('ideas-to-goals', { ideas: apiIdeas });

    if (result) {
      const goalNodes = result.nodes.filter((n) => n.stage === 'goal');
      // Update idea hashes from API response
      const apiIdeas2 = result.nodes.filter((n) => n.stage === 'idea');
      const updatedIdeas = ideas.map((idea) => {
        const apiIdea = apiIdeas2.find((a) => a.id === idea.id);
        return apiIdea ? { ...idea, hash: apiIdea.hash } : idea;
      });

      setStageData((prev) => ({
        ...prev,
        ideas: updatedIdeas,
        goals: goalNodes,
        edges: [...prev.edges, ...result.edges],
      }));
      setProvenances([result.provenance]);
    } else {
      // Fallback to demo data
      setUsedFallback(true);
      const fallback = buildFallbackData();
      setStageData((prev) => ({
        ...prev,
        ideas: fallback.ideas,
        goals: fallback.goals,
        edges: fallback.edges.filter((e) => e.edge_type === 'derives'),
      }));
      setProvenances([
        {
          method: 'demo_fallback',
          source_count: fallback.ideas.length,
          output_count: fallback.goals.length,
        },
      ]);
    }

    setLoading(false);
  }, [ideaText, parseIdeas, startTimer, scrollToResults]);

  // Step 2 -> Step 3: Plan tasks from goals
  const handlePlanTasks = useCallback(async () => {
    setLoading(true);
    setError(null);
    setStep('tasks');
    scrollToResults();

    if (usedFallback) {
      const fallback = buildFallbackData();
      setStageData((prev) => ({
        ...prev,
        tasks: fallback.tasks,
        edges: [
          ...prev.edges,
          ...fallback.edges.filter(
            (e) => e.edge_type === 'decomposes' || e.edge_type === 'depends_on',
          ),
        ],
      }));
      setProvenances((prev) => [
        ...prev,
        {
          method: 'demo_fallback',
          source_count: stageData.goals.length,
          output_count: fallback.tasks.length,
        },
      ]);
      setLoading(false);
      return;
    }

    const apiGoals = stageData.goals.map((goal) => ({
      id: goal.id,
      label: goal.label,
      metadata: goal.metadata,
    }));

    const result = await callTransition('goals-to-tasks', { goals: apiGoals });

    if (result) {
      const taskNodes = result.nodes.filter((n) => n.stage === 'action');
      setStageData((prev) => ({
        ...prev,
        tasks: taskNodes,
        edges: [...prev.edges, ...result.edges],
      }));
      setProvenances((prev) => [...prev, result.provenance]);
    } else {
      // Fallback
      setUsedFallback(true);
      const fallback = buildFallbackData();
      setStageData((prev) => ({
        ...prev,
        tasks: fallback.tasks,
        edges: [
          ...prev.edges,
          ...fallback.edges.filter(
            (e) => e.edge_type === 'decomposes' || e.edge_type === 'depends_on',
          ),
        ],
      }));
      setProvenances((prev) => [
        ...prev,
        {
          method: 'demo_fallback',
          source_count: stageData.goals.length,
          output_count: fallback.tasks.length,
        },
      ]);
    }

    setLoading(false);
  }, [stageData.goals, usedFallback, scrollToResults]);

  // Step 3 -> Step 4: Orchestrate agents from tasks
  const handleOrchestrate = useCallback(async () => {
    setLoading(true);
    setError(null);
    setStep('orchestrate');
    scrollToResults();

    if (usedFallback) {
      const fallback = buildFallbackData();
      setStageData((prev) => ({
        ...prev,
        agents: fallback.agents,
        edges: [...prev.edges, ...fallback.edges.filter((e) => e.edge_type === 'triggers')],
      }));
      setProvenances((prev) => [
        ...prev,
        {
          method: 'demo_fallback',
          source_count: stageData.tasks.length,
          output_count: fallback.agents.length,
        },
      ]);
      setLoading(false);
      stopTimer();
      setTimeout(() => setStep('complete'), 500);
      return;
    }

    const apiTasks = stageData.tasks.map((task) => ({
      id: task.id,
      label: task.label,
      metadata: task.metadata,
      derived_from: task.derived_from,
    }));

    const result = await callTransition('tasks-to-workflow', { tasks: apiTasks });

    if (result) {
      const orchNodes = result.nodes.filter((n) => n.stage === 'orchestration');
      setStageData((prev) => ({
        ...prev,
        agents: orchNodes,
        edges: [...prev.edges, ...result.edges],
      }));
      setProvenances((prev) => [...prev, result.provenance]);
    } else {
      setUsedFallback(true);
      const fallback = buildFallbackData();
      setStageData((prev) => ({
        ...prev,
        agents: fallback.agents,
        edges: [...prev.edges, ...fallback.edges.filter((e) => e.edge_type === 'triggers')],
      }));
      setProvenances((prev) => [
        ...prev,
        {
          method: 'demo_fallback',
          source_count: stageData.tasks.length,
          output_count: fallback.agents.length,
        },
      ]);
    }

    setLoading(false);
    stopTimer();
    setTimeout(() => setStep('complete'), 500);
  }, [stageData.tasks, usedFallback, stopTimer, scrollToResults]);

  // Reset
  const handleReset = useCallback(() => {
    setStep('input');
    setIdeaText('');
    setLoading(false);
    setError(null);
    setUsedFallback(false);
    setStageData({ ideas: [], goals: [], tasks: [], agents: [], edges: [] });
    setProvenances([]);
    setElapsedMs(0);
    stopTimer();
  }, [stopTimer]);

  // Use preset
  const handlePreset = useCallback((text: string) => {
    setIdeaText(text);
  }, []);

  // Count totals
  const totalNodes =
    stageData.ideas.length +
    stageData.goals.length +
    stageData.tasks.length +
    stageData.agents.length;

  return (
    <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] relative z-10">
      <div className="max-w-5xl mx-auto px-4 py-8 sm:py-12 space-y-8">
        {/* Header */}
        <div className="space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div>
              <h1 className="text-2xl sm:text-3xl font-theme-data font-bold text-[var(--acid-green)]">
                {'>'} 60-SECOND DEMO
              </h1>
              <p className="text-[var(--text-muted)] font-theme-data text-sm mt-1">
                Paste ideas, watch them become goals, tasks, and agent assignments
              </p>
            </div>
            <div className="flex items-center gap-2">
              {step !== 'input' && (
                <div className="font-theme-data text-xs text-[var(--text-muted)] border border-[var(--border)] px-3 py-1.5">
                  {(elapsedMs / 1000).toFixed(1)}s
                </div>
              )}
              <Link
                href="/demo"
                className="text-xs font-theme-data text-purple-400 hover:text-purple-300 transition-colors border border-purple-500/50 px-3 py-1.5 hover:border-purple-500"
              >
                [DEBATE DEMO]
              </Link>
              <Link
                href="/"
                className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors border border-[var(--border)] px-3 py-1.5 hover:border-[var(--acid-green)]/50"
              >
                [BACK TO HOME]
              </Link>
            </div>
          </div>
        </div>

        {/* Step Progress */}
        <div className="p-4 bg-[var(--surface)] border border-[var(--border)]">
          <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
            <span className="text-xs font-theme-data text-[var(--text-muted)] uppercase tracking-wider">
              Pipeline Progress
            </span>
            {loading && (
              <span className="flex items-center gap-2 text-xs font-theme-data text-[var(--acid-green)]">
                <span className="w-2 h-2 bg-[var(--acid-green)] rounded-full animate-pulse" />
                PROCESSING
              </span>
            )}
            {step === 'complete' && (
              <span className="text-xs font-theme-data text-[var(--acid-green)]">COMPLETE</span>
            )}
            {usedFallback && (
              <span className="text-xs font-theme-data text-[var(--acid-yellow)]">DEMO MODE</span>
            )}
          </div>
          <StepIndicator currentStep={step} />
        </div>

        {/* Step 1: Input */}
        {step === 'input' && (
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-xs font-theme-data text-[var(--text-muted)] uppercase tracking-wider">
                Step 1: Paste Your Ideas
              </label>
              <p className="text-xs font-theme-data text-[var(--text-muted)]/60">
                One idea per line, or comma-separated. These will flow through the full pipeline.
              </p>
            </div>

            <textarea
              value={ideaText}
              onChange={(e) => setIdeaText(e.target.value)}
              placeholder={
                'Build a customer feedback dashboard\nAutomate weekly reports\nImprove onboarding flow\nAdd real-time notifications\nCreate API documentation'
              }
              rows={6}
              className="w-full px-4 py-3 text-sm font-theme-data bg-[var(--surface)] border border-[var(--border)]
                       text-[var(--text)] placeholder-[var(--text-muted)]/30
                       focus:border-[var(--acid-green)] focus:outline-none
                       resize-y transition-colors"
            />

            {/* Presets */}
            <div className="space-y-2">
              <span className="text-xs font-theme-data text-[var(--text-muted)]">
                Or try a preset:
              </span>
              <div className="flex flex-wrap gap-2">
                {PRESET_IDEAS.map((preset, i) => {
                  const previewLabel = preset.split('\n')[0];
                  return (
                    <button
                      key={i}
                      onClick={() => handlePreset(preset)}
                      className="px-3 py-1.5 text-xs font-theme-data border border-[var(--acid-green)]/30
                               text-[var(--text-muted)] hover:text-[var(--acid-green)]
                               hover:border-[var(--acid-green)]/60 hover:bg-[var(--acid-green)]/5
                               transition-colors text-left"
                    >
                      {previewLabel}...
                    </button>
                  );
                })}
              </div>
            </div>

            <button
              onClick={handleGenerateGoals}
              disabled={loading || !ideaText.trim()}
              className="px-6 py-3 font-theme-data text-sm font-bold
                       bg-[var(--acid-green)] text-[var(--bg)]
                       hover:bg-[var(--acid-green)]/80 transition-colors
                       disabled:opacity-30 disabled:cursor-not-allowed"
            >
              GENERATE GOALS &rarr;
            </button>
          </div>
        )}

        {/* Error display */}
        {error && (
          <div className="p-3 border border-red-500/50 bg-red-500/10 text-red-400 font-theme-data text-sm">
            {error}
          </div>
        )}

        {/* Pipeline Visualization */}
        {step !== 'input' && (
          <div ref={resultsRef} className="space-y-6">
            {/* Ideas Section */}
            {stageData.ideas.length > 0 && (
              <StageSection
                title="Ideas"
                titleColor="text-blue-400"
                dotColor="bg-blue-400"
                nodes={stageData.ideas}
                baseDelay={0}
              />
            )}

            {/* Arrow: Ideas -> Goals */}
            {stageData.goals.length > 0 && (
              <>
                <StageArrows color="border-emerald-500/40 bg-emerald-500/40" />
                <StageSection
                  title="Goals"
                  titleColor="text-emerald-400"
                  dotColor="bg-emerald-400"
                  nodes={stageData.goals}
                  baseDelay={200}
                />
                {provenances[0] && <ProvenanceSummary provenance={provenances[0]} />}
              </>
            )}

            {/* Arrow: Goals -> Tasks */}
            {stageData.tasks.length > 0 && (
              <>
                <StageArrows color="border-amber-500/40 bg-amber-500/40" />
                <StageSection
                  title="Tasks"
                  titleColor="text-amber-400"
                  dotColor="bg-amber-400"
                  nodes={stageData.tasks}
                  baseDelay={400}
                />
                {provenances[1] && <ProvenanceSummary provenance={provenances[1]} />}
              </>
            )}

            {/* Arrow: Tasks -> Agents */}
            {stageData.agents.length > 0 && (
              <>
                <StageArrows color="border-purple-500/40 bg-purple-500/40" />
                <StageSection
                  title="Agent Assignments"
                  titleColor="text-purple-400"
                  dotColor="bg-purple-400"
                  nodes={stageData.agents}
                  baseDelay={600}
                />
                {provenances[2] && <ProvenanceSummary provenance={provenances[2]} />}
              </>
            )}

            {/* Action Buttons */}
            <div className="flex flex-wrap items-center gap-3 pt-2">
              {/* Step 2: Generate goals button is handled above */}

              {/* Step 3: Plan tasks */}
              {step === 'goals' && stageData.goals.length > 0 && !loading && (
                <button
                  onClick={handlePlanTasks}
                  disabled={loading}
                  className="px-5 py-2.5 font-theme-data text-sm font-bold
                           bg-amber-500 text-[var(--bg)]
                           hover:bg-amber-500/80 transition-colors
                           disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  PLAN ACTIONS &rarr;
                </button>
              )}

              {/* Step 4: Orchestrate */}
              {step === 'tasks' && stageData.tasks.length > 0 && !loading && (
                <button
                  onClick={handleOrchestrate}
                  disabled={loading}
                  className="px-5 py-2.5 font-theme-data text-sm font-bold
                           bg-purple-500 text-white
                           hover:bg-purple-500/80 transition-colors
                           disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  ORCHESTRATE &rarr;
                </button>
              )}

              {loading && (
                <span className="font-theme-data text-sm text-[var(--text-muted)] animate-pulse">
                  Processing...
                </span>
              )}
            </div>

            {/* Completion Summary */}
            {step === 'complete' && (
              <div className="border-2 border-[var(--acid-green)] bg-[var(--acid-green)]/5 p-6 space-y-4">
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <div className="flex items-center gap-2">
                    <div className="w-3 h-3 bg-[var(--acid-green)] rounded-full" />
                    <span className="font-theme-data text-lg font-bold text-[var(--acid-green)]">
                      PIPELINE COMPLETE
                    </span>
                  </div>
                  <span className="font-theme-data text-sm text-[var(--text-muted)]">
                    {(elapsedMs / 1000).toFixed(1)}s elapsed
                  </span>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  <div className="p-3 bg-blue-500/10 border border-blue-500/30">
                    <div className="text-2xl font-theme-data font-bold text-blue-400">
                      {stageData.ideas.length}
                    </div>
                    <div className="text-xs font-theme-data text-[var(--text-muted)]">Ideas</div>
                  </div>
                  <div className="p-3 bg-emerald-500/10 border border-emerald-500/30">
                    <div className="text-2xl font-theme-data font-bold text-emerald-400">
                      {stageData.goals.length}
                    </div>
                    <div className="text-xs font-theme-data text-[var(--text-muted)]">Goals</div>
                  </div>
                  <div className="p-3 bg-amber-500/10 border border-amber-500/30">
                    <div className="text-2xl font-theme-data font-bold text-amber-400">
                      {stageData.tasks.length}
                    </div>
                    <div className="text-xs font-theme-data text-[var(--text-muted)]">Tasks</div>
                  </div>
                  <div className="p-3 bg-purple-500/10 border border-purple-500/30">
                    <div className="text-2xl font-theme-data font-bold text-purple-400">
                      {stageData.agents.length}
                    </div>
                    <div className="text-xs font-theme-data text-[var(--text-muted)]">Agents</div>
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <span className="text-xs font-theme-data text-[var(--text-muted)] block mb-1">
                      Total Nodes
                    </span>
                    <span className="font-theme-data text-sm text-[var(--acid-green)]">
                      {totalNodes}
                    </span>
                  </div>
                  <div>
                    <span className="text-xs font-theme-data text-[var(--text-muted)] block mb-1">
                      Total Edges
                    </span>
                    <span className="font-theme-data text-sm text-[var(--acid-green)]">
                      {stageData.edges.length}
                    </span>
                  </div>
                </div>

                {/* Provenance chain */}
                {provenances.length > 0 && (
                  <div className="border-t border-[var(--border)] pt-3">
                    <span className="text-xs font-theme-data text-[var(--text-muted)] block mb-2">
                      Provenance Chain
                    </span>
                    <div className="flex items-center gap-2 flex-wrap text-[10px] font-theme-data text-[var(--text-muted)]">
                      {provenances.map((p, i) => (
                        <div key={i} className="flex items-center gap-1">
                          {i > 0 && <span className="text-[var(--acid-green)]">&rarr;</span>}
                          <span className="px-1.5 py-0.5 border border-[var(--border)] bg-[var(--surface)]">
                            {String(p.method || 'unknown')}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* CTA buttons */}
                <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-4">
                  <button
                    onClick={handleReset}
                    className="px-6 py-2 font-theme-data text-sm border border-[var(--acid-green)]/30
                             text-[var(--acid-green)] hover:bg-[var(--acid-green)]/10 transition-colors"
                  >
                    [START OVER]
                  </button>
                  <Link
                    href="/pipeline"
                    className="px-6 py-2 font-theme-data text-sm bg-[var(--acid-green)] text-[var(--bg)]
                             hover:bg-[var(--acid-green)]/80 transition-colors text-center"
                  >
                    OPEN FULL PIPELINE
                  </Link>
                  <Link
                    href="/arena"
                    className="px-6 py-2 font-theme-data text-sm border border-[var(--acid-cyan)]/30
                             text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 transition-colors text-center"
                  >
                    TRY LIVE DEBATE
                  </Link>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Idle state: how it works */}
        {step === 'input' && !ideaText.trim() && (
          <div className="border border-[var(--acid-green)]/20 bg-[var(--surface)]/30 p-6 sm:p-8 text-center space-y-4">
            <div className="text-3xl sm:text-4xl font-theme-data text-[var(--acid-green)]/30">
              {'{ >> }'}
            </div>
            <h2 className="text-lg font-theme-data text-[var(--acid-green)]">
              Idea-to-Execution in 60 Seconds
            </h2>
            <div className="max-w-2xl mx-auto text-left space-y-3 text-sm font-theme-data text-[var(--text-muted)]">
              <div className="flex gap-3">
                <span className="text-blue-400 shrink-0">1.</span>
                <span>
                  <strong className="text-blue-400">PASTE IDEAS</strong> -- Type or paste raw ideas,
                  one per line. They become the root nodes of your pipeline.
                </span>
              </div>
              <div className="flex gap-3">
                <span className="text-emerald-400 shrink-0">2.</span>
                <span>
                  <strong className="text-emerald-400">GENERATE GOALS</strong> -- AI clusters your
                  ideas and derives actionable goals with key results.
                </span>
              </div>
              <div className="flex gap-3">
                <span className="text-amber-400 shrink-0">3.</span>
                <span>
                  <strong className="text-amber-400">PLAN ACTIONS</strong> -- Each goal is
                  decomposed into concrete tasks with priorities and effort estimates.
                </span>
              </div>
              <div className="flex gap-3">
                <span className="text-purple-400 shrink-0">4.</span>
                <span>
                  <strong className="text-purple-400">ORCHESTRATE</strong> -- Tasks are assigned to
                  specialized agents (Researcher, Implementer, Reviewer) for execution.
                </span>
              </div>
            </div>
            <p className="text-xs font-theme-data text-[var(--text-muted)]/60 pt-2">
              Every node carries a provenance hash. The full DAG is traceable from idea to agent.
            </p>
          </div>
        )}

        {/* Footer */}
        <div className="text-center text-xs font-theme-data text-[var(--text-muted)]/60 pt-4 border-t border-[var(--border)]">
          {usedFallback
            ? 'Running in demo mode with sample data. Start the Aragora server to see live AI-powered pipeline transitions.'
            : "Powered by Aragora's idea-to-execution pipeline. Each transition uses AI to cluster, decompose, and orchestrate."}
        </div>
      </div>
    </main>
  );
}
