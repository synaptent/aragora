'use client';

import React, { useState, useEffect, useRef } from 'react';
import { getClient, EvidenceSnippet, EvidenceStatistics } from '@/lib/aragora-client';
import { logger } from '@/utils/logger';

type TabId = 'search' | 'collect' | 'browse';

interface Tab {
  id: TabId;
  label: string;
  description: string;
}

const tabs: Tab[] = [
  { id: 'search', label: 'Search', description: 'Search collected evidence' },
  { id: 'collect', label: 'Collect', description: 'Gather new evidence' },
  { id: 'browse', label: 'Browse', description: 'View all evidence' },
];

export default function EvidencePage() {
  const [activeTab, setActiveTab] = useState<TabId>('search');
  const [stats, setStats] = useState<EvidenceStatistics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<EvidenceSnippet[]>([]);
  const [searchMinReliability, setSearchMinReliability] = useState(0.5);

  // Collect state
  const [collectTask, setCollectTask] = useState('');
  const [collectDebateId, setCollectDebateId] = useState('');
  const [collectResults, setCollectResults] = useState<EvidenceSnippet[]>([]);
  const [collectKeywords, setCollectKeywords] = useState<string[]>([]);
  const [collecting, setCollecting] = useState(false);

  // Browse state
  const [evidenceList, setEvidenceList] = useState<EvidenceSnippet[]>([]);
  const [totalEvidence, setTotalEvidence] = useState(0);
  const [browseOffset, setBrowseOffset] = useState(0);
  const browseLimit = 20;
  const hasLoadedBrowse = useRef(false);

  // Load stats on mount
  useEffect(() => {
    loadStats();
  }, []);

  const loadStats = async () => {
    try {
      const client = getClient();
      const response = await client.evidence.statistics();
      setStats(response.statistics);
    } catch (err) {
      logger.error('Failed to load evidence stats:', err);
    }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) {
      setError('Please enter a search query');
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const client = getClient();
      const response = await client.evidence.search({
        query: searchQuery,
        limit: 50,
        min_reliability: searchMinReliability,
      });
      setSearchResults(response.results);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Search failed');
    } finally {
      setLoading(false);
    }
  };

  const handleCollect = async () => {
    if (!collectTask.trim()) {
      setError('Please enter a topic to collect evidence for');
      return;
    }

    setCollecting(true);
    setError(null);
    setCollectResults([]);
    setCollectKeywords([]);

    try {
      const client = getClient();
      const response = await client.evidence.collect({
        task: collectTask,
        debate_id: collectDebateId || undefined,
      });
      setCollectResults(response.snippets);
      setCollectKeywords(response.keywords);
      // Refresh stats after collection
      loadStats();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Evidence collection failed');
    } finally {
      setCollecting(false);
    }
  };

  const loadEvidenceList = async (offset = 0) => {
    setLoading(true);
    setError(null);
    try {
      const client = getClient();
      const response = await client.evidence.list({ limit: browseLimit, offset });
      setEvidenceList(response.evidence);
      setTotalEvidence(response.total);
      setBrowseOffset(offset);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load evidence');
    } finally {
      setLoading(false);
    }
  };

  // Load evidence list when switching to browse tab
  useEffect(() => {
    if (activeTab === 'browse' && !hasLoadedBrowse.current) {
      hasLoadedBrowse.current = true;
      loadEvidenceList(0);
    }
  }, [activeTab]);

  const handleDeleteEvidence = async (id: string) => {
    if (!confirm('Are you sure you want to delete this evidence?')) return;

    try {
      const client = getClient();
      await client.evidence.delete(id);
      // Remove from local state
      setEvidenceList((prev) => prev.filter((e) => e.id !== id));
      setSearchResults((prev) => prev.filter((e) => e.id !== id));
      setCollectResults((prev) => prev.filter((e) => e.id !== id));
      loadStats();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete evidence');
    }
  };

  const renderStats = () => (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <div className="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-sm border border-gray-200 dark:border-gray-700">
        <div className="text-2xl font-bold text-blue-600 dark:text-blue-400">
          {stats?.total_evidence ?? '-'}
        </div>
        <div className="text-sm text-gray-600 dark:text-gray-400">Total Evidence</div>
      </div>
      <div className="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-sm border border-gray-200 dark:border-gray-700">
        <div className="text-2xl font-bold text-green-600 dark:text-green-400">
          {stats?.average_reliability ? (stats.average_reliability * 100).toFixed(0) + '%' : '-'}
        </div>
        <div className="text-sm text-gray-600 dark:text-gray-400">Avg Reliability</div>
      </div>
      <div className="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-sm border border-gray-200 dark:border-gray-700">
        <div className="text-2xl font-bold text-purple-600 dark:text-purple-400">
          {stats?.by_source ? Object.keys(stats.by_source).length : '-'}
        </div>
        <div className="text-sm text-gray-600 dark:text-gray-400">Sources</div>
      </div>
      <div className="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-sm border border-gray-200 dark:border-gray-700">
        <div className="text-2xl font-bold text-amber-600 dark:text-amber-400">
          {stats?.average_quality ? (stats.average_quality * 100).toFixed(0) + '%' : '-'}
        </div>
        <div className="text-sm text-gray-600 dark:text-gray-400">Avg Quality</div>
      </div>
    </div>
  );

  const renderEvidenceCard = (evidence: EvidenceSnippet, showDelete = true) => (
    <div
      key={evidence.id}
      className="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-sm border border-gray-200 dark:border-gray-700"
    >
      <div className="flex items-start justify-between mb-2">
        <div className="flex-1">
          <h3 className="font-medium text-gray-900 dark:text-gray-100 line-clamp-2">
            {evidence.title}
          </h3>
          <div className="flex items-center gap-2 mt-1 text-sm text-gray-500 dark:text-gray-400">
            <span className="px-2 py-0.5 bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 rounded text-xs">
              {evidence.source}
            </span>
            <span>Reliability: {(evidence.reliability_score * 100).toFixed(0)}%</span>
            {evidence.freshness_score !== undefined && (
              <span>Freshness: {(evidence.freshness_score * 100).toFixed(0)}%</span>
            )}
          </div>
        </div>
        {showDelete && (
          <button
            onClick={() => handleDeleteEvidence(evidence.id)}
            className="text-red-500 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300 ml-2"
            title="Delete evidence"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
              />
            </svg>
          </button>
        )}
      </div>
      <p className="text-sm text-gray-700 dark:text-gray-300 line-clamp-3 mb-2">
        {evidence.snippet}
      </p>
      {evidence.url && (
        <a
          href={evidence.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm text-blue-600 dark:text-blue-400 hover:underline truncate block"
        >
          {evidence.url}
        </a>
      )}
    </div>
  );

  const renderSearchTab = () => (
    <div>
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
          Search Query
        </label>
        <div className="flex gap-2">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            placeholder="Enter search terms..."
            className="flex-1 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
          />
          <button
            onClick={handleSearch}
            disabled={loading}
            className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? 'Searching...' : 'Search'}
          </button>
        </div>
      </div>

      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
          Minimum Reliability: {(searchMinReliability * 100).toFixed(0)}%
        </label>
        <input
          type="range"
          min="0"
          max="1"
          step="0.1"
          value={searchMinReliability}
          onChange={(e) => setSearchMinReliability(parseFloat(e.target.value))}
          className="w-full"
        />
      </div>

      {searchResults.length > 0 && (
        <div className="space-y-4">
          <h3 className="text-lg font-medium text-gray-900 dark:text-gray-100">
            {searchResults.length} Results
          </h3>
          {searchResults.map((evidence) => renderEvidenceCard(evidence))}
        </div>
      )}
    </div>
  );

  const renderCollectTab = () => (
    <div>
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
          Topic / Task
        </label>
        <textarea
          value={collectTask}
          onChange={(e) => setCollectTask(e.target.value)}
          placeholder="Describe the topic to collect evidence for..."
          rows={3}
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
        />
      </div>

      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
          Associate with Debate (optional)
        </label>
        <input
          type="text"
          value={collectDebateId}
          onChange={(e) => setCollectDebateId(e.target.value)}
          placeholder="Debate ID..."
          className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
        />
      </div>

      <button
        onClick={handleCollect}
        disabled={collecting || !collectTask.trim()}
        className="w-full px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:opacity-50"
      >
        {collecting ? 'Collecting Evidence...' : 'Collect Evidence'}
      </button>

      {collectKeywords.length > 0 && (
        <div className="mt-4 p-3 bg-blue-50 dark:bg-blue-900/20 rounded-md">
          <h4 className="text-sm font-medium text-blue-800 dark:text-blue-300 mb-2">
            Extracted Keywords
          </h4>
          <div className="flex flex-wrap gap-2">
            {collectKeywords.map((keyword, idx) => (
              <span
                key={idx}
                className="px-2 py-1 bg-blue-100 dark:bg-blue-800 text-blue-700 dark:text-blue-200 rounded text-sm"
              >
                {keyword}
              </span>
            ))}
          </div>
        </div>
      )}

      {collectResults.length > 0 && (
        <div className="mt-6 space-y-4">
          <h3 className="text-lg font-medium text-gray-900 dark:text-gray-100">
            Collected {collectResults.length} Evidence Items
          </h3>
          {collectResults.map((evidence) => renderEvidenceCard(evidence, false))}
        </div>
      )}
    </div>
  );

  const renderBrowseTab = () => (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-medium text-gray-900 dark:text-gray-100">
          All Evidence ({totalEvidence})
        </h3>
        <button
          onClick={() => loadEvidenceList(browseOffset)}
          disabled={loading}
          className="px-3 py-1 text-sm text-blue-600 dark:text-blue-400 hover:underline"
        >
          Refresh
        </button>
      </div>

      {loading ? (
        <div className="text-center py-8 text-gray-500">Loading...</div>
      ) : evidenceList.length === 0 ? (
        <div className="text-center py-8 text-gray-500">No evidence collected yet</div>
      ) : (
        <>
          <div className="space-y-4">
            {evidenceList.map((evidence) => renderEvidenceCard(evidence))}
          </div>

          {/* Pagination */}
          <div className="flex justify-center gap-4 mt-6">
            <button
              onClick={() => loadEvidenceList(Math.max(0, browseOffset - browseLimit))}
              disabled={browseOffset === 0 || loading}
              className="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-md hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50"
            >
              Previous
            </button>
            <span className="py-2 text-gray-600 dark:text-gray-400">
              {browseOffset + 1} - {Math.min(browseOffset + browseLimit, totalEvidence)} of{' '}
              {totalEvidence}
            </span>
            <button
              onClick={() => loadEvidenceList(browseOffset + browseLimit)}
              disabled={browseOffset + browseLimit >= totalEvidence || loading}
              className="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-md hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </>
      )}
    </div>
  );

  return (
    <div className="max-w-6xl mx-auto p-6">
      <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100 mb-2">
        Evidence Collection
      </h1>
      <p className="text-gray-600 dark:text-gray-400 mb-6">
        Search, collect, and manage evidence for AI debates
      </p>

      {renderStats()}

      {error && (
        <div className="mb-4 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md text-red-800 dark:text-red-300">
          {error}
        </div>
      )}

      {/* Tabs */}
      <div className="border-b border-gray-200 dark:border-gray-700 mb-6">
        <nav className="flex gap-4">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`pb-2 px-1 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.id
                  ? 'border-blue-600 text-blue-600 dark:border-blue-400 dark:text-blue-400'
                  : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab Content */}
      <div className="min-h-[400px]">
        {activeTab === 'search' && renderSearchTab()}
        {activeTab === 'collect' && renderCollectTab()}
        {activeTab === 'browse' && renderBrowseTab()}
      </div>
    </div>
  );
}
