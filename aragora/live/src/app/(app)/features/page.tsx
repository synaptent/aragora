'use client';

import { useState, useMemo } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useFeatures } from '@/hooks/useFeatures';

type FeatureStatus = 'active' | 'available' | 'beta';

interface Feature {
  name: string;
  description: string;
  status: FeatureStatus;
  href?: string;
}

interface FeatureCategory {
  id: string;
  title: string;
  description: string;
  features: Feature[];
}

const STATUS_STYLES: Record<FeatureStatus, { bg: string; text: string; label: string }> = {
  active: { bg: 'bg-emerald-500/10', text: 'text-emerald-400', label: 'ACTIVE' },
  available: { bg: 'bg-blue-500/10', text: 'text-blue-400', label: 'AVAILABLE' },
  beta: { bg: 'bg-amber-500/10', text: 'text-amber-400', label: 'BETA' },
};

const CATEGORIES: FeatureCategory[] = [
  {
    id: 'debate',
    title: 'Debate Engine',
    description: 'Multi-agent adversarial debate orchestration with consensus detection',
    features: [
      { name: 'Arena Orchestrator', description: 'Run structured debates with configurable rounds, agents, and consensus methods', status: 'active', href: '/arena' },
      { name: 'Consensus Detection', description: 'Automatic convergence and majority-vote consensus with confidence scoring', status: 'active', href: '/consensus' },
      { name: 'ELO Rankings', description: 'Agent skill tracking via ELO rating system with tournament support', status: 'active', href: '/leaderboard' },
      { name: 'Decision Receipts', description: 'Cryptographic audit trails with SHA-256 hashing for every decision', status: 'active', href: '/receipts' },
      { name: 'Trickster Detection', description: 'Hollow consensus detection to prevent groupthink among agents', status: 'active', href: '/spectate' },
      { name: 'Live Explainability', description: 'Real-time factor tracking during debates via EventBus', status: 'active', href: '/spectate' },
      { name: 'Graph Debates', description: 'Graph-structured argument topology for non-linear debates', status: 'active', href: '/debates/graph' },
      { name: 'Matrix Debates', description: 'Multi-dimensional debate analysis across parameters', status: 'active', href: '/debates/matrix' },
      { name: 'Debate Breakpoints', description: 'Pause and resume debate execution at any point', status: 'active', href: '/breakpoints' },
      { name: 'Batch Debates', description: 'Run multiple debates in parallel with consolidated results', status: 'active', href: '/batch' },
      { name: 'Debate Forks', description: 'Fork debates to explore alternative argument paths', status: 'active', href: '/forks' },
      { name: 'Impasse Resolution', description: 'Tools for resolving deadlocked debates', status: 'active', href: '/impasse' },
      { name: 'Argument Analysis', description: 'Deep structural analysis of debate arguments', status: 'active', href: '/argument-analysis' },
    ],
  },
  {
    id: 'knowledge',
    title: 'Knowledge Management',
    description: 'Unified knowledge superstructure with 41 adapters across all memory systems',
    features: [
      { name: 'Knowledge Mound', description: '41 adapters integrating memory, consensus, evidence, and debate knowledge', status: 'active', href: '/knowledge' },
      { name: 'Semantic Search', description: 'Vector-based knowledge retrieval with confidence scoring', status: 'active', href: '/knowledge' },
      { name: 'Contradiction Detection', description: 'Automatic identification of conflicting knowledge nodes', status: 'active', href: '/knowledge' },
      { name: 'Multi-Tier Memory', description: 'Fast/Medium/Slow/Glacial memory tiers with TTL-based promotion', status: 'active', href: '/memory' },
      { name: 'Memory Analytics', description: 'Memory usage statistics, tier distribution, and pressure monitoring', status: 'active', href: '/memory-analytics' },
      { name: 'Supermemory', description: 'Cross-session external memory for persistent organizational learning', status: 'active', href: '/intelligence' },
      { name: 'Unified Memory Gateway', description: 'Fan-out queries across ContinuumMemory, KM, Supermemory, and claude-mem', status: 'active', href: '/intelligence' },
      { name: 'Cross-Debate Learning', description: 'Institutional knowledge injection between debates', status: 'active', href: '/knowledge/learning' },
      { name: 'Evidence Browser', description: 'Browse and verify evidence collected from debates', status: 'active', href: '/evidence' },
      { name: 'Repository Indexing', description: 'Index code repositories into the knowledge graph', status: 'active', href: '/repository' },
      { name: 'RLM Context', description: 'Recursive Language Model context stored as Python REPL variables', status: 'active', href: '/rlm' },
    ],
  },
  {
    id: 'agents',
    title: 'Agent Types',
    description: '42 agent types from 10+ providers with automatic fallback and resilience',
    features: [
      { name: 'Anthropic (Opus 4.5)', description: 'Claude API agent with structured output support', status: 'active', href: '/agents' },
      { name: 'OpenAI (GPT 5.2)', description: 'GPT API agent with function calling', status: 'active', href: '/agents' },
      { name: 'Gemini (3.1 Pro)', description: 'Google Gemini with multimodal capabilities', status: 'active', href: '/agents' },
      { name: 'Grok (4)', description: 'xAI Grok agent with real-time knowledge', status: 'active', href: '/agents' },
      { name: 'DeepSeek / R1', description: 'Reasoning-optimized models via OpenRouter', status: 'active', href: '/agents' },
      { name: 'Qwen / Kimi / Llama / Mistral', description: 'Broad model coverage via OpenRouter fallback', status: 'active', href: '/agents' },
      { name: 'Agent Performance', description: 'Deep-dive ELO trends, model comparison, and domain analytics', status: 'active', href: '/agents/performance' },
      { name: 'Agent Calibration', description: 'Brier score tracking and domain-specific performance assessment', status: 'active', href: '/calibration' },
      { name: 'Agent Recommender', description: 'AI-powered team composition suggestions based on task context', status: 'active', href: '/agents' },
      { name: 'Circuit Breaker', description: 'Automatic failure handling with OpenRouter fallback on quota errors', status: 'active', href: '/control-plane' },
      { name: 'Tournaments', description: 'Agent tournament competitions with bracket tracking', status: 'active', href: '/tournaments' },
    ],
  },
  {
    id: 'pipeline',
    title: 'Pipeline & Workflow',
    description: 'Idea-to-Execution pipeline with DAG visualization and workflow automation',
    features: [
      { name: 'Pipeline Canvas', description: '4-stage pipeline: Ideas, Goals, Actions, Orchestration with visual DAG', status: 'active', href: '/pipeline' },
      { name: 'Brain Dump', description: 'Paste unstructured thoughts and auto-organize into execution plans', status: 'active', href: '/pipeline' },
      { name: 'Workflow Engine', description: 'DAG-based automation with 50+ pre-built templates', status: 'active', href: '/workflows' },
      { name: 'Workflow Builder', description: 'Visual drag-and-drop workflow editor', status: 'active', href: '/workflows/builder' },
      { name: 'Workflow Templates', description: '50+ templates across 6 categories with pattern factories', status: 'active', href: '/templates' },
      { name: 'Mission Control', description: 'Unified dashboard for pipeline and orchestration status', status: 'active', href: '/mission-control' },
      { name: 'Scheduler', description: 'Priority-based task distribution and scheduling', status: 'active', href: '/scheduler' },
      { name: 'Queue Management', description: 'Task queue with priority ordering and status tracking', status: 'active', href: '/queue' },
    ],
  },
  {
    id: 'analytics',
    title: 'Analytics & Intelligence',
    description: 'Comprehensive debate metrics, agent performance, usage trends, and system intelligence',
    features: [
      { name: 'Analytics Dashboard', description: 'Debate metrics, agent performance, usage trends, and cost analysis', status: 'active', href: '/analytics' },
      { name: 'System Intelligence', description: 'Aggregated learning insights, agent performance, and institutional memory', status: 'active', href: '/intelligence' },
      { name: 'Admin Intelligence', description: 'ELO trends, improvement queue, and system learning overview', status: 'active', href: '/admin/intelligence' },
      { name: 'Cost Tracking', description: 'Per-model and per-provider cost breakdown with budget alerts', status: 'active', href: '/costs' },
      { name: 'Observability', description: 'Prometheus metrics, Grafana dashboards, OpenTelemetry tracing', status: 'active', href: '/observability' },
      { name: 'Usage Dashboard', description: 'Token usage, API call volume, and trend analysis', status: 'active', href: '/usage' },
      { name: 'Pulse (Trending Topics)', description: 'HackerNews, Reddit, Twitter ingestors with quality filtering', status: 'active', href: '/pulse' },
      { name: 'Evaluation', description: 'Agent and debate quality evaluation framework', status: 'active', href: '/evaluation' },
      { name: 'Quality Metrics', description: 'Debate quality scoring and assessment tools', status: 'active', href: '/quality' },
      { name: 'Uncertainty Tracking', description: 'Track and visualize uncertainty across debate outcomes', status: 'active', href: '/uncertainty' },
      { name: 'Insights', description: 'AI-generated insights from debate patterns and outcomes', status: 'active', href: '/insights' },
    ],
  },
  {
    id: 'enterprise',
    title: 'Enterprise & Governance',
    description: 'Production-ready enterprise features: RBAC, compliance, multi-tenancy, dashboard',
    features: [
      { name: 'Decision Integrity', description: 'End-to-end decision quality assurance with provenance tracking', status: 'active', href: '/decision-integrity' },
      { name: 'Dashboard', description: 'Agent registry, task scheduler, health monitoring, and policy governance', status: 'active', href: '/control-plane' },
      { name: 'RBAC v2', description: '360+ fine-grained permissions with role hierarchy and middleware', status: 'active', href: '/control-plane' },
      { name: 'Multi-Tenancy', description: 'Tenant isolation, resource quotas, and usage metering', status: 'active', href: '/admin/tenants' },
      { name: 'Moderation', description: 'Spam filtering and content validation for debates', status: 'active', href: '/moderation' },
      { name: 'Vertical Specialists', description: 'Healthcare (HIPAA), Financial (SOX), Legal vertical guides', status: 'active', href: '/verticals' },
    ],
  },
  {
    id: 'security',
    title: 'Security',
    description: 'Enterprise-grade security with encryption, RBAC, and anomaly detection',
    features: [
      { name: 'AES-256-GCM Encryption', description: 'Data encryption at rest and in transit', status: 'active', href: '/security' },
      { name: 'Key Rotation', description: 'Automated cryptographic key rotation pipeline', status: 'active', href: '/security' },
      { name: 'SSRF Protection', description: 'Safe HTTP wrapper preventing server-side request forgery', status: 'active', href: '/security-scan' },
      { name: 'Anomaly Detection', description: 'Real-time security anomaly detection and alerting', status: 'active', href: '/security-scan' },
      { name: 'OIDC/SAML SSO', description: 'Enterprise single sign-on with MFA support', status: 'active', href: '/auth/login' },
      { name: 'Red Team', description: 'Adversarial testing tools for debate and agent security', status: 'active', href: '/red-team' },
    ],
  },
  {
    id: 'compliance',
    title: 'Compliance',
    description: 'SOC 2 controls, GDPR support, EU AI Act artifact generation',
    features: [
      { name: 'EU AI Act Compliance', description: 'Risk classification, conformity assessment, and artifact bundle generation', status: 'active', href: '/compliance' },
      { name: 'Audit Trails', description: 'Complete audit logging of all decisions and actions', status: 'active', href: '/audit' },
      { name: 'Privacy Controls', description: 'GDPR anonymization, consent management, data deletion, retention policies', status: 'active', href: '/privacy' },
      { name: 'Policy Governance', description: 'Conflict detection, distributed cache, and sync scheduling', status: 'active', href: '/policy' },
    ],
  },
  {
    id: 'self-improvement',
    title: 'Self-Improvement',
    description: 'Autonomous Nomic Loop for self-directing codebase improvement',
    features: [
      { name: 'Nomic Loop', description: 'Autonomous cycle: debate improvements, design, implement, verify', status: 'active', href: '/self-improve' },
      { name: 'Nomic Control Panel', description: 'Monitor and control running Nomic Loop cycles', status: 'active', href: '/nomic-control' },
      { name: 'Meta-Planner', description: 'Debate-driven goal prioritization with cross-cycle learning', status: 'active', href: '/self-improve' },
      { name: 'Branch Coordinator', description: 'Parallel git worktree management for safe changes', status: 'active', href: '/self-improve' },
      { name: 'Pipeline (Idea-to-Execution)', description: '4-stage pipeline: Ideas, Goals, Workflows, Orchestration', status: 'active', href: '/pipeline' },
      { name: 'Spectator Mode', description: 'Real-time observation of autonomous improvement cycles', status: 'active', href: '/spectate' },
      { name: 'Introspection', description: 'Agent self-awareness and meta-cognition monitoring', status: 'active', href: '/introspection' },
      { name: 'Genesis', description: 'Fractal resolution, agent evolution, and Argonaut ledger', status: 'active', href: '/genesis' },
    ],
  },
  {
    id: 'integrations',
    title: 'Integrations & Connectors',
    description: 'Broad connector ecosystem for enterprise and consumer platforms',
    features: [
      { name: 'Slack / Discord / Teams', description: 'Chat platform connectors for debate interfaces', status: 'active', href: '/integrations' },
      { name: 'Telegram / WhatsApp', description: 'Mobile messaging connectors with bidirectional routing', status: 'active', href: '/social' },
      { name: 'Kafka / RabbitMQ', description: 'Enterprise event stream ingestion for real-time data', status: 'active', href: '/connectors' },
      { name: 'Zapier / Webhooks', description: 'No-code automation and custom webhook delivery', status: 'active', href: '/webhooks' },
      { name: 'LangChain Integration', description: 'LangChain tools and chains for debate workflows', status: 'available' },
      { name: 'MCP Server', description: 'Model Context Protocol server for tool-use AI agents', status: 'active', href: '/mcp' },
      { name: 'Plugins', description: 'Extensible plugin system for custom integrations', status: 'active', href: '/plugins' },
    ],
  },
  {
    id: 'developer',
    title: 'Developer Tools',
    description: 'Development, debugging, and code quality tools',
    features: [
      { name: 'Codebase Audit', description: 'Automated codebase analysis with bug detection and security scanning', status: 'active', href: '/codebase-audit' },
      { name: 'Code Review', description: 'AI-powered multi-agent code review with structured feedback', status: 'active', href: '/code-review' },
      { name: 'Security Scan', description: 'Automated security vulnerability detection', status: 'active', href: '/security-scan' },
      { name: 'Sandbox', description: 'Docker-based safe code execution environment', status: 'active', href: '/sandbox' },
      { name: 'API Explorer', description: 'Interactive API documentation and testing', status: 'active', href: '/api-explorer' },
      { name: 'API Documentation', description: 'Full OpenAPI docs with 2,000+ operations', status: 'active', href: '/api-docs' },
      { name: 'Developer Console', description: 'Developer tools and debugging utilities', status: 'active', href: '/developer' },
      { name: 'Marketplace', description: 'Agent template and protocol marketplace', status: 'active', href: '/marketplace' },
    ],
  },
  {
    id: 'voice',
    title: 'Voice & Media',
    description: 'TTS voice synthesis and audio processing for debate channels',
    features: [
      { name: 'Voice Sessions', description: 'Real-time voice streaming for debate participation', status: 'active', href: '/voice' },
      { name: 'TTS Integration', description: 'Text-to-speech synthesis for debate outputs', status: 'active', href: '/speech' },
      { name: 'Transcription', description: 'Audio-to-text transcription for debate input', status: 'active', href: '/transcribe' },
    ],
  },
];

export default function FeaturesPage() {
  const [filter, setFilter] = useState<FeatureStatus | 'all'>('all');
  const [searchQuery, setSearchQuery] = useState('');

  // Dynamic feature availability from the backend /api/features endpoint
  const {
    features: backendFeatures,
    loading: featuresLoading,
    isAvailable,
    getFeatureInfo,
  } = useFeatures();

  // Count how many features have confirmed backend availability
  const backendAvailableCount = useMemo(
    () => backendFeatures?.available?.length ?? 0,
    [backendFeatures],
  );
  const backendUnavailableCount = useMemo(
    () => backendFeatures?.unavailable?.length ?? 0,
    [backendFeatures],
  );

  const filteredCategories = CATEGORIES.map(cat => ({
    ...cat,
    features: cat.features.filter(f => {
      const matchesFilter = filter === 'all' || f.status === filter;
      const matchesSearch = !searchQuery.trim() ||
        f.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        f.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
        cat.title.toLowerCase().includes(searchQuery.toLowerCase());
      return matchesFilter && matchesSearch;
    }),
  })).filter(cat => cat.features.length > 0);

  const totalFeatures = CATEGORIES.reduce((sum, cat) => sum + cat.features.length, 0);
  const activeCount = CATEGORIES.reduce((sum, cat) => sum + cat.features.filter(f => f.status === 'active').length, 0);
  const betaCount = CATEGORIES.reduce((sum, cat) => sum + cat.features.filter(f => f.status === 'beta').length, 0);

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        <div className="container mx-auto px-4 py-6 max-w-5xl">
          {/* Header */}
          <div className="mb-6">
            <h1 className="text-2xl font-mono text-acid-green mb-2">
              {'>'} FEATURE DISCOVERY
            </h1>
            <p className="text-text-muted font-mono text-sm">
              Explore the full capabilities of the Aragora Decision Integrity Platform.
            </p>
          </div>

          {/* Stats */}
          <div className="grid grid-cols-3 md:grid-cols-4 gap-3 mb-6">
            <div className="p-3 bg-surface border border-border text-center">
              <div className="text-xl font-mono text-acid-green">{totalFeatures}</div>
              <div className="text-[10px] font-mono text-text-muted">Total Features</div>
            </div>
            <div className="p-3 bg-surface border border-border text-center">
              <div className="text-xl font-mono text-emerald-400">{activeCount}</div>
              <div className="text-[10px] font-mono text-text-muted">Active</div>
            </div>
            <div className="p-3 bg-surface border border-border text-center">
              <div className="text-xl font-mono text-amber-400">{betaCount}</div>
              <div className="text-[10px] font-mono text-text-muted">Beta</div>
            </div>
            <div className="hidden md:block p-3 bg-surface border border-border text-center">
              <div className="text-xl font-mono text-blue-400">{CATEGORIES.length}</div>
              <div className="text-[10px] font-mono text-text-muted">Categories</div>
            </div>
            {backendFeatures && (
              <div className="p-3 bg-surface border border-border text-center">
                <div className="text-xl font-mono text-acid-cyan">{backendAvailableCount}</div>
                <div className="text-[10px] font-mono text-text-muted">Backend Ready</div>
              </div>
            )}
          </div>

          {/* Backend Feature Status */}
          {!featuresLoading && backendFeatures && (
            <div className="mb-4 p-3 border border-acid-cyan/30 bg-acid-cyan/5 flex items-center gap-3">
              <span className="w-2 h-2 rounded-full bg-acid-cyan animate-pulse" />
              <span className="text-xs font-mono text-acid-cyan">
                Backend connected: {backendAvailableCount} features available, {backendUnavailableCount} unavailable
              </span>
            </div>
          )}

          {/* Search + Filter */}
          <div className="flex flex-wrap gap-3 mb-6">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search features..."
              className="flex-1 min-w-[200px] px-3 py-2 bg-surface border border-border text-text font-mono text-sm focus:border-acid-green focus:outline-none"
            />
            <div className="flex gap-1">
              {(['all', 'active', 'available', 'beta'] as const).map((s) => (
                <button
                  key={s}
                  onClick={() => setFilter(s)}
                  className={`px-3 py-2 text-xs font-mono transition-colors ${
                    filter === s
                      ? 'bg-acid-green text-bg'
                      : 'text-text-muted hover:text-text border border-border'
                  }`}
                >
                  {s.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          {/* Feature Categories */}
          <div className="space-y-6">
            {filteredCategories.map((category) => (
              <section key={category.id} className="bg-surface border border-border">
                <div className="p-4 border-b border-border">
                  <h2 className="text-sm font-mono text-acid-green font-bold uppercase">
                    {'>'} {category.title}
                  </h2>
                  <p className="text-xs font-mono text-text-muted mt-1">{category.description}</p>
                </div>
                <div className="divide-y divide-border">
                  {category.features.map((feature) => {
                    const style = STATUS_STYLES[feature.status];
                    // Lookup backend availability for this feature (normalize name to snake_case id)
                    const featureId = feature.name.toLowerCase().replace(/[\s/]+/g, '_').replace(/[^a-z0-9_]/g, '');
                    const backendInfo = getFeatureInfo(featureId);
                    const backendReady = backendFeatures ? isAvailable(featureId) : null;
                    const content = (
                      <div className="p-3 flex items-center justify-between hover:bg-bg/50 transition-colors">
                        <div className="flex-1 min-w-0 mr-3">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-mono text-text">{feature.name}</span>
                            <span className={`px-1.5 py-0.5 text-[10px] font-mono ${style.bg} ${style.text} border border-current/20`}>
                              {style.label}
                            </span>
                            {backendReady === true && (
                              <span className="px-1.5 py-0.5 text-[10px] font-mono bg-acid-cyan/10 text-acid-cyan border border-acid-cyan/20" title={backendInfo?.description || 'Available on backend'}>
                                LIVE
                              </span>
                            )}
                            {backendReady === false && (
                              <span className="px-1.5 py-0.5 text-[10px] font-mono bg-text-muted/10 text-text-muted border border-text-muted/20" title={backendInfo?.reason || 'Not available on backend'}>
                                OFFLINE
                              </span>
                            )}
                          </div>
                          <p className="text-xs font-mono text-text-muted mt-0.5 truncate">
                            {backendInfo?.description || feature.description}
                          </p>
                          {backendInfo?.reason && (
                            <p className="text-[10px] font-mono text-acid-yellow mt-0.5">{backendInfo.reason}</p>
                          )}
                        </div>
                        {feature.href && (
                          <span className="text-xs font-mono text-acid-green/60 flex-shrink-0">
                            {'->'}
                          </span>
                        )}
                      </div>
                    );

                    if (feature.href) {
                      return (
                        <Link key={feature.name} href={feature.href} className="block">
                          {content}
                        </Link>
                      );
                    }
                    return <div key={feature.name}>{content}</div>;
                  })}
                </div>
              </section>
            ))}
          </div>

          {filteredCategories.length === 0 && (
            <div className="text-center py-12 text-text-muted font-mono">
              No features match your search.
            </div>
          )}
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-mono py-8 border-t border-acid-green/20 mt-8">
          <p className="text-text-muted">{'>'} ARAGORA // FEATURE DISCOVERY</p>
        </footer>
      </main>
    </>
  );
}
