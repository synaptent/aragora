'use client';

import { useState, useMemo, useRef, useEffect, useCallback } from 'react';
import type { StreamEvent } from '@/types/events';
import { isAgentMessage } from '@/types/events';
import { RoleBadge } from './RoleBadge';
import { getAgentColors } from '@/utils/agentColors';
import { logger } from '@/utils/logger';
import { API_BASE_URL } from '@/config';

// Agent status types derived from event stream
type AgentStatus = 'idle' | 'thinking' | 'active' | 'rate_limited' | 'failed';

// Status indicator component
function StatusBadge({ status, compact = false }: { status: AgentStatus; compact?: boolean }) {
  const config: Record<AgentStatus, { color: string; label: string; animate?: boolean }> = {
    idle: { color: 'bg-text-muted/30', label: 'IDLE' },
    thinking: { color: 'bg-[var(--acid-cyan)]', label: 'THINKING', animate: true },
    active: { color: 'bg-[var(--accent)]', label: 'ACTIVE' },
    rate_limited: { color: 'bg-yellow-500', label: 'LIMITED' },
    failed: { color: 'bg-red-500', label: 'FAILED' },
  };
  const { color, label, animate } = config[status];

  if (compact) {
    return (
      <span
        className={`w-2 h-2 rounded-full ${color} ${animate ? 'animate-pulse' : ''}`}
        title={label}
      />
    );
  }

  return (
    <span
      className={`px-1.5 py-0.5 text-[10px] font-theme-data uppercase rounded ${color} ${
        status === 'thinking' || status === 'active' ? 'text-background' : 'text-text'
      } ${animate ? 'animate-pulse' : ''}`}
    >
      {label}
    </span>
  );
}

interface AgentTabsProps {
  events: StreamEvent[];
  apiBase?: string;
}

interface PositionEntry {
  topic: string;
  position: string;
  confidence: number;
  evidence_count: number;
  last_updated: string;
}

const DEFAULT_API_BASE = API_BASE_URL;

// Special tab ID for unified "All Agents" view
const ALL_AGENTS_TAB = '__all__';

// Terminal-style role indicators
const ROLE_ICONS: Record<string, string> = {
  proposer: '💡',
  critic: '🔍',
  synthesizer: '🔄',
  judge: '⚖️',
  reviewer: '📋',
  implementer: '🛠️',
  default: '▶',
};

interface AgentData {
  name: string;
  latestContent: string;
  role: string;
  cognitiveRole?: string;
  round: number;
  confidence?: number;
  citations?: string[];
  timestamp: number;
  status: AgentStatus;
  lastActivity: number;
  allMessages: Array<{ content: string; round: number; role: string; timestamp: number }>;
}

export function AgentTabs({ events, apiBase = DEFAULT_API_BASE }: AgentTabsProps) {
  // Default to "All Agents" unified timeline view
  const [selectedAgent, setSelectedAgent] = useState<string>(ALL_AGENTS_TAB);
  const [showHistory, setShowHistory] = useState(false);
  const [showPositions, setShowPositions] = useState(false);
  const [positions, setPositions] = useState<PositionEntry[]>([]);
  const [positionsLoading, setPositionsLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  // Fetch positions when viewing individual agent
  const fetchPositions = useCallback(
    async (agentName: string) => {
      setPositionsLoading(true);
      try {
        const response = await fetch(
          `${apiBase}/api/agent/${encodeURIComponent(agentName)}/positions`,
        );
        if (response.ok) {
          const data = await response.json();
          setPositions(data.positions || []);
        }
      } catch (err) {
        logger.error('Failed to fetch positions:', err);
        setPositions([]);
      } finally {
        setPositionsLoading(false);
      }
    },
    [apiBase],
  );

  // Fetch positions when agent selection changes
  useEffect(() => {
    if (selectedAgent !== ALL_AGENTS_TAB) {
      fetchPositions(selectedAgent);
    } else {
      setPositions([]);
      setShowPositions(false);
    }
  }, [selectedAgent, fetchPositions]);

  // Extract agent data from events, including status tracking
  const agentData = useMemo(() => {
    const agents: Record<string, AgentData> = {};
    const streamingAgents = new Set<string>();
    const failedAgents = new Set<string>();
    const rateLimitedAgents = new Set<string>();
    const now = Date.now() / 1000;

    // First pass: track streaming and error states
    events.forEach((event) => {
      const agentName = event.agent;
      if (!agentName) return;

      if (event.type === 'token_start' || event.type === 'token_delta') {
        streamingAgents.add(agentName);
      } else if (event.type === 'token_end') {
        streamingAgents.delete(agentName);
      } else if (event.type === 'error') {
        const errorData = event.data as Record<string, unknown>;
        const errorMsg = String(errorData.error || errorData.message || '').toLowerCase();
        if (errorMsg.includes('rate') || errorMsg.includes('429') || errorMsg.includes('quota')) {
          rateLimitedAgents.add(agentName);
        } else {
          failedAgents.add(agentName);
        }
      }
    });

    // Second pass: extract agent messages
    events.filter(isAgentMessage).forEach((event) => {
      if (!event.agent) return;

      const agentName = event.agent;
      const content = event.data.content || '';
      const role = event.data.role || 'proposer';
      const cognitiveRole = event.data.cognitive_role;
      const round = event.round || 0;
      const confidence = event.data.confidence;
      const citations = event.data.citations;

      if (!agents[agentName]) {
        agents[agentName] = {
          name: agentName,
          latestContent: content,
          role,
          cognitiveRole,
          round,
          confidence,
          citations,
          timestamp: event.timestamp,
          status: 'idle',
          lastActivity: event.timestamp,
          allMessages: [],
        };
      }

      agents[agentName].allMessages.push({ content, round, role, timestamp: event.timestamp });

      // Update to latest message
      if (event.timestamp >= agents[agentName].timestamp) {
        agents[agentName].latestContent = content;
        agents[agentName].role = role;
        agents[agentName].cognitiveRole = cognitiveRole;
        agents[agentName].round = round;
        agents[agentName].confidence = confidence;
        agents[agentName].citations = citations;
        agents[agentName].timestamp = event.timestamp;
        agents[agentName].lastActivity = event.timestamp;
      }
    });

    // Determine final status for each agent
    Object.values(agents).forEach((agent) => {
      if (failedAgents.has(agent.name)) {
        agent.status = 'failed';
      } else if (rateLimitedAgents.has(agent.name)) {
        agent.status = 'rate_limited';
      } else if (streamingAgents.has(agent.name)) {
        agent.status = 'thinking';
      } else if (now - agent.lastActivity < 5) {
        // Consider active if responded within last 5 seconds
        agent.status = 'active';
      } else {
        agent.status = 'idle';
      }
    });

    return Object.values(agents).sort((a, b) => a.name.localeCompare(b.name));
  }, [events]);

  // Extract unified timeline of all agent messages
  const unifiedTimeline = useMemo(() => {
    return events
      .filter(isAgentMessage)
      .filter((e) => e.agent)
      .map((e) => ({
        agent: e.agent || '',
        content: e.data.content || '',
        role: e.data.role || 'proposer',
        cognitiveRole: e.data.cognitive_role,
        round: e.round || 0,
        timestamp: e.timestamp,
      }))
      .sort((a, b) => a.timestamp - b.timestamp);
  }, [events]);

  // Auto-scroll when new messages arrive in unified view
  useEffect(() => {
    if (autoScroll && scrollRef.current && selectedAgent === ALL_AGENTS_TAB) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [unifiedTimeline.length, autoScroll, selectedAgent]);

  const handleScroll = () => {
    if (scrollRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
      const isAtBottom = scrollHeight - scrollTop - clientHeight < 50;
      setAutoScroll(isAtBottom);
    }
  };

  const activeAgent = selectedAgent;
  const currentAgent =
    selectedAgent !== ALL_AGENTS_TAB ? agentData.find((a) => a.name === activeAgent) : null;

  if (agentData.length === 0) {
    return (
      <div className="card flex flex-col h-full">
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h2 className="text-sm font-medium text-text-muted uppercase tracking-wider">
            Agent Responses
          </h2>
        </div>
        <div className="flex-1 flex items-center justify-center text-text-muted">
          Waiting for agent responses...
        </div>
      </div>
    );
  }

  return (
    <div className="card flex flex-col h-full">
      {/* Tab Bar */}
      <div className="flex items-center border-b border-border overflow-x-auto">
        {/* All Agents Tab (default) */}
        <button
          onClick={() => setSelectedAgent(ALL_AGENTS_TAB)}
          className={`
            relative px-4 py-3 text-sm font-medium whitespace-nowrap transition-all
            ${activeAgent === ALL_AGENTS_TAB ? 'text-[var(--accent)]' : 'text-text-muted hover:text-text'}
          `}
        >
          <span className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[var(--accent)]" />
            All Agents
            <span className="text-xs opacity-60">{unifiedTimeline.length}</span>
          </span>
          {activeAgent === ALL_AGENTS_TAB && (
            <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-[var(--accent)]" />
          )}
        </button>
        {/* Individual Agent Tabs */}
        {agentData.map((agent) => {
          const colors = getAgentColors(agent.name);
          const isActive = agent.name === activeAgent;

          return (
            <button
              key={agent.name}
              onClick={() => setSelectedAgent(agent.name)}
              className={`
                relative px-4 py-3 text-sm font-medium whitespace-nowrap transition-all
                ${isActive ? colors.text : 'text-text-muted hover:text-text'}
              `}
            >
              <span className="flex items-center gap-2">
                <StatusBadge status={agent.status} compact />
                {agent.name}
                {agent.round > 0 && <span className="text-xs opacity-60">R{agent.round}</span>}
              </span>
              {isActive && (
                <span className={`absolute bottom-0 left-0 right-0 h-0.5 ${colors.tab}`} />
              )}
            </button>
          );
        })}
      </div>

      {/* Content Area - Unified Timeline View */}
      {activeAgent === ALL_AGENTS_TAB && (
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Unified Header */}
          <div className="p-4 border-b border-border flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="text-sm text-text-muted">
                Activity Timeline • {unifiedTimeline.length} messages from {agentData.length} agents
              </span>
            </div>
            <div className="flex items-center gap-2 text-xs text-text-muted">
              {autoScroll ? (
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-[var(--accent)] animate-pulse" />
                  Live
                </span>
              ) : (
                <button
                  onClick={() => {
                    setAutoScroll(true);
                    if (scrollRef.current) {
                      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
                    }
                  }}
                  className="px-2 py-1 bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/30 hover:bg-[var(--accent)]/30"
                >
                  ↓ Jump to Latest
                </button>
              )}
            </div>
          </div>

          {/* Unified Timeline */}
          <div
            ref={scrollRef}
            onScroll={handleScroll}
            className="flex-1 overflow-y-auto p-4 space-y-3"
          >
            {unifiedTimeline.length === 0 ? (
              <div className="text-center text-text-muted py-8">Waiting for agent responses...</div>
            ) : (
              unifiedTimeline.map((msg, idx) => {
                const colors = getAgentColors(msg.agent);
                const roleIcon = ROLE_ICONS[msg.role] || ROLE_ICONS.default;
                return (
                  <div key={idx} className={`${colors.bg} border ${colors.border} p-3 rounded`}>
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-sm">{roleIcon}</span>
                      <span className={`font-medium text-sm ${colors.text}`}>{msg.agent}</span>
                      <RoleBadge role={msg.role} cognitiveRole={msg.cognitiveRole} />
                      {msg.round > 0 && (
                        <span className="px-1.5 py-0.5 text-xs bg-surface rounded border border-border">
                          R{msg.round}
                        </span>
                      )}
                      <span className="text-xs text-text-muted ml-auto">
                        {new Date(msg.timestamp * 1000).toLocaleTimeString()}
                      </span>
                    </div>
                    <div className="agent-output text-sm whitespace-pre-wrap break-words">
                      {msg.content}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}

      {/* Content Area - Individual Agent View */}
      {currentAgent && (
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Agent Header */}
          <div className="p-4 border-b border-border flex items-center justify-between">
            <div className="flex items-center gap-3">
              <StatusBadge status={currentAgent.status} />
              <RoleBadge role={currentAgent.role} cognitiveRole={currentAgent.cognitiveRole} />
              {currentAgent.round > 0 && (
                <span className="px-2 py-0.5 text-xs bg-surface rounded border border-border">
                  Round {currentAgent.round}
                </span>
              )}
            </div>
            <div className="flex items-center gap-3">
              {currentAgent.confidence !== undefined && (
                <span className="text-sm">
                  <span className="text-text-muted">Confidence:</span>{' '}
                  <span
                    className={`font-theme-data font-medium ${
                      currentAgent.confidence >= 0.8
                        ? 'text-green-400'
                        : currentAgent.confidence >= 0.6
                          ? 'text-yellow-400'
                          : 'text-red-400'
                    }`}
                  >
                    {Math.round(currentAgent.confidence * 100)}%
                  </span>
                </span>
              )}
              {currentAgent.citations && currentAgent.citations.length > 0 && (
                <span className="text-sm text-text-muted">
                  Citations: {currentAgent.citations.length}
                </span>
              )}
              <button
                onClick={() => {
                  setShowPositions(!showPositions);
                  if (!showPositions) setShowHistory(false);
                }}
                className={`px-2 py-1 text-xs rounded border transition-colors ${
                  showPositions
                    ? 'bg-purple-500 text-white border-purple-500'
                    : 'bg-surface text-text-muted border-border hover:text-text'
                }`}
              >
                Positions {positions.length > 0 && `(${positions.length})`}
              </button>
              <button
                onClick={() => {
                  setShowHistory(!showHistory);
                  if (!showHistory) setShowPositions(false);
                }}
                className={`px-2 py-1 text-xs rounded border transition-colors ${
                  showHistory
                    ? 'bg-accent text-white border-accent'
                    : 'bg-surface text-text-muted border-border hover:text-text'
                }`}
              >
                {showHistory ? 'Latest' : 'History'}
              </button>
            </div>
          </div>

          {/* Response Content */}
          <div className="flex-1 overflow-y-auto p-4">
            {showPositions ? (
              <div className="space-y-3">
                {positionsLoading ? (
                  <div className="text-center text-text-muted py-4">Loading positions...</div>
                ) : positions.length === 0 ? (
                  <div className="text-center text-text-muted py-4">
                    No recorded positions for this agent.
                  </div>
                ) : (
                  positions.map((pos, idx) => (
                    <div
                      key={idx}
                      className="p-3 bg-surface border border-border rounded-lg hover:border-purple-500/30 transition-colors"
                    >
                      <div className="flex items-center justify-between mb-2">
                        <span className="font-medium text-text text-sm">{pos.topic}</span>
                        <div className="flex items-center gap-2 text-xs">
                          <span
                            className={`px-2 py-0.5 rounded ${
                              pos.confidence >= 0.8
                                ? 'bg-green-500/20 text-green-400'
                                : pos.confidence >= 0.5
                                  ? 'bg-yellow-500/20 text-yellow-400'
                                  : 'bg-red-500/20 text-red-400'
                            }`}
                          >
                            {Math.round(pos.confidence * 100)}% conf
                          </span>
                          {pos.evidence_count > 0 && (
                            <span className="text-text-muted">{pos.evidence_count} evidence</span>
                          )}
                        </div>
                      </div>
                      <p className="text-sm text-text-muted">{pos.position}</p>
                      <div className="text-xs text-text-muted mt-2">
                        Updated: {new Date(pos.last_updated).toLocaleDateString()}
                      </div>
                    </div>
                  ))
                )}
              </div>
            ) : showHistory ? (
              <div className="space-y-4">
                {currentAgent.allMessages
                  .sort((a, b) => b.timestamp - a.timestamp)
                  .map((msg, idx) => (
                    <div key={idx} className="border-l-2 border-border pl-4">
                      <div className="flex items-center gap-2 mb-2 text-xs text-text-muted">
                        <span>Round {msg.round}</span>
                        <span>•</span>
                        <span>{new Date(msg.timestamp * 1000).toLocaleTimeString()}</span>
                      </div>
                      <div className="agent-output whitespace-pre-wrap break-words">
                        {msg.content}
                      </div>
                    </div>
                  ))}
              </div>
            ) : (
              <div className="agent-output whitespace-pre-wrap break-words">
                {currentAgent.latestContent}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
