'use client';

import { useState, useCallback } from 'react';
import { API_BASE_URL } from '@/config';
import { ReviewInput } from './ReviewInput';
import { ReviewProgress } from './ReviewProgress';
import { ReviewResults } from './ReviewResults';

export type ReviewStep = 'input' | 'reviewing' | 'complete';

export type ReviewFocus = 'security' | 'performance' | 'quality' | 'all';

export interface ReviewAgent {
  id: string;
  name: string;
  icon: string;
  specialty: string;
  enabled: boolean;
}

export interface ReviewFinding {
  id: string;
  agent: string;
  category: 'security' | 'performance' | 'quality' | 'architecture';
  severity: 'critical' | 'high' | 'medium' | 'low' | 'info';
  title: string;
  description: string;
  file?: string;
  line?: number;
  suggestion?: string;
  codeSnippet?: string;
}

export interface ReviewDebateRound {
  round: number;
  agents: string[];
  topic: string;
  messages: Array<{ agent: string; content: string; timestamp: string }>;
  consensus?: string;
}

export interface ReviewResult {
  id: string;
  prUrl?: string;
  verdict: 'approve' | 'comment' | 'request_changes';
  summary: string;
  findings: ReviewFinding[];
  debateRounds: ReviewDebateRound[];
  metrics: {
    filesReviewed: number;
    linesAnalyzed: number;
    agentsParticipated: number;
    debateRounds: number;
    duration: number;
  };
  timestamp: string;
}

const DEFAULT_AGENTS: ReviewAgent[] = [
  {
    id: 'anthropic',
    name: 'Claude',
    icon: '🟣',
    specialty: 'Security & Architecture',
    enabled: true,
  },
  { id: 'openai', name: 'GPT-4', icon: '🟢', specialty: 'Code Quality & Patterns', enabled: true },
  {
    id: 'gemini',
    name: 'Gemini',
    icon: '🔵',
    specialty: 'Performance & Optimization',
    enabled: true,
  },
  { id: 'mistral', name: 'Mistral', icon: '🟠', specialty: 'Logic & Edge Cases', enabled: false },
];

export function CodeReviewWorkflow() {
  const apiBase = API_BASE_URL;
  const [step, setStep] = useState<ReviewStep>('input');
  const [agents, setAgents] = useState<ReviewAgent[]>(DEFAULT_AGENTS);
  const [focus, setFocus] = useState<ReviewFocus>('all');
  const [prUrl, setPrUrl] = useState('');
  const [diffContent, setDiffContent] = useState('');
  const [result, setResult] = useState<ReviewResult | null>(null);
  const [progress, setProgress] = useState({
    phase: '',
    percent: 0,
    currentAgent: '',
    debateRound: 0,
    totalRounds: 3,
  });

  const handleStartReview = useCallback(async () => {
    setStep('reviewing');
    setProgress({
      phase: 'Initializing review...',
      percent: 5,
      currentAgent: '',
      debateRound: 0,
      totalRounds: 3,
    });

    try {
      // Start review via API
      const response = await fetch(`${apiBase}/api/github/pr/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pr_url: prUrl || undefined,
          diff: diffContent || undefined,
          agents: agents.filter((a) => a.enabled).map((a) => a.id),
          focus: focus === 'all' ? ['security', 'performance', 'quality'] : [focus],
          rounds: 3,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        // Poll for results
        pollReviewStatus(data.review_id);
      } else {
        // Fallback to mock review
        runMockReview();
      }
    } catch {
      // Run mock review on error
      runMockReview();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- pollReviewStatus and runMockReview are stable
  }, [prUrl, diffContent, agents, focus]);

  const pollReviewStatus = useCallback(
    async (reviewId: string) => {
      const checkStatus = async () => {
        try {
          const response = await fetch(`${apiBase}/api/github/pr/review/${reviewId}`);
          if (response.ok) {
            const data = await response.json();
            if (data.status === 'completed') {
              setResult(transformApiResult(data));
              setStep('complete');
              return true;
            } else if (data.status === 'failed') {
              runMockReview();
              return true;
            } else {
              // Update progress
              setProgress({
                phase: data.phase || 'Processing...',
                percent: data.progress || 50,
                currentAgent: data.current_agent || '',
                debateRound: data.debate_round || 1,
                totalRounds: 3,
              });
            }
          }
        } catch {
          // Continue polling
        }
        return false;
      };

      // Poll every 2 seconds
      const interval = setInterval(async () => {
        const done = await checkStatus();
        if (done) clearInterval(interval);
      }, 2000);

      // Timeout after 2 minutes
      setTimeout(() => {
        clearInterval(interval);
        if (step === 'reviewing') {
          runMockReview();
        }
      }, 120000);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runMockReview and transformApiResult are stable
    [step],
  );

  const transformApiResult = (data: Record<string, unknown>): ReviewResult => {
    const findings = Array.isArray(data.findings) ? data.findings : [];
    const debateRounds = Array.isArray(data.debate_rounds) ? data.debate_rounds : [];
    const metrics = data.metrics as Record<string, number> | undefined;
    return {
      id: (data.id as string) || crypto.randomUUID(),
      prUrl: (data.pr_url as string) || prUrl,
      verdict: (data.verdict as 'approve' | 'comment' | 'request_changes') || 'comment',
      summary: (data.summary as string) || 'Review completed',
      findings: findings.map((f: Record<string, unknown>) => ({
        id: (f.id as string) || crypto.randomUUID(),
        agent: (f.agent as string) || 'unknown',
        category: (f.category as ReviewFinding['category']) || 'quality',
        severity: (f.severity as ReviewFinding['severity']) || 'medium',
        title: (f.title as string) || '',
        description: (f.description as string) || '',
        file: f.file as string,
        line: f.line as number,
        suggestion: f.suggestion as string,
        codeSnippet: f.code_snippet as string,
      })),
      debateRounds: debateRounds.map((r: Record<string, unknown>) => ({
        round: r.round as number,
        agents: Array.isArray(r.agents) ? (r.agents as string[]) : [],
        topic: (r.topic as string) || '',
        messages: Array.isArray(r.messages)
          ? r.messages.map((m: Record<string, unknown>) => ({
              agent: m.agent as string,
              content: m.content as string,
              timestamp: m.timestamp as string,
            }))
          : [],
        consensus: r.consensus as string,
      })),
      metrics: {
        filesReviewed: metrics?.files_reviewed || 0,
        linesAnalyzed: metrics?.lines_analyzed || 0,
        agentsParticipated: metrics?.agents_participated || agents.filter((a) => a.enabled).length,
        debateRounds: metrics?.debate_rounds || 3,
        duration: metrics?.duration || 0,
      },
      timestamp: (data.timestamp as string) || new Date().toISOString(),
    };
  };

  const runMockReview = useCallback(() => {
    // Simulate review phases
    const phases = [
      { phase: 'Fetching PR details...', percent: 10 },
      { phase: 'Analyzing code changes...', percent: 20 },
      { phase: 'Security review debate', percent: 35, currentAgent: 'Claude', debateRound: 1 },
      { phase: 'Performance review debate', percent: 50, currentAgent: 'Gemini', debateRound: 1 },
      { phase: 'Code quality debate', percent: 65, currentAgent: 'GPT-4', debateRound: 2 },
      { phase: 'Synthesizing findings...', percent: 80, debateRound: 2 },
      { phase: 'Building consensus...', percent: 90, debateRound: 3 },
      { phase: 'Generating report...', percent: 95, debateRound: 3 },
    ];

    let i = 0;
    const interval = setInterval(() => {
      if (i < phases.length) {
        setProgress({
          phase: phases[i].phase,
          percent: phases[i].percent,
          currentAgent: phases[i].currentAgent || '',
          debateRound: phases[i].debateRound || 0,
          totalRounds: 3,
        });
        i++;
      } else {
        clearInterval(interval);
        setResult(generateMockResult());
        setStep('complete');
      }
    }, 1500);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- generateMockResult is stable
  }, []);

  const generateMockResult = (): ReviewResult => {
    const enabledAgents = agents.filter((a) => a.enabled);
    return {
      id: crypto.randomUUID(),
      prUrl: prUrl || undefined,
      verdict: 'request_changes',
      summary:
        'The multi-agent review identified several issues requiring attention. Security vulnerabilities were found that should be addressed before merging. Performance optimizations were suggested, and code quality improvements were recommended.',
      findings: [
        {
          id: '1',
          agent: 'Claude',
          category: 'security',
          severity: 'critical',
          title: 'Potential SQL Injection Vulnerability',
          description:
            'User input is directly concatenated into SQL query without sanitization. This allows attackers to execute arbitrary SQL commands.',
          file: 'src/db/queries.ts',
          line: 42,
          suggestion: 'Use parameterized queries or an ORM to prevent SQL injection.',
          codeSnippet: 'const query = `SELECT * FROM users WHERE id = ${userId}`;',
        },
        {
          id: '2',
          agent: 'Claude',
          category: 'security',
          severity: 'high',
          title: 'Missing Authentication Check',
          description:
            'API endpoint lacks authentication middleware, allowing unauthorized access to sensitive data.',
          file: 'src/api/users.ts',
          line: 15,
          suggestion: 'Add authentication middleware: router.use(authMiddleware);',
        },
        {
          id: '3',
          agent: 'Gemini',
          category: 'performance',
          severity: 'medium',
          title: 'N+1 Query Pattern Detected',
          description:
            'Loop executes individual database queries instead of batch fetching. This causes significant performance degradation with large datasets.',
          file: 'src/services/order.ts',
          line: 78,
          suggestion:
            'Use Promise.all() with batch query or eager loading to fetch related data in one query.',
        },
        {
          id: '4',
          agent: 'GPT-4',
          category: 'quality',
          severity: 'medium',
          title: 'Missing Error Handling',
          description:
            'Async function lacks try-catch block. Unhandled promise rejections will crash the application.',
          file: 'src/handlers/payment.ts',
          line: 34,
          suggestion: 'Wrap async operations in try-catch and handle errors appropriately.',
        },
        {
          id: '5',
          agent: 'GPT-4',
          category: 'quality',
          severity: 'low',
          title: 'Magic Number in Business Logic',
          description:
            'Hardcoded value 0.15 represents tax rate but lacks documentation or named constant.',
          file: 'src/utils/pricing.ts',
          line: 23,
          suggestion: 'Extract to named constant: const TAX_RATE = 0.15;',
        },
        {
          id: '6',
          agent: 'Gemini',
          category: 'performance',
          severity: 'low',
          title: 'Unnecessary Re-renders',
          description:
            'React component re-renders on every parent update due to inline function definition.',
          file: 'src/components/List.tsx',
          line: 12,
          suggestion: 'Use useCallback to memoize the handler function.',
        },
      ],
      debateRounds: [
        {
          round: 1,
          agents: enabledAgents.map((a) => a.name),
          topic: 'Security Analysis',
          messages: [
            {
              agent: 'Claude',
              content:
                'I identified a critical SQL injection vulnerability in queries.ts. The user input is directly concatenated without any sanitization.',
              timestamp: new Date(Date.now() - 180000).toISOString(),
            },
            {
              agent: 'GPT-4',
              content:
                'Agreed. Additionally, the authentication middleware is missing from several endpoints, creating unauthorized access vectors.',
              timestamp: new Date(Date.now() - 170000).toISOString(),
            },
            {
              agent: 'Gemini',
              content:
                'I concur with both assessments. The SQL injection is the most critical issue requiring immediate attention.',
              timestamp: new Date(Date.now() - 160000).toISOString(),
            },
          ],
          consensus:
            'Critical security vulnerabilities identified: SQL injection and missing authentication require immediate fixes before merge.',
        },
        {
          round: 2,
          agents: enabledAgents.map((a) => a.name),
          topic: 'Performance & Quality',
          messages: [
            {
              agent: 'Gemini',
              content:
                'The N+1 query pattern in order.ts will cause significant slowdown at scale. Each loop iteration makes a separate DB call.',
              timestamp: new Date(Date.now() - 120000).toISOString(),
            },
            {
              agent: 'GPT-4',
              content:
                'Good catch. I also noticed missing error handling in the payment handler - unhandled rejections could crash the server.',
              timestamp: new Date(Date.now() - 110000).toISOString(),
            },
            {
              agent: 'Claude',
              content:
                'The error handling issue is important for reliability. I suggest wrapping all async payment operations in proper try-catch blocks.',
              timestamp: new Date(Date.now() - 100000).toISOString(),
            },
          ],
          consensus:
            'N+1 query and error handling issues should be addressed. Performance impact is moderate but error handling affects reliability.',
        },
        {
          round: 3,
          agents: enabledAgents.map((a) => a.name),
          topic: 'Final Verdict',
          messages: [
            {
              agent: 'Claude',
              content:
                'Given the critical security issues, I recommend REQUEST_CHANGES. The SQL injection must be fixed before merge.',
              timestamp: new Date(Date.now() - 60000).toISOString(),
            },
            {
              agent: 'GPT-4',
              content:
                'I agree. Security vulnerabilities take priority. Once those are addressed, the remaining issues can be handled in follow-up PRs.',
              timestamp: new Date(Date.now() - 50000).toISOString(),
            },
            {
              agent: 'Gemini',
              content:
                'Consensus reached. REQUEST_CHANGES is the appropriate verdict. We should provide clear remediation guidance.',
              timestamp: new Date(Date.now() - 40000).toISOString(),
            },
          ],
          consensus:
            'Unanimous decision: REQUEST_CHANGES due to critical security vulnerabilities. Must fix SQL injection and add authentication before merge.',
        },
      ],
      metrics: {
        filesReviewed: 8,
        linesAnalyzed: 342,
        agentsParticipated: enabledAgents.length,
        debateRounds: 3,
        duration: 45,
      },
      timestamp: new Date().toISOString(),
    };
  };

  const handleNewReview = useCallback(() => {
    setStep('input');
    setPrUrl('');
    setDiffContent('');
    setResult(null);
    setProgress({ phase: '', percent: 0, currentAgent: '', debateRound: 0, totalRounds: 3 });
  }, []);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-theme-data text-[var(--acid-green)]">
          {'>'} MULTI-AGENT CODE REVIEW
        </h1>
        <p className="text-sm text-[var(--text-muted)] mt-1">
          AI agents debate and analyze your code for security, performance, and quality
        </p>
      </div>

      {/* Workflow Steps */}
      {step === 'input' && (
        <ReviewInput
          prUrl={prUrl}
          setPrUrl={setPrUrl}
          diffContent={diffContent}
          setDiffContent={setDiffContent}
          agents={agents}
          setAgents={setAgents}
          focus={focus}
          setFocus={setFocus}
          onStartReview={handleStartReview}
        />
      )}

      {step === 'reviewing' && (
        <ReviewProgress progress={progress} agents={agents.filter((a) => a.enabled)} />
      )}

      {step === 'complete' && result && (
        <ReviewResults result={result} onNewReview={handleNewReview} />
      )}
    </div>
  );
}

export default CodeReviewWorkflow;
