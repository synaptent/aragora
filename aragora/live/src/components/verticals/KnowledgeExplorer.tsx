'use client';

/**
 * Knowledge Explorer Component
 *
 * Allows users to explore the Knowledge Mound - browsing indexed content,
 * viewing facts with provenance, and seeing reasoning patterns.
 */

import { useState, useCallback, useMemo } from 'react';

export interface KnowledgeFact {
  id: string;
  content: string;
  vertical: string;
  factType: string;
  confidence: number;
  sources: string[];
  extractedAt: string;
  lastVerified?: string;
  metadata: Record<string, unknown>;
}

export interface ReasoningPattern {
  id: string;
  name: string;
  description: string;
  occurrences: number;
  successRate: number;
  domains: string[];
}

interface KnowledgeExplorerProps {
  facts?: KnowledgeFact[];
  patterns?: ReasoningPattern[];
  selectedVertical?: string;
  onFactClick?: (fact: KnowledgeFact) => void;
  onPatternClick?: (pattern: ReasoningPattern) => void;
}

// Mock data for demonstration
const MOCK_FACTS: KnowledgeFact[] = [
  {
    id: 'fact_001',
    content: 'SQL injection vulnerabilities found in user input handling',
    vertical: 'software',
    factType: 'security_vulnerability',
    confidence: 0.95,
    sources: ['src/api/users.py:42', 'src/db/queries.py:118'],
    extractedAt: '2024-01-15T10:30:00Z',
    lastVerified: '2024-01-16T08:00:00Z',
    metadata: { severity: 'high', cwe: 'CWE-89' },
  },
  {
    id: 'fact_002',
    content: 'Indemnification clause missing from vendor contract',
    vertical: 'legal',
    factType: 'contract_issue',
    confidence: 0.88,
    sources: ['contracts/vendor_agreement_v3.pdf'],
    extractedAt: '2024-01-14T14:20:00Z',
    metadata: { risk_level: 'high' },
  },
  {
    id: 'fact_003',
    content: 'PHI data detected in logging output',
    vertical: 'healthcare',
    factType: 'compliance_violation',
    confidence: 0.92,
    sources: ['logs/app.log:1542'],
    extractedAt: '2024-01-15T09:15:00Z',
    metadata: { hipaa_violation: true },
  },
];

const MOCK_PATTERNS: ReasoningPattern[] = [
  {
    id: 'pattern_001',
    name: 'Security-First Analysis',
    description: 'Prioritize security considerations in code review',
    occurrences: 47,
    successRate: 0.89,
    domains: ['software'],
  },
  {
    id: 'pattern_002',
    name: 'Risk Escalation Path',
    description: 'High-severity issues should trigger immediate review',
    occurrences: 23,
    successRate: 0.94,
    domains: ['software', 'legal', 'healthcare'],
  },
];

type TabType = 'facts' | 'patterns' | 'culture';

export function KnowledgeExplorer({
  facts = MOCK_FACTS,
  patterns = MOCK_PATTERNS,
  selectedVertical,
  onFactClick,
  onPatternClick,
}: KnowledgeExplorerProps) {
  const [activeTab, setActiveTab] = useState<TabType>('facts');
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedFactId, setExpandedFactId] = useState<string | null>(null);

  // Filter facts by vertical and search
  const filteredFacts = useMemo(() => {
    return facts.filter((fact) => {
      const matchesVertical = !selectedVertical || fact.vertical === selectedVertical;
      const matchesSearch =
        !searchQuery ||
        fact.content.toLowerCase().includes(searchQuery.toLowerCase()) ||
        fact.factType.toLowerCase().includes(searchQuery.toLowerCase());
      return matchesVertical && matchesSearch;
    });
  }, [facts, selectedVertical, searchQuery]);

  // Filter patterns by vertical
  const filteredPatterns = useMemo(() => {
    return patterns.filter((pattern) => {
      return !selectedVertical || pattern.domains.includes(selectedVertical);
    });
  }, [patterns, selectedVertical]);

  const handleFactClick = useCallback(
    (fact: KnowledgeFact) => {
      setExpandedFactId(expandedFactId === fact.id ? null : fact.id);
      onFactClick?.(fact);
    },
    [expandedFactId, onFactClick],
  );

  const getConfidenceColor = (confidence: number) => {
    if (confidence >= 0.9) return 'text-[var(--accent)]';
    if (confidence >= 0.7) return 'text-yellow-400';
    return 'text-orange-400';
  };

  const getVerticalIcon = (vertical: string) => {
    const icons: Record<string, string> = {
      software: '💻',
      legal: '⚖️',
      healthcare: '🏥',
      accounting: '📊',
      research: '🔬',
    };
    return icons[vertical] || '📝';
  };

  return (
    <div className="bg-surface border border-border rounded-lg overflow-hidden h-full flex flex-col">
      {/* Header */}
      <div className="px-4 py-3 border-b border-border bg-bg flex-shrink-0">
        <h3 className="text-sm font-theme-data font-bold text-[var(--accent)]">
          KNOWLEDGE MOUND EXPLORER
        </h3>
        <p className="text-xs text-text-muted mt-1">
          Browse organizational knowledge and reasoning patterns
        </p>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border flex-shrink-0">
        {(['facts', 'patterns', 'culture'] as TabType[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`
              px-4 py-2 text-xs font-theme-data uppercase
              ${
                activeTab === tab
                  ? 'text-[var(--accent)] border-b-2 border-[var(--accent)] bg-bg'
                  : 'text-text-muted hover:text-text'
              }
            `}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Search (for facts tab) */}
      {activeTab === 'facts' && (
        <div className="p-4 border-b border-border flex-shrink-0">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search facts..."
            className="w-full px-3 py-2 bg-bg border border-border rounded text-sm font-theme-data text-text placeholder:text-text-muted focus:outline-none focus:border-[var(--accent)]"
          />
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        {activeTab === 'facts' && (
          <div className="space-y-2">
            {filteredFacts.length === 0 ? (
              <p className="text-sm text-text-muted text-center py-8">No facts found</p>
            ) : (
              filteredFacts.map((fact) => (
                <div
                  key={fact.id}
                  className={`
                    p-3 bg-bg border border-border rounded-lg cursor-pointer
                    hover:border-text-muted transition-colors
                    ${expandedFactId === fact.id ? 'border-[var(--accent)]' : ''}
                  `}
                  onClick={() => handleFactClick(fact)}
                >
                  {/* Fact Header */}
                  <div className="flex items-start gap-2">
                    <span className="text-lg">{getVerticalIcon(fact.vertical)}</span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-text">{fact.content}</p>
                      <div className="flex items-center gap-2 mt-1">
                        <span className="text-xs font-theme-data px-1.5 py-0.5 bg-surface border border-border rounded">
                          {fact.factType}
                        </span>
                        <span
                          className={`text-xs font-theme-data ${getConfidenceColor(fact.confidence)}`}
                        >
                          {Math.round(fact.confidence * 100)}% confidence
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Expanded Details */}
                  {expandedFactId === fact.id && (
                    <div className="mt-3 pt-3 border-t border-border">
                      <div className="grid grid-cols-2 gap-4 text-xs">
                        <div>
                          <span className="text-text-muted">Sources:</span>
                          <ul className="mt-1 space-y-0.5">
                            {fact.sources.map((source, i) => (
                              <li key={i} className="font-theme-data text-cyan-400">
                                {source}
                              </li>
                            ))}
                          </ul>
                        </div>
                        <div>
                          <span className="text-text-muted">Extracted:</span>
                          <p className="mt-1 font-theme-data">
                            {new Date(fact.extractedAt).toLocaleDateString()}
                          </p>
                          {fact.lastVerified && (
                            <>
                              <span className="text-text-muted mt-2 block">Verified:</span>
                              <p className="mt-1 font-theme-data text-[var(--accent)]">
                                {new Date(fact.lastVerified).toLocaleDateString()}
                              </p>
                            </>
                          )}
                        </div>
                      </div>
                      {Object.keys(fact.metadata).length > 0 && (
                        <div className="mt-3">
                          <span className="text-xs text-text-muted">Metadata:</span>
                          <pre className="mt-1 text-xs font-theme-data bg-surface p-2 rounded overflow-x-auto">
                            {JSON.stringify(fact.metadata, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === 'patterns' && (
          <div className="space-y-2">
            {filteredPatterns.length === 0 ? (
              <p className="text-sm text-text-muted text-center py-8">No patterns found</p>
            ) : (
              filteredPatterns.map((pattern) => (
                <div
                  key={pattern.id}
                  className="p-3 bg-bg border border-border rounded-lg cursor-pointer hover:border-text-muted transition-colors"
                  onClick={() => onPatternClick?.(pattern)}
                >
                  <div className="flex items-center justify-between">
                    <h4 className="font-theme-data font-bold text-text">{pattern.name}</h4>
                    <span className="text-xs font-theme-data text-[var(--accent)]">
                      {Math.round(pattern.successRate * 100)}% success
                    </span>
                  </div>
                  <p className="text-sm text-text-muted mt-1">{pattern.description}</p>
                  <div className="flex items-center gap-3 mt-2 text-xs text-text-muted">
                    <span>{pattern.occurrences} occurrences</span>
                    <span>•</span>
                    <span>Domains: {pattern.domains.join(', ')}</span>
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === 'culture' && (
          <div className="text-center py-8">
            <span className="text-4xl">🐜</span>
            <h4 className="font-theme-data font-bold text-text mt-4">Organizational Culture</h4>
            <p className="text-sm text-text-muted mt-2">
              Stigmergic signals and reasoning patterns accumulated from debates
            </p>
            <div className="mt-6 grid grid-cols-3 gap-4 text-center">
              <div className="p-3 bg-bg border border-border rounded">
                <div className="text-2xl font-bold text-[var(--accent)]">47</div>
                <div className="text-xs text-text-muted">Patterns</div>
              </div>
              <div className="p-3 bg-bg border border-border rounded">
                <div className="text-2xl font-bold text-cyan-400">23</div>
                <div className="text-xs text-text-muted">Heuristics</div>
              </div>
              <div className="p-3 bg-bg border border-border rounded">
                <div className="text-2xl font-bold text-purple-400">156</div>
                <div className="text-xs text-text-muted">Signals</div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Footer Stats */}
      <div className="px-4 py-2 border-t border-border bg-bg flex-shrink-0">
        <div className="flex items-center justify-between text-xs font-theme-data text-text-muted">
          <span>
            {activeTab === 'facts' && `${filteredFacts.length} facts`}
            {activeTab === 'patterns' && `${filteredPatterns.length} patterns`}
            {activeTab === 'culture' && 'Culture insights'}
          </span>
          {selectedVertical && (
            <span className="text-[var(--accent)]">
              {getVerticalIcon(selectedVertical)} {selectedVertical}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export default KnowledgeExplorer;
