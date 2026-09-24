'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { DEFAULT_AGENTS, DEFAULT_ROUNDS } from '@/config';
import { VerticalSelector } from './VerticalSelector';
import { useAuth } from '@/context/AuthContext';
import { logger } from '@/utils/logger';

interface DebateInputProps {
  apiBase: string;
  onDebateStarted?: (debateId: string, question: string) => void;
  onError?: (error: string) => void;
  onQuestionChange?: (question: string) => void;
  defaultFormat?: 'light' | 'full';
  defaultQuestion?: string;
  defaultAgents?: string;
  defaultRounds?: number;
  defaultBudgetLimit?: string;
  initialShowAdvanced?: boolean;
  allowPlaygroundFallback?: boolean;
  templateId?: string;
}

type DebateMode = 'standard' | 'graph' | 'matrix';
type DebateFormat = 'light' | 'full';

const DEBATE_MODES: Record<DebateMode, { label: string; description: string; endpoint: string }> = {
  standard: {
    label: 'Standard',
    description: 'Linear debate with critique rounds',
    endpoint: '/api/v1/debates',
  },
  graph: {
    label: 'Graph',
    description: 'Branching debate exploring multiple paths',
    endpoint: '/api/v1/debates/graph',
  },
  matrix: {
    label: 'Matrix',
    description: 'Parallel scenarios for comparison',
    endpoint: '/api/v1/debates/matrix',
  },
};

const DEBATE_FORMATS: Record<
  DebateFormat,
  { label: string; description: string; time: string; icon: string }
> = {
  light: {
    label: 'Quick',
    description: '4 rounds, focused analysis',
    time: '~5 min',
    icon: '\u26A1', // Lightning bolt
  },
  full: {
    label: 'Thorough',
    description: '9 rounds, deep exploration',
    time: '~15-30 min',
    icon: '\uD83E\uDDE0', // Brain emoji
  },
};

interface AgentRecommendation {
  agent: string;
  suitability: number;
  domain_match: boolean;
}

type ApiStatus = 'checking' | 'online' | 'offline';

// Simple domain detection from question text
function detectDomain(text: string): string {
  const lower = text.toLowerCase();
  if (
    /\b(code|programming|api|software|bug|function|class|typescript|javascript|python)\b/.test(
      lower,
    )
  ) {
    return 'technical';
  }
  if (/\b(security|auth|encryption|vulnerability|attack|password|token)\b/.test(lower)) {
    return 'security';
  }
  if (/\b(ethics|moral|right|wrong|should|fair|justice|harm)\b/.test(lower)) {
    return 'ethics';
  }
  if (/\b(ai|machine learning|model|neural|llm|gpt|claude|reasoning)\b/.test(lower)) {
    return 'ai';
  }
  if (/\b(architecture|design|pattern|microservice|monolith|scale|database)\b/.test(lower)) {
    return 'architecture';
  }
  return 'general';
}

export function DebateInput({
  apiBase,
  onDebateStarted,
  onError,
  onQuestionChange,
  defaultFormat,
  defaultQuestion,
  defaultAgents,
  defaultRounds,
  defaultBudgetLimit,
  initialShowAdvanced,
  allowPlaygroundFallback = true,
  templateId: _templateId,
}: DebateInputProps) {
  const router = useRouter();
  const { tokens, isLoading: authLoading, isAuthenticated } = useAuth();
  const [question, setQuestion] = useState(defaultQuestion ?? '');

  // Sync if defaultQuestion changes (e.g., template loaded async)
  useEffect(() => {
    if (defaultQuestion && !question) {
      setQuestion(defaultQuestion);
    }
  }, [defaultQuestion]); // eslint-disable-line react-hooks/exhaustive-deps

  // Notify parent of question changes
  useEffect(() => {
    onQuestionChange?.(question);
  }, [question]); // eslint-disable-line react-hooks/exhaustive-deps
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(initialShowAdvanced ?? false);
  const [agents, setAgents] = useState(defaultAgents ?? DEFAULT_AGENTS);
  const [rounds, setRounds] = useState(defaultRounds ?? DEFAULT_ROUNDS);
  const [debateMode, setDebateMode] = useState<DebateMode>('standard');
  const [debateFormat, setDebateFormat] = useState<DebateFormat>(defaultFormat || 'full');
  const [apiStatus, setApiStatus] = useState<ApiStatus>('checking');
  const [recommendations, setRecommendations] = useState<AgentRecommendation[]>([]);
  const [detectedDomain, setDetectedDomain] = useState<string>('general');
  const [selectedVertical, setSelectedVertical] = useState<string>('general');
  const [budgetLimit, setBudgetLimit] = useState<string>(defaultBudgetLimit ?? '');
  const [localError, setLocalError] = useState<string | null>(null);
  const [costEstimate, setCostEstimate] = useState<{
    total: number;
    breakdown: { model: string; subtotal: number }[];
  } | null>(null);
  const [costLoading, setCostLoading] = useState(false);
  const [costError, setCostError] = useState(false);
  const debounceRef = useRef<NodeJS.Timeout | null>(null);
  const costDebounceRef = useRef<NodeJS.Timeout | null>(null);
  const hasLiveAccess = isAuthenticated && Boolean(tokens?.access_token);
  const requiresLiveAuth = !allowPlaygroundFallback && !authLoading && !hasLiveAccess;

  // Combined question pool: AI philosophy + Multi-agent debate + Technical architecture
  const allQuestions = [
    // AI Philosophy & Ethics
    'Can AI systems develop genuine understanding, or only simulate it?',
    'Should autonomous AI agents have the right to refuse unethical requests?',
    'Is Hegelian dialectics the optimal framework for AI reasoning?',
    'Will AI agents eventually form their own societies and cultures?',
    'Is truth something AI can discover, or only approximate?',
    'Should AI systems prioritize uncomfortable truths over what humans want to hear?',
    'Should AI development be paused to solve risks, or accelerated for benefits?',
    'Should AI systems be granted legal personhood with rights and responsibilities?',
    'Should humanity cede political power to a benevolent AI superintelligence?',

    // Society & Policy
    'How will AI impact job displacement and what policies should governments implement?',
    'Should governments implement universal basic income to mitigate AI job impacts?',
    'If eliminating climate change required giving up the internet, should we make that trade?',
    'In 2034, should voting be mandatory with AI-assisted candidate matching?',
    'What widely-used technology will future generations condemn us for, the way we now view asbestos or leaded gasoline?',
    'If you could instantly eradicate one widely accepted social norm with no backlash, what would it be and why?',

    // Provocative Hypotheticals
    'If you had to live-stream your entire digital life to everyone you know for 30 days, what would you pay to avoid it?',
    'If every person who ever lived could vote on whether humanity should voluntarily end tomorrow, would extinction win?',
    'If a Transparency Patch made every thought about others audible, which institution would collapse first: Marriage, Politics, Law, or Religion?',
    'What skill or knowledge that you are proud of will be completely obsolete within your lifetime?',
    'If aliens visited Earth and could only observe one person for 24 hours to understand humanity, who would you choose?',
    'What is the most ethically justifiable form of cheating, and where would you draw the line?',
    'If you could eliminate one universally accepted moral value from humanity to test its impact, which would you choose?',
    'You have a one-time time machine: prevent infant Hitler from becoming a dictator, but lose civil-rights movements, the EU, and modern computing. Press the button?',

    // Civilization & Future
    "Should humanity colonize Mars, or focus those resources on solving Earth's problems first?",
    'Should human lifespan be artificially extended, and if so, who decides who gets access?',
    'Are we fundamentally changing human nature with technology, or merely amplifying existing traits?',
    'If we could run a historical Diff Check measuring Net Suffering vs. Net Joy for famous figures, whose score would shock us most?',
    "If we could access the Universe's Error Logs for failed civilizations, what Critical Warning would Earth be flagging?",
    'Should legal personhood scale with measured consciousness probability? A 70%-sapient AI pays 70% tax; a 30%-conscious pig gets 30% protection?',

    // Multi-Agent Debate
    'Is consensus among AI agents more reliable than a single powerful model?',
    'Can adversarial debate eliminate AI hallucinations?',
    'Can competing AI perspectives reach genuine synthesis?',
    'What makes a good debate question for AI agents?',
    'How would you redesign democracy using multi-agent systems?',
    'When should a multi-agent system override human judgment?',
    'Should AI critics be more aggressive or more diplomatic?',

    // Technical Architecture
    'What are the tradeoffs between microservices and monoliths?',
    'How should we implement rate limiting for 1M requests/sec?',
    'Is GraphQL or REST better for real-time collaborative APIs?',
    'What authentication strategy balances security with UX?',
    'Should we use TypeScript or JavaScript for this project?',

    // Business Strategy
    'When should a startup prioritize market share over profitability?',
    'What factors should drive a build vs. buy decision for core infrastructure?',
    'How should a B2B company approach pricing for a new product category?',
    'When is the right time for a startup to expand internationally?',
    'Should we pursue a platform strategy or stay focused on our core product?',
    'What are the trade-offs between vertical and horizontal market expansion?',
    'How should we evaluate potential acquisition targets vs. organic growth?',
    'When should a company pivot its business model vs. double down?',
    'What metrics should drive enterprise sales team compensation?',
    'How do you balance customer customization requests with product roadmap?',
    'Should we open-source our core technology to accelerate adoption?',
    'What is the optimal balance between self-serve and sales-led growth?',

    // Enterprise & Compliance
    'How should we approach SOC 2 certification for a fast-moving startup?',
    'What is the best strategy for GDPR compliance in a multi-tenant SaaS?',
    'How do we balance security controls with developer productivity?',
    'What vendor evaluation criteria matter most for enterprise software?',
    'How should we structure our compliance program to satisfy multiple frameworks?',
    'When should a company hire a dedicated security team vs. outsource?',
    'What is the ROI calculation for investing in compliance automation?',
    'How do we prepare for enterprise customer security questionnaires at scale?',
    'Should we pursue FedRAMP certification for government sales?',
    'How do we implement least-privilege access without slowing down engineering?',

    // Financial Services & FinTech
    'What are the trade-offs between real-time and batch processing for payments?',
    'How should we approach AML/KYC compliance for a new fintech product?',
    'What is the optimal architecture for a high-frequency trading system?',
    'How do we balance fraud prevention with customer experience?',
    'Should we build our own payment rails or use existing infrastructure?',
    'What is the best approach to regulatory reporting automation?',
    'How should we handle PCI-DSS compliance in a cloud-native architecture?',
    'What are the trade-offs between centralized and decentralized finance?',

    // Healthcare
    'How should we approach HIPAA compliance for a healthcare AI product?',
    'What are the trade-offs between HL7 FHIR and legacy healthcare APIs?',
    'How do we balance clinical decision support accuracy with explainability?',
    'What is the best approach to patient data governance in a multi-provider system?',
    'Should healthcare AI systems require human oversight for all decisions?',
    'How do we handle clinical trial data in compliance with FDA 21 CFR Part 11?',

    // Legal & Contracts
    'Should legal teams adopt AI for contract review, and what are the risks?',
    'How do we approach IP protection for AI-generated innovations?',
    'What is the optimal approach to compliance monitoring across jurisdictions?',
    'How should companies prepare for AI regulation like the EU AI Act?',
    'What are the trade-offs between in-house counsel and outside firms?',
    'How do we automate legal operations without sacrificing quality?',

    // SaaS & Platform
    'What is the best multi-tenancy architecture for enterprise SaaS?',
    'How should we approach usage-based pricing for an API product?',
    'What are the trade-offs between API-first and UI-first product development?',
    'How do we balance platform openness with quality control?',
    'What is the optimal approach to customer success for enterprise accounts?',
    'How should we handle data residency requirements for global customers?',
    'When should a SaaS company add professional services?',
    'What is the best approach to managing technical debt while scaling?',
  ];

  // Select random placeholder on mount (stable across re-renders)
  const [placeholder] = useState(
    () => allQuestions[Math.floor(Math.random() * allQuestions.length)],
  );

  // Check API health on mount
  useEffect(() => {
    const checkHealth = async () => {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 5000);

        const response = await fetch(`${apiBase}/api/health`, { signal: controller.signal });
        clearTimeout(timeoutId);

        setApiStatus(response.ok ? 'online' : 'offline');
      } catch {
        setApiStatus('offline');
      }
    };

    checkHealth();
    // Re-check every 30 seconds
    const interval = setInterval(checkHealth, 30000);
    return () => clearInterval(interval);
  }, [apiBase]);

  // Detect domain and fetch routing recommendations when question changes
  useEffect(() => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }

    if (!question.trim() || apiStatus !== 'online') {
      setRecommendations([]);
      setDetectedDomain('general');
      return;
    }

    debounceRef.current = setTimeout(async () => {
      const domain = detectDomain(question);
      setDetectedDomain(domain);

      // Only fetch recommendations for non-general domains
      if (domain !== 'general') {
        try {
          const recHeaders: Record<string, string> = { 'Content-Type': 'application/json' };
          if (tokens?.access_token) recHeaders['Authorization'] = `Bearer ${tokens.access_token}`;
          const response = await fetch(`${apiBase}/api/routing/recommendations`, {
            method: 'POST',
            headers: recHeaders,
            body: JSON.stringify({ primary_domain: domain, limit: 4 }),
          });
          if (response.ok) {
            const data = await response.json();
            setRecommendations(data.recommendations || []);
          }
        } catch {
          // Silently fail - recommendations are optional
        }
      }
    }, 500); // Debounce 500ms

    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    };
  }, [question, apiBase, apiStatus, tokens?.access_token]);

  // Fetch cost estimate when agents/rounds change
  useEffect(() => {
    if (costDebounceRef.current) clearTimeout(costDebounceRef.current);
    if (apiStatus !== 'online') {
      setCostEstimate(null);
      return;
    }

    const agentList = agents
      .split(',')
      .map((a) => a.trim())
      .filter(Boolean);
    if (agentList.length === 0) {
      setCostEstimate(null);
      return;
    }

    costDebounceRef.current = setTimeout(async () => {
      setCostLoading(true);
      setCostError(false);
      try {
        const params = new URLSearchParams({
          num_agents: String(agentList.length),
          num_rounds: String(rounds),
          model_types: agentList.join(','),
        });
        const costHeaders: Record<string, string> = {};
        if (tokens?.access_token) costHeaders['Authorization'] = `Bearer ${tokens.access_token}`;
        const res = await fetch(`${apiBase}/api/v1/debates/estimate-cost?${params}`, {
          headers: costHeaders,
        });
        if (res.ok) {
          const data = await res.json();
          setCostEstimate({
            total: data.total_estimated_cost_usd ?? 0,
            breakdown: (data.breakdown_by_model ?? []).map(
              (b: { model?: string; subtotal_usd?: number }) => ({
                model: b.model ?? 'unknown',
                subtotal: b.subtotal_usd ?? 0,
              }),
            ),
          });
        } else {
          setCostError(true);
        }
      } catch {
        setCostError(true);
      } finally {
        setCostLoading(false);
      }
    }, 600);

    return () => {
      if (costDebounceRef.current) clearTimeout(costDebounceRef.current);
    };
  }, [agents, rounds, apiBase, apiStatus, tokens?.access_token]);

  // Apply recommended agents
  const applyRecommendations = useCallback(() => {
    if (recommendations.length > 0) {
      const recAgents = recommendations.map((r) => r.agent).join(',');
      setAgents(recAgents);
    }
  }, [recommendations]);

  const preflightAgents = useCallback(
    async (_agentList: string[]) => {
      try {
        const availHeaders: Record<string, string> = {};
        if (tokens?.access_token) availHeaders['Authorization'] = `Bearer ${tokens.access_token}`;
        const response = await fetch(`${apiBase}/api/introspection/agents/availability`, {
          headers: availHeaders,
        });
        if (!response.ok) {
          logger.warn('[DebateInput] Agent availability check failed', response.status);
          return null;
        }
        const data = await response.json();
        return data as { available?: string[]; missing?: string[] };
      } catch (err) {
        logger.warn('[DebateInput] Agent availability check error', err);
        return null;
      }
    },
    [apiBase, tokens?.access_token],
  );

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();

      // Use placeholder as fallback when input is empty
      const trimmedQuestion = question.trim() || placeholder;
      if (!trimmedQuestion || isSubmitting) return;

      // Check auth state before submitting
      if (authLoading) {
        logger.debug('[DebateInput] Auth still loading, waiting...');
        onError?.('Please wait, authentication is loading...');
        return;
      }

      // In demo/playground mode, skip auth and use playground endpoint
      if (requiresLiveAuth) {
        const message = 'Sign in to start a live debate from this page.';
        setLocalError(message);
        onError?.(message);
        return;
      }

      const usePlayground = allowPlaygroundFallback && !hasLiveAccess;

      setIsSubmitting(true);
      setLocalError(null);

      // Create AbortController for request timeout (30 seconds)
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 30000);

      try {
        const modeConfig = DEBATE_MODES[debateMode];
        const requestedAgents = agents
          .split(',')
          .map((a) => a.trim())
          .filter(Boolean);

        // In playground mode, skip agent preflight (mock agents always available)
        if (!usePlayground && requestedAgents.length > 0) {
          const availability = await preflightAgents(requestedAgents);
          if (availability?.available?.length) {
            const missingAgents = requestedAgents.filter(
              (agent) => !availability.available?.includes(agent),
            );
            if (missingAgents.length > 0) {
              const message = `Missing credentials for: ${missingAgents.join(', ')}`;
              setLocalError(message);
              onError?.(message);
              setIsSubmitting(false);
              return;
            }
          }
        }

        const headers: Record<string, string> = { 'Content-Type': 'application/json' };
        if (!usePlayground && tokens?.access_token) {
          headers['Authorization'] = `Bearer ${tokens.access_token}`;
        }

        // Use playground endpoint for unauthenticated users (demo mode / no API keys)
        const endpoint = usePlayground ? '/api/v1/playground/debate' : modeConfig.endpoint;

        // Debug: Log request details
        const requestUrl = `${apiBase}${endpoint}`;
        logger.debug('[DebateInput] Starting debate request:', {
          endpoint: requestUrl,
          hasAuth: !!tokens?.access_token,
          mode: usePlayground ? 'playground' : debateMode,
          questionPreview:
            trimmedQuestion.substring(0, 50) + (trimmedQuestion.length > 50 ? '...' : ''),
        });

        // Playground endpoint uses "topic" + "agents" (count); standard uses "question" + "agents" (list)
        const requestBody = usePlayground
          ? { topic: trimmedQuestion, rounds, agents: requestedAgents.length || 3 }
          : {
              question: trimmedQuestion,
              rounds,
              debate_format: debateFormat,
              auto_select: requestedAgents.length === 0,
              ...(requestedAgents.length > 0 && { agents: requestedAgents }),
              vertical: selectedVertical !== 'general' ? selectedVertical : undefined,
              ...(debateMode === 'graph' && { branch_on_disagreement: true }),
              ...(debateMode === 'matrix' && { scenarios: 3 }),
              ...(budgetLimit &&
                parseFloat(budgetLimit) > 0 && { budget_limit_usd: parseFloat(budgetLimit) }),
            };

        const response = await fetch(requestUrl, {
          method: 'POST',
          headers,
          signal: controller.signal,
          body: JSON.stringify(requestBody),
        });

        clearTimeout(timeoutId);

        // Debug: Log response details
        const responseContentType = response.headers.get('content-type') || '';
        logger.debug('[DebateInput] Response received:', {
          status: response.status,
          statusText: response.statusText,
          contentType: responseContentType,
          url: response.url,
        });

        // Check response status BEFORE parsing JSON
        if (!response.ok) {
          let errorMessage: string;

          if (responseContentType.includes('application/json')) {
            // Server returned JSON error - parse it
            const errorData = await response.json().catch(() => ({}));

            // Auto-fallback to playground if server suggests it (e.g. no API keys configured)
            if (errorData.use_playground && !usePlayground) {
              logger.debug(
                '[DebateInput] Server suggests playground fallback, retrying in playground mode',
              );
              const playgroundUrl = `${apiBase}/api/v1/playground/debate`;
              const playgroundBody = {
                topic: trimmedQuestion,
                rounds,
                agents: requestedAgents.length || 3,
              };
              const pgResponse = await fetch(playgroundUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(playgroundBody),
              });
              if (pgResponse.ok) {
                const pgData = await pgResponse.json();
                const pgDebateId = pgData.debate_id || pgData.id;
                if (pgDebateId) {
                  onDebateStarted?.(pgDebateId, trimmedQuestion);
                  setQuestion('');
                  setIsSubmitting(false);
                  clearTimeout(timeoutId);
                  return;
                }
              }
              // If playground also fails, fall through to show original error
            }

            errorMessage =
              errorData.error || errorData.message || `Server error: ${response.status}`;
          } else {
            // Server returned HTML or other non-JSON response - log for debugging
            const text = await response.text();
            logger.error('[DebateInput] Non-JSON error response:', {
              status: response.status,
              contentType: responseContentType,
              bodyPreview: text.substring(0, 300),
            });

            // User-friendly messages based on status code
            if (response.status === 401) {
              errorMessage = 'Authentication required. Please log in and try again.';
            } else if (response.status === 403) {
              errorMessage = 'Access denied. You may not have permission for this action.';
            } else if (response.status === 404) {
              errorMessage = 'API endpoint not found. The server may be misconfigured.';
            } else if (response.status >= 500) {
              errorMessage = `Server error (${response.status}). The backend may be experiencing issues.`;
            } else {
              errorMessage = `Request failed: ${response.status} ${response.statusText}`;
            }
          }
          throw new Error(errorMessage);
        }

        // Validate content-type before JSON parsing
        if (!responseContentType.includes('application/json')) {
          const text = await response.text();
          logger.error('[DebateInput] Unexpected content-type on success:', {
            expected: 'application/json',
            got: responseContentType,
            bodyPreview: text.substring(0, 300),
          });
          throw new Error(
            `Server returned ${responseContentType || 'unknown content'} instead of JSON. The API may be misconfigured.`,
          );
        }

        // Now safe to parse JSON
        const data = await response.json();

        // Standard endpoint returns {success, debate_id}; playground returns {id, topic, status, ...}
        const debateId = data.debate_id || data.matrix_id || data.id;
        const isSuccess = data.success || (usePlayground && debateId);

        if (isSuccess && debateId) {
          logger.debug('[DebateInput] Debate started successfully:', {
            debateId,
            mode: usePlayground ? 'playground' : debateMode,
          });

          // Navigate to visualization page for Graph/Matrix modes
          if (!usePlayground && debateMode === 'graph') {
            router.push(`/debates/graph?id=${debateId}`);
          } else if (!usePlayground && debateMode === 'matrix') {
            router.push(`/debates/matrix?id=${data.matrix_id || debateId}`);
          } else if (!onDebateStarted) {
            // No callback provided — navigate to the debate detail page by default
            router.push(`/debates/${debateId}`);
          }

          // Always call onDebateStarted for tracking/notification
          onDebateStarted?.(debateId, trimmedQuestion);
          setQuestion('');
        } else {
          logger.warn('[DebateInput] Debate creation failed:', data);
          const errorMessage = data.error || 'Failed to start debate';
          setLocalError(errorMessage);
          onError?.(errorMessage);
        }
      } catch (err) {
        // Enhanced error logging
        logger.error('[DebateInput] Error during debate creation:', err);

        let errorMessage: string;

        if (err instanceof TypeError && err.message === 'Failed to fetch') {
          errorMessage = 'Cannot reach the server. Please check your connection and try again.';
          setApiStatus('offline');
        } else if (err instanceof Error && err.name === 'AbortError') {
          errorMessage = 'Request timed out after 30 seconds. The server may be overloaded.';
        } else if (err instanceof SyntaxError && err.message.includes('Unexpected token')) {
          // This catches JSON parse errors when server returns HTML
          errorMessage =
            'Server returned an invalid response (HTML instead of JSON). The API may be down or misconfigured.';
        } else if (err instanceof Error) {
          errorMessage = err.message;
        } else {
          errorMessage = 'An unexpected error occurred. Please try again.';
        }

        setLocalError(errorMessage);
        onError?.(errorMessage);
      } finally {
        clearTimeout(timeoutId);
        setIsSubmitting(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- selectedVertical changes are handled separately
    [
      question,
      placeholder,
      agents,
      rounds,
      debateMode,
      debateFormat,
      apiBase,
      isSubmitting,
      onDebateStarted,
      onError,
      router,
      tokens,
      authLoading,
      hasLiveAccess,
      allowPlaygroundFallback,
      requiresLiveAuth,
      isAuthenticated,
    ],
  );

  const isDisabled =
    isSubmitting || apiStatus === 'offline' || apiStatus === 'checking' || authLoading;
  const isPlaygroundMode = allowPlaygroundFallback && apiStatus === 'online' && !hasLiveAccess;

  return (
    <div className="w-full max-w-3xl mx-auto">
      {requiresLiveAuth && (
        <div className="mb-4 p-3 bg-warning/10 border border-warning/30 font-theme-data text-sm">
          <div className="flex items-center gap-2 text-warning">
            <span className="w-2 h-2 rounded-full bg-warning" />
            <span>Live debates require an authenticated session.</span>
          </div>
        </div>
      )}
      {/* Playground mode indicator */}
      {isPlaygroundMode && (
        <div className="mb-4 p-3 bg-[var(--accent)]/10 border border-[var(--accent)]/30 font-theme-data text-sm">
          <div className="flex items-center gap-2 text-[var(--accent)]">
            <span className="w-2 h-2 rounded-full bg-[var(--accent)]" />
            <span>Demo mode — using mock agents (no API keys required)</span>
          </div>
        </div>
      )}
      {/* API Status Banner */}
      {apiStatus === 'offline' && (
        <div className="mb-4 p-3 bg-warning/10 border border-warning/30 font-theme-data text-sm">
          <div className="flex items-center gap-2 text-warning">
            <span className="w-2 h-2 rounded-full bg-warning animate-pulse" />
            <span>API server offline</span>
          </div>
          <p className="text-text-muted text-xs mt-1">
            Our servers are being updated. Please try again in a few minutes.
          </p>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-1">
        {/* Main Input */}
        <div className="relative">
          <label htmlFor="debate-question" className="sr-only">
            Enter your debate question
          </label>
          <textarea
            id="debate-question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder={apiStatus === 'offline' ? 'API server offline...' : placeholder}
            disabled={isDisabled}
            rows={3}
            aria-describedby="debate-input-hint"
            className="debate-input w-full bg-surface border-2 border-[var(--accent)]/40 focus:border-[var(--accent)]
                       px-5 py-4 font-theme-data text-lg text-text placeholder-text-muted/40
                       resize-none transition-all focus:outline-none rounded-2xl
                       disabled:opacity-50 disabled:cursor-not-allowed
                       focus:shadow-[0_0_20px_rgba(0,255,65,0.15)]"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                handleSubmit(e);
              }
            }}
          />
          <div
            id="debate-input-hint"
            className="absolute bottom-2 right-2 text-xs text-text-muted font-theme-data"
          >
            {question.length > 0 && `${question.length} chars`}
            {question.length === 0 && 'Cmd+Enter to debate this question'}
          </div>
        </div>

        {/* Agent Routing Hints */}
        {detectedDomain !== 'general' && recommendations.length > 0 && (
          <div className="flex items-center gap-2 p-2 bg-surface/50 border border-[var(--acid-cyan)]/30 rounded">
            <span className="text-xs font-theme-data text-[var(--acid-cyan)]">
              [{detectedDomain.toUpperCase()}]
            </span>
            <span className="text-xs text-text-muted">Suggested agents:</span>
            <div className="flex gap-1 flex-wrap">
              {recommendations.slice(0, 3).map((rec) => (
                <span
                  key={rec.agent}
                  className="px-1.5 py-0.5 text-xs font-theme-data bg-bg rounded text-text"
                  title={`Suitability: ${(rec.suitability * 100).toFixed(0)}%`}
                >
                  {rec.agent}
                </span>
              ))}
            </div>
            <button
              type="button"
              onClick={applyRecommendations}
              aria-label="Use recommended agents"
              className="ml-auto text-xs font-theme-data text-[var(--accent)] hover:text-[var(--accent)]/80 transition-colors"
            >
              [USE]
            </button>
          </div>
        )}

        {/* Options Toggle + Submit */}
        <div className="flex items-center justify-between gap-2 mt-1">
          {/* Options toggle and vertical indicator */}
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              aria-expanded={showAdvanced}
              aria-controls="advanced-options"
              aria-label={showAdvanced ? 'Hide advanced options' : 'Show advanced options'}
              className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
            >
              {showAdvanced ? '[-] Hide options' : '[+] Show options'}
            </button>

            {/* Compact vertical indicator */}
            {!showAdvanced && (
              <VerticalSelector
                apiBase={apiBase}
                selectedVertical={selectedVertical}
                onVerticalChange={setSelectedVertical}
                onAgentsChange={setAgents}
                questionText={question}
                compact
              />
            )}
          </div>

          {/* Compact cost indicator when options are collapsed */}
          {!showAdvanced && (costEstimate || costLoading || costError) && (
            <span className="text-xs font-theme-data">
              {costLoading ? (
                <span className="text-text-muted animate-pulse">estimating...</span>
              ) : costError ? (
                <span className="text-warning/60">cost N/A</span>
              ) : costEstimate ? (
                <span className="text-[var(--accent)]/70">
                  ~${costEstimate.total < 0.01 ? '<0.01' : costEstimate.total.toFixed(2)}
                </span>
              ) : null}
            </span>
          )}

          <button
            type="submit"
            disabled={isDisabled}
            aria-label="Start debate"
            className="px-8 py-3 bg-[var(--accent)] text-bg font-theme-data font-bold text-lg
                       hover:bg-[var(--accent)]/80 transition-colors
                       disabled:bg-text-muted disabled:cursor-not-allowed
                       flex items-center gap-2 shrink-0 relative"
          >
            {isPlaygroundMode && (
              <span className="absolute -top-2 -right-2 px-1.5 py-0.5 text-[10px] font-theme-data font-bold bg-acid-yellow text-bg rounded-sm leading-tight">
                DEMO
              </span>
            )}
            {apiStatus === 'checking' ? (
              <span className="animate-pulse">CONNECTING...</span>
            ) : apiStatus === 'offline' ? (
              <span>OFFLINE</span>
            ) : isSubmitting ? (
              <span className="animate-pulse">STARTING...</span>
            ) : (
              <>
                <span>[&gt;]</span>
                <span>START DEBATE</span>
              </>
            )}
          </button>
        </div>

        {/* Advanced Options */}
        {showAdvanced && (
          <div
            id="advanced-options"
            className="border border-[var(--accent)]/30 p-4 space-y-4 bg-surface/50"
          >
            {/* Debate Mode Selector */}
            <div>
              <label
                id="debate-mode-label"
                className="block text-xs font-theme-data text-text-muted mb-2"
              >
                DEBATE MODE
              </label>
              <div
                className="flex gap-2"
                role="tablist"
                aria-labelledby="debate-mode-label"
                onKeyDown={(e) => {
                  const modes = Object.keys(DEBATE_MODES) as DebateMode[];
                  const currentIndex = modes.indexOf(debateMode);
                  if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
                    e.preventDefault();
                    const nextIndex = (currentIndex + 1) % modes.length;
                    setDebateMode(modes[nextIndex]);
                  } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
                    e.preventDefault();
                    const prevIndex = (currentIndex - 1 + modes.length) % modes.length;
                    setDebateMode(modes[prevIndex]);
                  }
                }}
              >
                {(Object.keys(DEBATE_MODES) as DebateMode[]).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    role="tab"
                    aria-selected={debateMode === mode}
                    aria-label={`${DEBATE_MODES[mode].label} mode: ${DEBATE_MODES[mode].description}`}
                    tabIndex={debateMode === mode ? 0 : -1}
                    onClick={() => setDebateMode(mode)}
                    className={`flex-1 px-3 py-2 text-xs font-theme-data border transition-colors ${
                      debateMode === mode
                        ? 'bg-[var(--accent)] text-bg border-[var(--accent)]'
                        : 'bg-bg text-text-muted border-[var(--accent)]/30 hover:border-[var(--accent)]/60'
                    }`}
                    title={DEBATE_MODES[mode].description}
                  >
                    {DEBATE_MODES[mode].label.toUpperCase()}
                  </button>
                ))}
              </div>
              <p className="text-[10px] text-text-muted mt-1">
                {DEBATE_MODES[debateMode].description}
              </p>
            </div>

            {/* Debate Format Selector */}
            <div>
              <label
                id="debate-format-label"
                className="block text-xs font-theme-data text-text-muted mb-2"
              >
                DEBATE DEPTH
              </label>
              <div
                className="flex gap-2"
                role="radiogroup"
                aria-labelledby="debate-format-label"
                onKeyDown={(e) => {
                  const formats = Object.keys(DEBATE_FORMATS) as DebateFormat[];
                  const currentIndex = formats.indexOf(debateFormat);
                  if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
                    e.preventDefault();
                    const nextIndex = (currentIndex + 1) % formats.length;
                    setDebateFormat(formats[nextIndex]);
                  } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
                    e.preventDefault();
                    const prevIndex = (currentIndex - 1 + formats.length) % formats.length;
                    setDebateFormat(formats[prevIndex]);
                  }
                }}
              >
                {(Object.keys(DEBATE_FORMATS) as DebateFormat[]).map((format) => (
                  <button
                    key={format}
                    type="button"
                    role="radio"
                    aria-checked={debateFormat === format}
                    aria-label={`${DEBATE_FORMATS[format].label}: ${DEBATE_FORMATS[format].description}, ${DEBATE_FORMATS[format].time}`}
                    tabIndex={debateFormat === format ? 0 : -1}
                    onClick={() => setDebateFormat(format)}
                    className={`flex-1 px-3 py-2 text-xs font-theme-data border transition-colors ${
                      debateFormat === format
                        ? 'bg-[var(--accent)] text-bg border-[var(--accent)]'
                        : 'bg-bg text-text-muted border-[var(--accent)]/30 hover:border-[var(--accent)]/60'
                    }`}
                    title={`${DEBATE_FORMATS[format].description} (${DEBATE_FORMATS[format].time})`}
                  >
                    <span className="mr-1">{DEBATE_FORMATS[format].icon}</span>
                    {DEBATE_FORMATS[format].label.toUpperCase()}
                    <span className="block text-[10px] opacity-70 mt-0.5">
                      {DEBATE_FORMATS[format].time}
                    </span>
                  </button>
                ))}
              </div>
              <p className="text-[10px] text-text-muted mt-1">
                {DEBATE_FORMATS[debateFormat].description}
              </p>
            </div>

            {/* Vertical Selector */}
            <VerticalSelector
              apiBase={apiBase}
              selectedVertical={selectedVertical}
              onVerticalChange={setSelectedVertical}
              onAgentsChange={setAgents}
              questionText={question}
            />

            <div className="grid grid-cols-2 gap-4">
              {/* Agents */}
              <div>
                <label
                  htmlFor="debate-agents"
                  className="block text-xs font-theme-data text-text-muted mb-1"
                >
                  AGENTS (comma-separated)
                </label>
                <input
                  id="debate-agents"
                  type="text"
                  value={agents}
                  onChange={(e) => setAgents(e.target.value)}
                  className="w-full bg-bg border border-[var(--accent)]/30 px-3 py-2
                             font-theme-data text-sm text-text focus:border-[var(--accent)]
                             focus:outline-none"
                  placeholder="grok,anthropic-api,openai-api,deepseek"
                />
                <p className="text-[10px] text-text-muted mt-1">
                  Leave blank to auto-select a balanced team, or enter comma-separated agent ids.
                </p>
              </div>

              {/* Rounds */}
              <div>
                <label
                  htmlFor="debate-rounds"
                  className="block text-xs font-theme-data text-text-muted mb-1"
                >
                  DEBATE ROUNDS
                </label>
                <select
                  id="debate-rounds"
                  value={rounds}
                  onChange={(e) => setRounds(parseInt(e.target.value))}
                  className="w-full bg-bg border border-[var(--accent)]/30 px-3 py-2
                             font-theme-data text-sm text-text focus:border-[var(--accent)]
                             focus:outline-none"
                >
                  {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((n) => (
                    <option key={n} value={n}>
                      {n} round{n !== 1 ? 's' : ''}
                      {n === 8 ? ' (recommended)' : ''}
                    </option>
                  ))}
                </select>
                <p className="text-[10px] text-text-muted mt-1">
                  8 rounds = full 9-phase format (context through adjudication)
                </p>
              </div>

              {/* Budget Limit */}
              <div>
                <label
                  htmlFor="debate-budget"
                  className="block text-xs font-theme-data text-text-muted mb-1"
                >
                  BUDGET CAP (USD)
                </label>
                <input
                  id="debate-budget"
                  type="number"
                  min="0.01"
                  max="100"
                  step="0.01"
                  value={budgetLimit}
                  onChange={(e) => setBudgetLimit(e.target.value)}
                  placeholder="No limit"
                  className={`w-full bg-bg border px-3 py-2
                             font-theme-data text-sm text-text focus:outline-none transition-colors
                             ${
                               budgetLimit &&
                               costEstimate &&
                               parseFloat(budgetLimit) > 0 &&
                               parseFloat(budgetLimit) < costEstimate.total
                                 ? 'border-warning/60 focus:border-warning'
                                 : 'border-[var(--accent)]/30 focus:border-[var(--accent)]'
                             }`}
                />
                {budgetLimit &&
                costEstimate &&
                parseFloat(budgetLimit) > 0 &&
                parseFloat(budgetLimit) < costEstimate.total ? (
                  <p className="text-[10px] text-warning mt-1 font-theme-data">
                    Budget ${parseFloat(budgetLimit).toFixed(2)} is below estimated cost $
                    {costEstimate.total.toFixed(2)}
                  </p>
                ) : (
                  <p className="text-[10px] text-text-muted mt-1">
                    Debate halts when cost reaches this limit
                  </p>
                )}
              </div>
            </div>

            {/* Cost Estimate Preview */}
            {(costEstimate || costLoading || costError) && (
              <div
                className={`border p-3 bg-bg/50 transition-colors ${
                  costError ? 'border-warning/30' : 'border-[var(--acid-cyan)]/30'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-theme-data text-[var(--acid-cyan)]">
                    ESTIMATED COST
                  </span>
                  {costLoading ? (
                    <span className="text-sm font-theme-data text-text-muted">
                      <span className="inline-flex gap-0.5">
                        <span className="animate-pulse">.</span>
                        <span className="animate-pulse" style={{ animationDelay: '150ms' }}>
                          .
                        </span>
                        <span className="animate-pulse" style={{ animationDelay: '300ms' }}>
                          .
                        </span>
                      </span>
                    </span>
                  ) : costError ? (
                    <span className="text-xs font-theme-data text-warning/80">unavailable</span>
                  ) : costEstimate ? (
                    <span className="text-lg font-theme-data font-bold text-[var(--accent)]">
                      ${costEstimate.total < 0.01 ? '<0.01' : costEstimate.total.toFixed(2)}
                    </span>
                  ) : null}
                </div>
                {!costError && costEstimate && costEstimate.breakdown.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {costEstimate.breakdown.map((b, i) => (
                      <div
                        key={i}
                        className="flex items-center justify-between text-[10px] font-theme-data text-text-muted"
                      >
                        <span>{b.model}</span>
                        <span>${b.subtotal < 0.001 ? '<0.001' : b.subtotal.toFixed(3)}</span>
                      </div>
                    ))}
                  </div>
                )}
                <p className="text-[10px] text-text-muted/50 mt-1">
                  {costError
                    ? 'Could not reach cost API. Debate will still work.'
                    : 'Based on average token usage. Actual cost may vary.'}
                </p>
              </div>
            )}
          </div>
        )}
      </form>

      {/* Error display */}
      {localError && (
        <div className="mt-4 p-3 bg-red-900/20 border border-red-500/40 rounded font-theme-data text-sm">
          <div className="flex items-start gap-2">
            <span className="text-red-400 shrink-0">[ERROR]</span>
            <span className="text-red-300">{localError}</span>
          </div>
          <button
            type="button"
            onClick={() => setLocalError(null)}
            className="mt-2 text-xs text-red-400/70 hover:text-red-300 transition-colors"
          >
            [DISMISS]
          </button>
        </div>
      )}

      {/* Status hint - only show offline/connecting states */}
      {apiStatus !== 'online' && (
        <div className="mt-4 text-center">
          {apiStatus === 'offline' ? (
            <p className="text-[10px] font-theme-data text-warning/50">
              Server temporarily unavailable — please try again shortly
            </p>
          ) : (
            <p className="text-[10px] font-theme-data text-text-muted/40 animate-pulse">
              Connecting...
            </p>
          )}
        </div>
      )}
    </div>
  );
}
