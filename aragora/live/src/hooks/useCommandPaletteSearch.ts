'use client';

import { useCallback, useEffect, useRef } from 'react';
import { useDebounce } from './useTimers';
import { useBackend } from '@/components/BackendSelector';
import { useCommandPaletteStore } from '@/store/commandPaletteStore';
import type { SearchResult, SearchCategory, QuickAction } from '@/components/command-palette/types';
import { QUICK_ACTIONS } from '@/components/command-palette/types';

// ---------------------------------------------------------------------------
// Complete navigation page index for client-side search
// Organized by sidebar categories, covering all 147 routes
// ---------------------------------------------------------------------------

const NAVIGATION_PAGES: SearchResult[] = [
  // -- Start --
  {
    id: 'page-hub',
    type: 'pages',
    title: 'Hub',
    subtitle: 'Start / Main dashboard',
    href: '/hub',
    icon: '+',
    keywords: ['home', 'main', 'start'],
  },
  {
    id: 'page-arena',
    type: 'pages',
    title: 'New Debate',
    subtitle: 'Start / Create a debate',
    href: '/arena',
    icon: '!',
    keywords: ['create', 'start', 'debate'],
  },
  {
    id: 'page-playbooks',
    type: 'pages',
    title: 'Playbooks',
    subtitle: 'Start / Decision playbooks',
    href: '/playbooks',
    icon: 'P',
    keywords: ['playbook', 'recipe'],
  },
  {
    id: 'page-gauntlet',
    type: 'pages',
    title: 'Stress Test',
    subtitle: 'Start / Decision gauntlet',
    href: '/gauntlet',
    icon: '%',
    keywords: ['gauntlet', 'stress', 'test'],
  },
  {
    id: 'page-code-review',
    type: 'pages',
    title: 'Code Review',
    subtitle: 'Start / Security code review',
    href: '/code-review',
    icon: '<',
    keywords: ['code', 'review', 'security'],
  },
  {
    id: 'page-audit',
    type: 'pages',
    title: 'Document Audit',
    subtitle: 'Start / Compliance audit',
    href: '/audit',
    icon: '|',
    keywords: ['audit', 'document', 'compliance'],
  },
  {
    id: 'page-audit-new',
    type: 'pages',
    title: 'New Audit',
    subtitle: 'Start / Create new audit',
    href: '/audit/new',
    icon: '|',
    keywords: ['audit', 'new', 'create'],
  },
  {
    id: 'page-audit-templates',
    type: 'pages',
    title: 'Audit Templates',
    subtitle: 'Start / Audit templates',
    href: '/audit/templates',
    icon: '|',
    keywords: ['audit', 'template'],
  },
  {
    id: 'page-audit-view',
    type: 'pages',
    title: 'View Audit',
    subtitle: 'Start / View audit results',
    href: '/audit/view',
    icon: '|',
    keywords: ['audit', 'view', 'results'],
  },

  // -- Pipeline --
  {
    id: 'page-pipeline',
    type: 'pages',
    title: 'Pipeline',
    subtitle: 'Pipeline / Idea-to-Execution',
    href: '/pipeline',
    icon: '|',
    keywords: ['pipeline', 'execution'],
  },
  {
    id: 'page-ideas',
    type: 'pages',
    title: 'Ideas',
    subtitle: 'Pipeline / Idea capture',
    href: '/ideas',
    icon: '~',
    keywords: ['ideas', 'brainstorm'],
  },
  {
    id: 'page-goals',
    type: 'pages',
    title: 'Goals',
    subtitle: 'Pipeline / Goal tracking',
    href: '/goals',
    icon: 'G',
    keywords: ['goals', 'objectives'],
  },
  {
    id: 'page-actions',
    type: 'pages',
    title: 'Actions',
    subtitle: 'Pipeline / Action items',
    href: '/actions',
    icon: 'A',
    keywords: ['actions', 'tasks', 'items'],
  },
  {
    id: 'page-orchestration',
    type: 'pages',
    title: 'Orchestration',
    subtitle: 'Pipeline / Workflow orchestration',
    href: '/orchestration',
    icon: '!',
    keywords: ['orchestration', 'workflow'],
  },

  // -- Decisions --
  {
    id: 'page-deliberations',
    type: 'pages',
    title: 'Deliberations',
    subtitle: 'Decisions / Deliberation threads',
    href: '/deliberations',
    icon: '\u2696',
    keywords: ['deliberation', 'discussion'],
  },
  {
    id: 'page-batch',
    type: 'pages',
    title: 'Batch Debates',
    subtitle: 'Decisions / Batch processing',
    href: '/batch',
    icon: '\u229E',
    keywords: ['batch', 'bulk', 'debates'],
  },
  {
    id: 'page-forks',
    type: 'pages',
    title: 'Forks',
    subtitle: 'Decisions / Debate forks',
    href: '/forks',
    icon: '\u2442',
    keywords: ['fork', 'branch', 'diverge'],
  },
  {
    id: 'page-impasse',
    type: 'pages',
    title: 'Impasse',
    subtitle: 'Decisions / Impasse detection',
    href: '/impasse',
    icon: '\u26A0',
    keywords: ['impasse', 'deadlock', 'stuck'],
  },
  {
    id: 'page-compare',
    type: 'pages',
    title: 'Compare',
    subtitle: 'Decisions / Side-by-side comparison',
    href: '/compare',
    icon: '\u2194',
    keywords: ['compare', 'diff', 'side'],
  },
  {
    id: 'page-crux',
    type: 'pages',
    title: 'Crux',
    subtitle: 'Decisions / Key disagreements',
    href: '/crux',
    icon: '\u2020',
    keywords: ['crux', 'disagreement', 'key'],
  },
  {
    id: 'page-spectate',
    type: 'pages',
    title: 'Spectate',
    subtitle: 'Decisions / Watch live debates',
    href: '/spectate',
    icon: '\u25C9',
    keywords: ['spectate', 'watch', 'live'],
  },
  {
    id: 'page-replays',
    type: 'pages',
    title: 'Replays',
    subtitle: 'Decisions / Debate replays',
    href: '/replays',
    icon: '\u21BB',
    keywords: ['replay', 'history', 'rewatch'],
  },
  {
    id: 'page-consensus',
    type: 'pages',
    title: 'Consensus',
    subtitle: 'Decisions / Consensus explorer',
    href: '/consensus',
    icon: '#',
    keywords: ['consensus', 'agreement'],
  },

  // -- Browse --
  {
    id: 'page-debates',
    type: 'pages',
    title: 'Debates',
    subtitle: 'Browse / Past debates',
    href: '/debates',
    icon: '#',
    keywords: ['debates', 'browse', 'history'],
  },
  {
    id: 'page-debates-graph',
    type: 'pages',
    title: 'Debate Graph',
    subtitle: 'Browse / Graph visualization',
    href: '/debates/graph',
    icon: '#',
    keywords: ['graph', 'debate', 'visualize'],
  },
  {
    id: 'page-debates-matrix',
    type: 'pages',
    title: 'Debate Matrix',
    subtitle: 'Browse / Matrix view',
    href: '/debates/matrix',
    icon: '#',
    keywords: ['matrix', 'debate', 'grid'],
  },
  {
    id: 'page-debates-provenance',
    type: 'pages',
    title: 'Debate Provenance',
    subtitle: 'Browse / Provenance chain',
    href: '/debates/provenance',
    icon: '#',
    keywords: ['provenance', 'debate', 'chain'],
  },
  {
    id: 'page-knowledge',
    type: 'pages',
    title: 'Knowledge',
    subtitle: 'Browse / Knowledge base',
    href: '/knowledge',
    icon: '?',
    keywords: ['knowledge', 'search', 'facts'],
  },
  {
    id: 'page-knowledge-learning',
    type: 'pages',
    title: 'Cross-Debate Learning',
    subtitle: 'Browse / Knowledge learning',
    href: '/knowledge/learning',
    icon: '\u2042',
    keywords: ['learning', 'cross-debate', 'knowledge'],
  },
  {
    id: 'page-leaderboard',
    type: 'pages',
    title: 'Leaderboard',
    subtitle: 'Browse / Agent rankings',
    href: '/leaderboard',
    icon: '^',
    keywords: ['leaderboard', 'ranking', 'elo'],
  },
  {
    id: 'page-agents',
    type: 'pages',
    title: 'Agents',
    subtitle: 'Browse / Agent recommender',
    href: '/agents',
    icon: '&',
    keywords: ['agents', 'recommend'],
  },
  {
    id: 'page-marketplace',
    type: 'pages',
    title: 'Marketplace',
    subtitle: 'Browse / Agent marketplace',
    href: '/marketplace',
    icon: '$',
    keywords: ['marketplace', 'store', 'plugins'],
  },
  {
    id: 'page-usage',
    type: 'pages',
    title: 'Usage',
    subtitle: 'Browse / Usage statistics',
    href: '/usage',
    icon: '%',
    keywords: ['usage', 'stats', 'costs'],
  },
  {
    id: 'page-gallery',
    type: 'pages',
    title: 'Gallery',
    subtitle: 'Browse / Public debates',
    href: '/gallery',
    icon: '*',
    keywords: ['gallery', 'public'],
  },
  {
    id: 'page-about',
    type: 'pages',
    title: 'About',
    subtitle: 'Browse / About Aragora',
    href: '/about',
    icon: 'i',
    keywords: ['about', 'info'],
  },
  {
    id: 'page-portal',
    type: 'pages',
    title: 'Portal',
    subtitle: 'Browse / User portal',
    href: '/portal',
    icon: '\u2302',
    keywords: ['portal', 'home'],
  },
  {
    id: 'page-social',
    type: 'pages',
    title: 'Social',
    subtitle: 'Browse / Social feed',
    href: '/social',
    icon: '\u263A',
    keywords: ['social', 'feed', 'community'],
  },
  {
    id: 'page-moments',
    type: 'pages',
    title: 'Moments',
    subtitle: 'Browse / Agent moments',
    href: '/moments',
    icon: '\u25C6',
    keywords: ['moments', 'highlights'],
  },
  {
    id: 'page-status',
    type: 'pages',
    title: 'Status',
    subtitle: 'Browse / System status',
    href: '/system-status',
    icon: '\u2713',
    keywords: ['status', 'health', 'system'],
  },
  {
    id: 'page-dashboard',
    type: 'pages',
    title: 'Dashboard',
    subtitle: 'Browse / Overview dashboard',
    href: '/dashboard',
    icon: '#',
    keywords: ['dashboard', 'overview'],
  },

  // -- Analytics & Insights --
  {
    id: 'page-insights',
    type: 'pages',
    title: 'Insights',
    subtitle: 'Analytics / Decision insights',
    href: '/insights',
    icon: '\u272A',
    keywords: ['insights', 'analysis'],
  },
  {
    id: 'page-intelligence',
    type: 'pages',
    title: 'Intelligence',
    subtitle: 'Analytics / Intelligence feed',
    href: '/intelligence',
    icon: '\u269B',
    keywords: ['intelligence', 'feed'],
  },
  {
    id: 'page-calibration',
    type: 'pages',
    title: 'Calibration',
    subtitle: 'Analytics / Agent calibration',
    href: '/calibration',
    icon: '\u2316',
    keywords: ['calibration', 'accuracy'],
  },
  {
    id: 'page-evaluation',
    type: 'pages',
    title: 'Evaluation',
    subtitle: 'Analytics / Debate evaluation',
    href: '/evaluation',
    icon: '\u2606',
    keywords: ['evaluation', 'assess'],
  },
  {
    id: 'page-uncertainty',
    type: 'pages',
    title: 'Uncertainty',
    subtitle: 'Analytics / Uncertainty tracking',
    href: '/uncertainty',
    icon: '\u00B1',
    keywords: ['uncertainty', 'confidence'],
  },
  {
    id: 'page-quality',
    type: 'pages',
    title: 'Quality',
    subtitle: 'Analytics / Quality metrics',
    href: '/quality',
    icon: '\u2605',
    keywords: ['quality', 'metrics'],
  },
  {
    id: 'page-costs',
    type: 'pages',
    title: 'Costs',
    subtitle: 'Analytics / Cost tracking',
    href: '/costs',
    icon: '\u00A2',
    keywords: ['costs', 'spending', 'budget'],
  },
  {
    id: 'page-tournaments',
    type: 'pages',
    title: 'Tournaments',
    subtitle: 'Analytics / Agent tournaments',
    href: '/tournaments',
    icon: '\u2295',
    keywords: ['tournament', 'bracket', 'competition'],
  },
  {
    id: 'page-analytics',
    type: 'pages',
    title: 'Analytics',
    subtitle: 'Analytics / Usage analytics',
    href: '/analytics',
    icon: '~',
    keywords: ['analytics', 'charts', 'data'],
  },

  // -- Enterprise --
  {
    id: 'page-compliance',
    type: 'pages',
    title: 'Compliance',
    subtitle: 'Enterprise / Compliance dashboard',
    href: '/compliance',
    icon: '\u2713',
    keywords: ['compliance', 'soc2', 'gdpr'],
  },
  {
    id: 'page-control-plane',
    type: 'pages',
    title: 'Dashboard',
    subtitle: 'Enterprise / Agent dashboard',
    href: '/control-plane',
    icon: '\u25CE',
    keywords: ['dashboard', 'platform', 'management'],
  },
  {
    id: 'page-receipts',
    type: 'pages',
    title: 'Receipts',
    subtitle: 'Enterprise / Decision receipts',
    href: '/receipts',
    icon: '$',
    keywords: ['receipts', 'audit', 'trail'],
  },
  {
    id: 'page-policy',
    type: 'pages',
    title: 'Policy',
    subtitle: 'Enterprise / Policy governance',
    href: '/policy',
    icon: '\u2696',
    keywords: ['policy', 'rules', 'governance'],
  },
  {
    id: 'page-privacy',
    type: 'pages',
    title: 'Privacy',
    subtitle: 'Enterprise / Privacy controls',
    href: '/privacy',
    icon: '\u229E',
    keywords: ['privacy', 'gdpr', 'data'],
  },
  {
    id: 'page-moderation',
    type: 'pages',
    title: 'Moderation',
    subtitle: 'Enterprise / Content moderation',
    href: '/moderation',
    icon: '\u2691',
    keywords: ['moderation', 'content', 'filter'],
  },
  {
    id: 'page-security',
    type: 'pages',
    title: 'Security',
    subtitle: 'Enterprise / Security overview',
    href: '/security',
    icon: '\u26BF',
    keywords: ['security', 'encryption'],
  },
  {
    id: 'page-observability',
    type: 'pages',
    title: 'Observability',
    subtitle: 'Enterprise / Metrics & tracing',
    href: '/observability',
    icon: '\u25C9',
    keywords: ['observability', 'metrics', 'tracing'],
  },
  {
    id: 'page-pulse',
    type: 'pages',
    title: 'Pulse',
    subtitle: 'Enterprise / Trending topics',
    href: '/pulse',
    icon: '\u2764',
    keywords: ['pulse', 'trending', 'topics'],
  },

  // -- Tools --
  {
    id: 'page-inbox',
    type: 'pages',
    title: 'Inbox',
    subtitle: 'Tools / Notifications',
    href: '/inbox',
    icon: '@',
    keywords: ['inbox', 'notifications', 'messages'],
  },
  {
    id: 'page-inbox-callback',
    type: 'pages',
    title: 'Inbox Callback',
    subtitle: 'Tools / OAuth callback',
    href: '/inbox/callback',
    icon: '@',
    keywords: ['inbox', 'callback', 'oauth'],
  },
  {
    id: 'page-shared-inbox',
    type: 'pages',
    title: 'Shared Inbox',
    subtitle: 'Tools / Team inbox',
    href: '/shared-inbox',
    icon: '\u2709',
    keywords: ['shared', 'inbox', 'team'],
  },
  {
    id: 'page-documents',
    type: 'pages',
    title: 'Documents',
    subtitle: 'Tools / Document management',
    href: '/documents',
    icon: ']',
    keywords: ['documents', 'files', 'upload'],
  },
  {
    id: 'page-workflows',
    type: 'pages',
    title: 'Workflows',
    subtitle: 'Tools / Automation workflows',
    href: '/workflows',
    icon: '>',
    keywords: ['workflows', 'automation'],
  },
  {
    id: 'page-workflows-builder',
    type: 'pages',
    title: 'Workflow Builder',
    subtitle: 'Tools / Visual workflow builder',
    href: '/workflows/builder',
    icon: '>',
    keywords: ['workflow', 'builder', 'visual'],
  },
  {
    id: 'page-workflows-runtime',
    type: 'pages',
    title: 'Workflow Runtime',
    subtitle: 'Tools / Running workflows',
    href: '/workflows/runtime',
    icon: '>',
    keywords: ['workflow', 'runtime', 'running'],
  },
  {
    id: 'page-connectors',
    type: 'pages',
    title: 'Connectors',
    subtitle: 'Tools / Data connectors',
    href: '/connectors',
    icon: '<',
    keywords: ['connectors', 'data', 'integration'],
  },
  {
    id: 'page-templates',
    type: 'pages',
    title: 'Templates',
    subtitle: 'Tools / Debate templates',
    href: '/templates',
    icon: '[',
    keywords: ['templates', 'prebuilt'],
  },
  {
    id: 'page-autonomous',
    type: 'pages',
    title: 'Autonomous',
    subtitle: 'Tools / Autonomous agents',
    href: '/autonomous',
    icon: '!',
    keywords: ['autonomous', 'auto', 'agent'],
  },
  {
    id: 'page-mcp',
    type: 'pages',
    title: 'MCP Tools',
    subtitle: 'Tools / Model Context Protocol',
    href: '/mcp',
    icon: '~',
    keywords: ['mcp', 'tools', 'protocol'],
  },
  {
    id: 'page-webhooks',
    type: 'pages',
    title: 'Webhooks',
    subtitle: 'Tools / Webhook management',
    href: '/webhooks',
    icon: '\u21C4',
    keywords: ['webhooks', 'hooks', 'events'],
  },
  {
    id: 'page-plugins',
    type: 'pages',
    title: 'Plugins',
    subtitle: 'Tools / Plugin marketplace',
    href: '/plugins',
    icon: '\u2699',
    keywords: ['plugins', 'extensions'],
  },
  {
    id: 'page-api-explorer',
    type: 'pages',
    title: 'API Explorer',
    subtitle: 'Tools / Interactive API explorer',
    href: '/api-explorer',
    icon: '{',
    keywords: ['api', 'explorer', 'rest', 'swagger'],
  },
  {
    id: 'page-broadcast',
    type: 'pages',
    title: 'Broadcast',
    subtitle: 'Tools / Broadcast messages',
    href: '/broadcast',
    icon: '\u25CE',
    keywords: ['broadcast', 'announce'],
  },
  {
    id: 'page-command-center',
    type: 'pages',
    title: 'Command Center',
    subtitle: 'Tools / Unified command center',
    href: '/command-center',
    icon: '\u2318',
    keywords: ['command', 'center', 'control'],
  },

  // -- Memory & Knowledge --
  {
    id: 'page-memory',
    type: 'pages',
    title: 'Memory',
    subtitle: 'Memory / Memory explorer',
    href: '/memory',
    icon: '=',
    keywords: ['memory', 'explore', 'continuum'],
  },
  {
    id: 'page-memory-analytics',
    type: 'pages',
    title: 'Memory Analytics',
    subtitle: 'Memory / Memory metrics',
    href: '/memory-analytics',
    icon: '\u2261',
    keywords: ['memory', 'analytics', 'metrics'],
  },
  {
    id: 'page-evidence',
    type: 'pages',
    title: 'Evidence',
    subtitle: 'Memory / Evidence chain',
    href: '/evidence',
    icon: '\u2690',
    keywords: ['evidence', 'proof', 'chain'],
  },
  {
    id: 'page-repository',
    type: 'pages',
    title: 'Repository',
    subtitle: 'Memory / Knowledge repository',
    href: '/repository',
    icon: '\u25A3',
    keywords: ['repository', 'storage'],
  },
  {
    id: 'page-rlm',
    type: 'pages',
    title: 'RLM',
    subtitle: 'Memory / Recursive Language Models',
    href: '/rlm',
    icon: '\u21BA',
    keywords: ['rlm', 'recursive', 'language'],
  },

  // -- Development --
  {
    id: 'page-codebase-audit',
    type: 'pages',
    title: 'Codebase Audit',
    subtitle: 'Development / Codebase auditor',
    href: '/codebase-audit',
    icon: '\u2611',
    keywords: ['codebase', 'audit', 'scan'],
  },
  {
    id: 'page-security-scan',
    type: 'pages',
    title: 'Security Scan',
    subtitle: 'Development / Security scanner',
    href: '/security-scan',
    icon: '\u26BF',
    keywords: ['security', 'scan', 'vulnerability'],
  },
  {
    id: 'page-developer',
    type: 'pages',
    title: 'Developer',
    subtitle: 'Development / Developer tools',
    href: '/developer',
    icon: '>_',
    keywords: ['developer', 'tools', 'dev'],
  },
  {
    id: 'page-sandbox',
    type: 'pages',
    title: 'Sandbox',
    subtitle: 'Development / Safe code execution',
    href: '/sandbox',
    icon: '\u25A1',
    keywords: ['sandbox', 'code', 'execute'],
  },
  {
    id: 'page-reviews',
    type: 'pages',
    title: 'Code Reviews',
    subtitle: 'Development / Security reviews',
    href: '/reviews',
    icon: '<',
    keywords: ['reviews', 'code', 'security'],
  },

  // -- AI & ML --
  {
    id: 'page-training',
    type: 'pages',
    title: 'Training',
    subtitle: 'AI & ML / Training management',
    href: '/training',
    icon: '\u2699',
    keywords: ['training', 'model', 'fine-tune'],
  },
  {
    id: 'page-training-explorer',
    type: 'pages',
    title: 'Training Explorer',
    subtitle: 'AI & ML / Explore training data',
    href: '/training/explorer',
    icon: '\u2699',
    keywords: ['training', 'explorer', 'data'],
  },
  {
    id: 'page-training-models',
    type: 'pages',
    title: 'Training Models',
    subtitle: 'AI & ML / Manage models',
    href: '/training/models',
    icon: '\u2699',
    keywords: ['training', 'models', 'manage'],
  },
  {
    id: 'page-ml',
    type: 'pages',
    title: 'ML',
    subtitle: 'AI & ML / Machine learning dashboard',
    href: '/ml',
    icon: '\u2206',
    keywords: ['ml', 'machine', 'learning'],
  },
  {
    id: 'page-selection',
    type: 'pages',
    title: 'Selection',
    subtitle: 'AI & ML / Agent selection',
    href: '/selection',
    icon: '\u21D2',
    keywords: ['selection', 'agent', 'choose'],
  },
  {
    id: 'page-evolution',
    type: 'pages',
    title: 'Evolution',
    subtitle: 'AI & ML / Agent evolution',
    href: '/evolution',
    icon: '\u267E',
    keywords: ['evolution', 'improve', 'adapt'],
  },
  {
    id: 'page-ab-testing',
    type: 'pages',
    title: 'AB Testing',
    subtitle: 'AI & ML / Experiment tracking',
    href: '/ab-testing',
    icon: 'A|B',
    keywords: ['ab', 'testing', 'experiment'],
  },

  // -- Voice & Media --
  {
    id: 'page-voice',
    type: 'pages',
    title: 'Voice',
    subtitle: 'Voice & Media / Voice input',
    href: '/voice',
    icon: '\u266A',
    keywords: ['voice', 'speech', 'audio'],
  },
  {
    id: 'page-speech',
    type: 'pages',
    title: 'Speech',
    subtitle: 'Voice & Media / Text-to-speech',
    href: '/speech',
    icon: '\u25B6',
    keywords: ['speech', 'tts', 'synthesis'],
  },
  {
    id: 'page-transcribe',
    type: 'pages',
    title: 'Transcribe',
    subtitle: 'Voice & Media / Audio transcription',
    href: '/transcribe',
    icon: '\u270E',
    keywords: ['transcribe', 'audio', 'text'],
  },

  // -- Business --
  {
    id: 'page-accounting',
    type: 'pages',
    title: 'Accounting',
    subtitle: 'Business / Accounting dashboard',
    href: '/accounting',
    icon: '\u2211',
    keywords: ['accounting', 'finance', 'books'],
  },
  {
    id: 'page-accounting-plaid',
    type: 'pages',
    title: 'Plaid Integration',
    subtitle: 'Business / Plaid connection',
    href: '/accounting/plaid',
    icon: '\u2211',
    keywords: ['plaid', 'bank', 'accounting'],
  },
  {
    id: 'page-pricing',
    type: 'pages',
    title: 'Pricing',
    subtitle: 'Business / Pricing plans',
    href: '/pricing',
    icon: '\u00A4',
    keywords: ['pricing', 'plans', 'subscription'],
  },
  {
    id: 'page-verticals',
    type: 'pages',
    title: 'Verticals',
    subtitle: 'Business / Industry verticals',
    href: '/verticals',
    icon: '/',
    keywords: ['verticals', 'industry', 'healthcare', 'finance', 'legal'],
  },
  {
    id: 'page-billing',
    type: 'pages',
    title: 'Billing',
    subtitle: 'Business / Billing management',
    href: '/billing',
    icon: '$',
    keywords: ['billing', 'payment', 'invoice'],
  },
  {
    id: 'page-billing-success',
    type: 'pages',
    title: 'Billing Success',
    subtitle: 'Business / Payment confirmed',
    href: '/billing/success',
    icon: '$',
    keywords: ['billing', 'success', 'payment'],
  },

  // -- Orchestration --
  {
    id: 'page-scheduler',
    type: 'pages',
    title: 'Scheduler',
    subtitle: 'Orchestration / Task scheduler',
    href: '/scheduler',
    icon: '\u25F7',
    keywords: ['scheduler', 'schedule', 'cron'],
  },
  {
    id: 'page-queue',
    type: 'pages',
    title: 'Queue',
    subtitle: 'Orchestration / Job queue',
    href: '/queue',
    icon: '\u2630',
    keywords: ['queue', 'jobs', 'tasks'],
  },
  {
    id: 'page-nomic-control',
    type: 'pages',
    title: 'Nomic Control',
    subtitle: 'Orchestration / Self-improvement',
    href: '/nomic-control',
    icon: '\u221E',
    keywords: ['nomic', 'self-improve', 'loop'],
  },
  {
    id: 'page-verification',
    type: 'pages',
    title: 'Verification',
    subtitle: 'Orchestration / Formal verification',
    href: '/verification',
    icon: '\u2713',
    keywords: ['verification', 'formal', 'proof'],
  },
  {
    id: 'page-verify',
    type: 'pages',
    title: 'Verify',
    subtitle: 'Orchestration / Verify results',
    href: '/verify',
    icon: '\u2714',
    keywords: ['verify', 'check', 'validate'],
  },
  {
    id: 'page-self-improve',
    type: 'pages',
    title: 'Self Improve',
    subtitle: 'Orchestration / Autonomous improvement',
    href: '/self-improve',
    icon: '\u221E',
    keywords: ['self', 'improve', 'autonomous'],
  },

  // -- Advanced --
  {
    id: 'page-genesis',
    type: 'pages',
    title: 'Genesis',
    subtitle: 'Advanced / Fractal resolution',
    href: '/genesis',
    icon: '@',
    keywords: ['genesis', 'fractal', 'resolution'],
  },
  {
    id: 'page-introspection',
    type: 'pages',
    title: 'Introspection',
    subtitle: 'Advanced / Agent self-awareness',
    href: '/introspection',
    icon: '?',
    keywords: ['introspection', 'self-awareness', 'meta'],
  },
  {
    id: 'page-network',
    type: 'pages',
    title: 'Agent Network',
    subtitle: 'Advanced / Agent network graph',
    href: '/network',
    icon: '~',
    keywords: ['network', 'graph', 'agent'],
  },
  {
    id: 'page-probe',
    type: 'pages',
    title: 'Capability Probe',
    subtitle: 'Advanced / Agent capability testing',
    href: '/probe',
    icon: '^',
    keywords: ['probe', 'capability', 'test'],
  },
  {
    id: 'page-red-team',
    type: 'pages',
    title: 'Red Team',
    subtitle: 'Advanced / Adversarial testing',
    href: '/red-team',
    icon: '!',
    keywords: ['red', 'team', 'adversarial'],
  },
  {
    id: 'page-modes',
    type: 'pages',
    title: 'Op Modes',
    subtitle: 'Advanced / Operational modes',
    href: '/modes',
    icon: '#',
    keywords: ['modes', 'operational', 'role'],
  },
  {
    id: 'page-laboratory',
    type: 'pages',
    title: 'Laboratory',
    subtitle: 'Advanced / Experimental features',
    href: '/laboratory',
    icon: '\u2697',
    keywords: ['laboratory', 'experiment'],
  },
  {
    id: 'page-breakpoints',
    type: 'pages',
    title: 'Breakpoints',
    subtitle: 'Advanced / Debate breakpoints',
    href: '/breakpoints',
    icon: '\u25CF',
    keywords: ['breakpoints', 'debug', 'pause'],
  },
  {
    id: 'page-checkpoints',
    type: 'pages',
    title: 'Checkpoints',
    subtitle: 'Advanced / Save points',
    href: '/checkpoints',
    icon: '\u2713',
    keywords: ['checkpoints', 'save', 'snapshot'],
  },
  {
    id: 'page-integrations',
    type: 'pages',
    title: 'Integrations',
    subtitle: 'Advanced / Platform integrations',
    href: '/integrations',
    icon: ':',
    keywords: ['integrations', 'slack', 'teams', 'connect'],
  },
  {
    id: 'page-integrations-chat',
    type: 'pages',
    title: 'Chat Integrations',
    subtitle: 'Advanced / Chat platform integrations',
    href: '/integrations/chat',
    icon: ':',
    keywords: ['chat', 'integrations', 'telegram', 'whatsapp'],
  },

  // -- Account --
  {
    id: 'page-settings',
    type: 'pages',
    title: 'Settings',
    subtitle: 'Account / User settings',
    href: '/settings',
    icon: '*',
    keywords: ['settings', 'config', 'preferences'],
  },
  {
    id: 'page-organization',
    type: 'pages',
    title: 'Organization',
    subtitle: 'Account / Organization settings',
    href: '/organization',
    icon: '@',
    keywords: ['organization', 'org', 'team'],
  },
  {
    id: 'page-organization-members',
    type: 'pages',
    title: 'Organization Members',
    subtitle: 'Account / Manage members',
    href: '/organization/members',
    icon: '@',
    keywords: ['members', 'team', 'invite'],
  },
  {
    id: 'page-demo',
    type: 'pages',
    title: 'Demo',
    subtitle: 'Demo mode',
    href: '/demo',
    icon: '>',
    keywords: ['demo', 'try', 'test'],
  },
  {
    id: 'page-agent',
    type: 'pages',
    title: 'Agent Detail',
    subtitle: 'Agent detail view',
    href: '/agent',
    icon: '&',
    keywords: ['agent', 'detail', 'profile'],
  },

  // -- Admin --
  {
    id: 'page-admin',
    type: 'pages',
    title: 'Admin Dashboard',
    subtitle: 'Admin / Dashboard',
    href: '/admin',
    icon: '!',
    keywords: ['admin', 'dashboard'],
  },
  {
    id: 'page-admin-users',
    type: 'pages',
    title: 'User Management',
    subtitle: 'Admin / Manage users',
    href: '/admin/users',
    icon: '@',
    keywords: ['admin', 'users', 'manage'],
  },
  {
    id: 'page-admin-organizations',
    type: 'pages',
    title: 'Organizations',
    subtitle: 'Admin / Manage organizations',
    href: '/admin/organizations',
    icon: '#',
    keywords: ['admin', 'organizations'],
  },
  {
    id: 'page-admin-tenants',
    type: 'pages',
    title: 'Tenants',
    subtitle: 'Admin / Multi-tenancy',
    href: '/admin/tenants',
    icon: '\u2302',
    keywords: ['admin', 'tenants', 'multi-tenant'],
  },
  {
    id: 'page-admin-revenue',
    type: 'pages',
    title: 'Revenue',
    subtitle: 'Admin / Revenue metrics',
    href: '/admin/revenue',
    icon: '$',
    keywords: ['admin', 'revenue', 'income'],
  },
  {
    id: 'page-admin-roi',
    type: 'pages',
    title: 'ROI Dashboard',
    subtitle: 'Admin / Return on investment',
    href: '/admin/roi-dashboard',
    icon: '\u2197',
    keywords: ['admin', 'roi', 'return'],
  },
  {
    id: 'page-admin-billing',
    type: 'pages',
    title: 'Admin Billing',
    subtitle: 'Admin / Billing management',
    href: '/admin/billing',
    icon: '\u00A4',
    keywords: ['admin', 'billing'],
  },
  {
    id: 'page-admin-usage',
    type: 'pages',
    title: 'Admin Usage',
    subtitle: 'Admin / Usage statistics',
    href: '/admin/usage',
    icon: '%',
    keywords: ['admin', 'usage', 'stats'],
  },
  {
    id: 'page-admin-audit',
    type: 'pages',
    title: 'Admin Audit',
    subtitle: 'Admin / Audit logs',
    href: '/admin/audit',
    icon: '\u2611',
    keywords: ['admin', 'audit', 'logs'],
  },
  {
    id: 'page-admin-security',
    type: 'pages',
    title: 'Admin Security',
    subtitle: 'Admin / Security settings',
    href: '/admin/security',
    icon: '\u26BF',
    keywords: ['admin', 'security'],
  },
  {
    id: 'page-admin-evidence',
    type: 'pages',
    title: 'Admin Evidence',
    subtitle: 'Admin / Evidence management',
    href: '/admin/evidence',
    icon: '\u2690',
    keywords: ['admin', 'evidence'],
  },
  {
    id: 'page-admin-forensic',
    type: 'pages',
    title: 'Forensic',
    subtitle: 'Admin / Forensic analysis',
    href: '/admin/forensic',
    icon: '\u2623',
    keywords: ['admin', 'forensic', 'investigation'],
  },
  {
    id: 'page-admin-knowledge',
    type: 'pages',
    title: 'Admin Knowledge',
    subtitle: 'Admin / Knowledge management',
    href: '/admin/knowledge',
    icon: '?',
    keywords: ['admin', 'knowledge'],
  },
  {
    id: 'page-admin-memory',
    type: 'pages',
    title: 'Admin Memory',
    subtitle: 'Admin / Memory management',
    href: '/admin/memory',
    icon: '=',
    keywords: ['admin', 'memory'],
  },
  {
    id: 'page-admin-nomic',
    type: 'pages',
    title: 'Nomic',
    subtitle: 'Admin / Nomic loop control',
    href: '/admin/nomic',
    icon: '\u221E',
    keywords: ['admin', 'nomic', 'loop'],
  },
  {
    id: 'page-admin-personas',
    type: 'pages',
    title: 'Personas',
    subtitle: 'Admin / Agent personas',
    href: '/admin/personas',
    icon: '&',
    keywords: ['admin', 'personas', 'agent'],
  },
  {
    id: 'page-admin-queue',
    type: 'pages',
    title: 'Admin Queue',
    subtitle: 'Admin / Queue management',
    href: '/admin/queue',
    icon: '\u2630',
    keywords: ['admin', 'queue', 'jobs'],
  },
  {
    id: 'page-admin-streaming',
    type: 'pages',
    title: 'Streaming',
    subtitle: 'Admin / Streaming config',
    href: '/admin/streaming',
    icon: '\u25B6',
    keywords: ['admin', 'streaming', 'kafka'],
  },
  {
    id: 'page-admin-training',
    type: 'pages',
    title: 'Admin Training',
    subtitle: 'Admin / Training management',
    href: '/admin/training',
    icon: '\u2699',
    keywords: ['admin', 'training'],
  },
  {
    id: 'page-admin-verticals',
    type: 'pages',
    title: 'Admin Verticals',
    subtitle: 'Admin / Vertical settings',
    href: '/admin/verticals',
    icon: '/',
    keywords: ['admin', 'verticals'],
  },
  {
    id: 'page-admin-workspace',
    type: 'pages',
    title: 'Workspace',
    subtitle: 'Admin / Workspace management',
    href: '/admin/workspace',
    icon: '\u25A3',
    keywords: ['admin', 'workspace'],
  },
  {
    id: 'page-admin-ab-tests',
    type: 'pages',
    title: 'AB Tests',
    subtitle: 'Admin / AB test management',
    href: '/admin/ab-tests',
    icon: 'A|B',
    keywords: ['admin', 'ab', 'tests'],
  },
];

const DEBOUNCE_MS = 200;

/**
 * Search pages by query with fuzzy matching across title, subtitle, and keywords
 */
function searchPages(query: string): SearchResult[] {
  const lowerQuery = query.toLowerCase();
  const terms = lowerQuery.split(/\s+/).filter(Boolean);

  // Score each page for relevance
  const scored = NAVIGATION_PAGES.map((page) => {
    const titleLower = page.title.toLowerCase();
    const subtitleLower = page.subtitle?.toLowerCase() || '';
    const keywordsLower = page.keywords?.map((k) => k.toLowerCase()) || [];

    let score = 0;

    // Exact title match is best
    if (titleLower === lowerQuery) score += 100;
    // Title starts with query
    else if (titleLower.startsWith(lowerQuery)) score += 50;
    // Title contains query
    else if (titleLower.includes(lowerQuery)) score += 30;

    // Check each search term
    for (const term of terms) {
      if (titleLower.includes(term)) score += 20;
      if (subtitleLower.includes(term)) score += 10;
      if (keywordsLower.some((kw) => kw.includes(term) || term.includes(kw))) score += 15;
    }

    return { page, score };
  });

  return scored
    .filter(({ score }) => score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 12)
    .map(({ page }) => page);
}

/**
 * Filter quick actions by query
 */
function filterQuickActions(query: string): QuickAction[] {
  const lowerQuery = query.toLowerCase();
  return QUICK_ACTIONS.filter(
    (action) =>
      action.label.toLowerCase().includes(lowerQuery) ||
      action.keywords.some((kw) => kw.toLowerCase().includes(lowerQuery)) ||
      action.description?.toLowerCase().includes(lowerQuery),
  ).slice(0, 5);
}

/**
 * Convert QuickAction to SearchResult format
 */
function quickActionToSearchResult(action: QuickAction): SearchResult {
  return {
    id: `action-${action.id}`,
    type: 'actions',
    title: action.label,
    subtitle: action.description,
    href: action.href,
    action: action.action,
    icon: action.icon,
    keywords: action.keywords,
  };
}

interface UseCommandPaletteSearchResult {
  search: (query: string, category: SearchCategory) => Promise<void>;
  results: SearchResult[];
  isSearching: boolean;
  error: string | null;
}

/**
 * useCommandPaletteSearch
 *
 * Hook for aggregating search results from multiple sources:
 * - Pages (client-side)
 * - Quick actions (client-side)
 * - Debates (API)
 * - Agents (API)
 * - Documents (API)
 * - Knowledge (API)
 */
export function useCommandPaletteSearch(): UseCommandPaletteSearchResult {
  const { config } = useBackend();
  const {
    results,
    isSearching,
    searchError,
    setResults,
    setIsSearching,
    setSearchError,
    query,
    activeCategory,
  } = useCommandPaletteStore();

  const abortControllerRef = useRef<AbortController | null>(null);
  const debouncedQuery = useDebounce(query, DEBOUNCE_MS);

  /**
   * Search debates via API
   */
  const searchDebates = useCallback(
    async (q: string, signal: AbortSignal): Promise<SearchResult[]> => {
      try {
        const response = await fetch(
          `${config.api}/api/debates?limit=5&q=${encodeURIComponent(q)}`,
          { signal },
        );
        if (!response.ok) return [];
        const data = await response.json();
        return (data.debates || []).map(
          (d: { id: string; task?: string; question?: string; consensus?: string }) => ({
            id: `debate-${d.id}`,
            type: 'debates' as SearchCategory,
            title: d.task || d.question || d.id,
            subtitle: d.consensus ? `Consensus: ${d.consensus}` : undefined,
            href: `/debates/${d.id}`,
            icon: '!',
          }),
        );
      } catch {
        return [];
      }
    },
    [config.api],
  );

  /**
   * Search agents via API
   */
  const searchAgents = useCallback(
    async (q: string, signal: AbortSignal): Promise<SearchResult[]> => {
      try {
        const response = await fetch(`${config.api}/api/agents/configs?limit=5`, { signal });
        if (!response.ok) return [];
        const data = await response.json();
        const agents = data.configs || data.agents || [];
        const lowerQ = q.toLowerCase();
        return agents
          .filter(
            (a: { name?: string; display_name?: string }) =>
              a.name?.toLowerCase().includes(lowerQ) ||
              a.display_name?.toLowerCase().includes(lowerQ),
          )
          .slice(0, 5)
          .map((a: { name: string; display_name?: string; model?: string }) => ({
            id: `agent-${a.name}`,
            type: 'agents' as SearchCategory,
            title: a.display_name || a.name,
            subtitle: a.model || 'AI Agent',
            href: `/agents?agent=${a.name}`,
            icon: '&',
          }));
      } catch {
        return [];
      }
    },
    [config.api],
  );

  /**
   * Search documents via API
   */
  const searchDocuments = useCallback(
    async (q: string, signal: AbortSignal): Promise<SearchResult[]> => {
      try {
        const response = await fetch(
          `${config.api}/api/documents?limit=5&q=${encodeURIComponent(q)}`,
          { signal },
        );
        if (!response.ok) return [];
        const data = await response.json();
        return (data.documents || []).map(
          (d: { id: string; filename?: string; name?: string; type?: string }) => ({
            id: `doc-${d.id}`,
            type: 'documents' as SearchCategory,
            title: d.filename || d.name || d.id,
            subtitle: d.type || 'Document',
            href: `/documents?id=${d.id}`,
            icon: ']',
          }),
        );
      } catch {
        return [];
      }
    },
    [config.api],
  );

  /**
   * Search knowledge via API
   */
  const searchKnowledge = useCallback(
    async (q: string, signal: AbortSignal): Promise<SearchResult[]> => {
      try {
        const response = await fetch(`${config.api}/api/knowledge/mound/query`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: q, limit: 5 }),
          signal,
        });
        if (!response.ok) return [];
        const data = await response.json();
        return (data.nodes || []).map((n: { id: string; content?: string; type?: string }) => ({
          id: `knowledge-${n.id}`,
          type: 'knowledge' as SearchCategory,
          title: n.content?.slice(0, 60) || n.id,
          subtitle: n.type || 'Knowledge',
          href: `/knowledge?node=${n.id}`,
          icon: '?',
        }));
      } catch {
        return [];
      }
    },
    [config.api],
  );

  /**
   * Aggregate search across all sources
   */
  const search = useCallback(
    async (q: string, category: SearchCategory) => {
      // Cancel any pending request
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }

      const trimmedQuery = q.trim();

      // If no query, show quick actions only
      if (!trimmedQuery) {
        const actions = QUICK_ACTIONS.slice(0, 6).map(quickActionToSearchResult);
        setResults(actions);
        setIsSearching(false);
        setSearchError(null);
        return;
      }

      setIsSearching(true);
      setSearchError(null);

      const controller = new AbortController();
      abortControllerRef.current = controller;

      try {
        const allResults: SearchResult[] = [];

        // Always search pages and actions (client-side, fast)
        if (category === 'all' || category === 'pages') {
          allResults.push(...searchPages(trimmedQuery));
        }
        if (category === 'all' || category === 'actions') {
          allResults.push(...filterQuickActions(trimmedQuery).map(quickActionToSearchResult));
        }

        // API searches in parallel
        const apiSearches: Promise<SearchResult[]>[] = [];

        if (category === 'all' || category === 'debates') {
          apiSearches.push(searchDebates(trimmedQuery, controller.signal));
        }
        if (category === 'all' || category === 'agents') {
          apiSearches.push(searchAgents(trimmedQuery, controller.signal));
        }
        if (category === 'all' || category === 'documents') {
          apiSearches.push(searchDocuments(trimmedQuery, controller.signal));
        }
        if (category === 'all' || category === 'knowledge') {
          apiSearches.push(searchKnowledge(trimmedQuery, controller.signal));
        }

        // Wait for all API searches
        const apiResults = await Promise.allSettled(apiSearches);

        // Collect successful results
        for (const result of apiResults) {
          if (result.status === 'fulfilled') {
            allResults.push(...result.value);
          }
        }

        // Sort by relevance (exact matches first)
        const lowerQuery = trimmedQuery.toLowerCase();
        allResults.sort((a, b) => {
          const aExact = a.title.toLowerCase() === lowerQuery ? 1 : 0;
          const bExact = b.title.toLowerCase() === lowerQuery ? 1 : 0;
          return bExact - aExact;
        });

        setResults(allResults.slice(0, 20));
      } catch (err) {
        if (err instanceof Error && err.name === 'AbortError') {
          // Request was cancelled, ignore
          return;
        }
        setSearchError('Search failed. Please try again.');
      } finally {
        setIsSearching(false);
      }
    },
    [
      searchDebates,
      searchAgents,
      searchDocuments,
      searchKnowledge,
      setResults,
      setIsSearching,
      setSearchError,
    ],
  );

  // Trigger search when debounced query changes
  useEffect(() => {
    search(debouncedQuery, activeCategory);
  }, [debouncedQuery, activeCategory, search]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  return { search, results, isSearching, error: searchError };
}

export default useCommandPaletteSearch;
