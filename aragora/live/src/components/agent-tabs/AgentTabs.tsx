'use client';

import { useState, useMemo, useRef, useEffect, useCallback } from 'react';
import { isAgentMessage } from '@/types/events';
import { getAgentColors } from '@/utils/agentColors';
import { AllAgentsTab } from './AllAgentsTab';
import { IndividualAgentTab } from './IndividualAgentTab';
import type {
  AgentTabsProps,
  AgentData,
  TimelineMessage,
  PositionEntry,
  MatchHistoryEntry,
} from './types';
import { ALL_AGENTS_TAB } from './types';
import { logger } from '@/utils/logger';
import { API_BASE_URL } from '@/config';

const DEFAULT_API_BASE = API_BASE_URL;

export function AgentTabs({ events, apiBase = DEFAULT_API_BASE }: AgentTabsProps) {
  const [selectedAgent, setSelectedAgent] = useState<string>(ALL_AGENTS_TAB);
  const [showHistory, setShowHistory] = useState(false);
  const [showPositions, setShowPositions] = useState(false);
  const [showMatchHistory, setShowMatchHistory] = useState(false);
  const [positions, setPositions] = useState<PositionEntry[]>([]);
  const [positionsLoading, setPositionsLoading] = useState(false);
  const [matchHistory, setMatchHistory] = useState<MatchHistoryEntry[]>([]);
  const [matchHistoryLoading, setMatchHistoryLoading] = useState(false);
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

  // Fetch match history when viewing individual agent
  const fetchMatchHistory = useCallback(
    async (agentName: string) => {
      setMatchHistoryLoading(true);
      try {
        const response = await fetch(
          `${apiBase}/api/agent/${encodeURIComponent(agentName)}/history?limit=50`,
        );
        if (response.ok) {
          const data = await response.json();
          setMatchHistory(data.history || []);
        }
      } catch (err) {
        logger.error('Failed to fetch match history:', err);
        setMatchHistory([]);
      } finally {
        setMatchHistoryLoading(false);
      }
    },
    [apiBase],
  );

  // Fetch positions and match history when agent selection changes
  useEffect(() => {
    if (selectedAgent !== ALL_AGENTS_TAB) {
      fetchPositions(selectedAgent);
      fetchMatchHistory(selectedAgent);
    } else {
      setPositions([]);
      setMatchHistory([]);
      setShowPositions(false);
      setShowMatchHistory(false);
    }
  }, [selectedAgent, fetchPositions, fetchMatchHistory]);

  // Extract agent data from events
  const agentData = useMemo<AgentData[]>(() => {
    const agents: Record<string, AgentData> = {};

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
      }
    });

    return Object.values(agents).sort((a, b) => a.name.localeCompare(b.name));
  }, [events]);

  // Extract unified timeline of all agent messages
  const unifiedTimeline = useMemo<TimelineMessage[]>(() => {
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

  const handleScroll = useCallback(() => {
    if (scrollRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
      const isAtBottom = scrollHeight - scrollTop - clientHeight < 50;
      setAutoScroll(isAtBottom);
    }
  }, []);

  const handleJumpToLatest = useCallback(() => {
    setAutoScroll(true);
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, []);

  const handleToggleHistory = useCallback(() => {
    setShowHistory((prev) => !prev);
    setShowPositions(false);
    setShowMatchHistory(false);
  }, []);

  const handleTogglePositions = useCallback(() => {
    setShowPositions((prev) => !prev);
    setShowHistory(false);
    setShowMatchHistory(false);
  }, []);

  const handleToggleMatchHistory = useCallback(() => {
    setShowMatchHistory((prev) => !prev);
    setShowHistory(false);
    setShowPositions(false);
  }, []);

  const currentAgent =
    selectedAgent !== ALL_AGENTS_TAB ? agentData.find((a) => a.name === selectedAgent) : null;

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
            ${selectedAgent === ALL_AGENTS_TAB ? 'text-[var(--accent)]' : 'text-text-muted hover:text-text'}
          `}
        >
          <span className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[var(--accent)]" />
            All Agents
            <span className="text-xs opacity-60">{unifiedTimeline.length}</span>
          </span>
          {selectedAgent === ALL_AGENTS_TAB && (
            <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-[var(--accent)]" />
          )}
        </button>

        {/* Individual Agent Tabs */}
        {agentData.map((agent) => {
          const colors = getAgentColors(agent.name);
          const isActive = agent.name === selectedAgent;

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
                <span className={`w-2 h-2 rounded-full ${colors.tab}`} />
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

      {/* Content Area */}
      {selectedAgent === ALL_AGENTS_TAB && (
        <AllAgentsTab
          unifiedTimeline={unifiedTimeline}
          agentData={agentData}
          autoScroll={autoScroll}
          scrollRef={scrollRef}
          onScroll={handleScroll}
          onJumpToLatest={handleJumpToLatest}
        />
      )}

      {currentAgent && (
        <IndividualAgentTab
          currentAgent={currentAgent}
          positions={positions}
          positionsLoading={positionsLoading}
          matchHistory={matchHistory}
          matchHistoryLoading={matchHistoryLoading}
          showHistory={showHistory}
          showPositions={showPositions}
          showMatchHistory={showMatchHistory}
          onToggleHistory={handleToggleHistory}
          onTogglePositions={handleTogglePositions}
          onToggleMatchHistory={handleToggleMatchHistory}
          apiBase={apiBase}
        />
      )}
    </div>
  );
}
