/**
 * PublicGallery.tsx - Browse and share public debates
 *
 * Displays public debates from the gallery with filtering, search,
 * and embed/share functionality. Part of Phase 12 GA preparation.
 */

'use client';

import { useState, useEffect, useCallback } from 'react';
import { useAragoraClient } from '@/hooks/useAragoraClient';
import { GalleryEntry } from '@/lib/aragora-client';
import { sanitizeHtml } from '@/utils/sanitize';

type FilterMode = 'all' | 'featured' | 'consensus' | 'no-consensus';

export function PublicGallery() {
  const client = useAragoraClient();
  const [entries, setEntries] = useState<GalleryEntry[]>([]);
  const [filteredEntries, setFilteredEntries] = useState<GalleryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterMode, setFilterMode] = useState<FilterMode>('all');
  const [selectedEntry, setSelectedEntry] = useState<GalleryEntry | null>(null);
  const [embedData, setEmbedData] = useState<{ embed_url: string; embed_html: string } | null>(
    null,
  );
  const [showEmbedModal, setShowEmbedModal] = useState(false);
  const [copiedField, setCopiedField] = useState<string | null>(null);

  // Load gallery entries
  const loadEntries = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await client.gallery.list({ limit: 100 });
      setEntries(response.entries);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load gallery');
    } finally {
      setLoading(false);
    }
  }, [client.gallery]);

  useEffect(() => {
    loadEntries();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Filter entries based on search and filter mode
  useEffect(() => {
    let filtered = entries;

    // Apply search filter
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(
        (entry) =>
          entry.title.toLowerCase().includes(query) ||
          entry.summary.toLowerCase().includes(query) ||
          entry.agents.some((agent) => agent.toLowerCase().includes(query)),
      );
    }

    // Apply filter mode
    switch (filterMode) {
      case 'featured':
        filtered = filtered.filter((entry) => entry.featured);
        break;
      case 'consensus':
        filtered = filtered.filter((entry) => entry.consensus_reached);
        break;
      case 'no-consensus':
        filtered = filtered.filter((entry) => !entry.consensus_reached);
        break;
    }

    setFilteredEntries(filtered);
  }, [entries, searchQuery, filterMode]);

  // Get embed data for a debate
  const getEmbedData = async (entry: GalleryEntry) => {
    setSelectedEntry(entry);
    setEmbedData(null);
    setShowEmbedModal(true);
    try {
      const response = await client.gallery.embed(entry.id);
      setEmbedData(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to get embed code');
    }
  };

  // Copy to clipboard
  const copyToClipboard = async (text: string, field: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedField(field);
      setTimeout(() => setCopiedField(null), 2000);
    } catch {
      setError('Failed to copy to clipboard');
    }
  };

  // Format date for display
  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
  };

  // Format view count
  const formatViews = (views?: number) => {
    if (views === undefined || views === null) return '0';
    if (views >= 1000000) return `${(views / 1000000).toFixed(1)}M`;
    if (views >= 1000) return `${(views / 1000).toFixed(1)}K`;
    return views.toString();
  };

  return (
    <div className="public-gallery">
      <style>{`
        .public-gallery {
          font-family: system-ui, -apple-system, sans-serif;
          max-width: 1200px;
          margin: 0 auto;
          padding: 24px;
        }

        .gallery-header {
          margin-bottom: 24px;
        }

        .gallery-header h1 {
          font-size: 28px;
          font-weight: 600;
          margin: 0 0 8px 0;
          color: #1a1a2e;
        }

        .gallery-header p {
          color: #666;
          margin: 0;
        }

        .gallery-controls {
          display: flex;
          gap: 16px;
          margin-bottom: 24px;
          flex-wrap: wrap;
        }

        .search-input {
          flex: 1;
          min-width: 200px;
          padding: 10px 14px;
          border: 1px solid #ddd;
          border-radius: 8px;
          font-size: 14px;
        }

        .search-input:focus {
          outline: none;
          border-color: #4f46e5;
          box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1);
        }

        .filter-buttons {
          display: flex;
          gap: 8px;
        }

        .filter-btn {
          padding: 10px 16px;
          border: 1px solid #ddd;
          border-radius: 8px;
          background: white;
          font-size: 14px;
          cursor: pointer;
          transition: all 0.2s;
        }

        .filter-btn:hover {
          border-color: #4f46e5;
        }

        .filter-btn.active {
          background: #4f46e5;
          color: white;
          border-color: #4f46e5;
        }

        .gallery-stats {
          display: flex;
          gap: 24px;
          margin-bottom: 24px;
          padding: 16px;
          background: #f8f9fa;
          border-radius: 12px;
        }

        .stat-item {
          text-align: center;
        }

        .stat-value {
          font-size: 24px;
          font-weight: 600;
          color: #1a1a2e;
        }

        .stat-label {
          font-size: 12px;
          color: #666;
          text-transform: uppercase;
        }

        .gallery-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
          gap: 20px;
        }

        .debate-card {
          background: white;
          border: 1px solid #e5e7eb;
          border-radius: 12px;
          overflow: hidden;
          transition: all 0.2s;
        }

        .debate-card:hover {
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
          transform: translateY(-2px);
        }

        .debate-card.featured {
          border-color: #fbbf24;
          box-shadow: 0 0 0 1px #fbbf24;
        }

        .card-header {
          padding: 16px;
          border-bottom: 1px solid #f3f4f6;
        }

        .card-title {
          font-size: 16px;
          font-weight: 600;
          margin: 0 0 8px 0;
          color: #1a1a2e;
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .featured-badge {
          background: #fef3c7;
          color: #92400e;
          padding: 2px 8px;
          border-radius: 4px;
          font-size: 11px;
          font-weight: 500;
        }

        .card-meta {
          display: flex;
          gap: 16px;
          font-size: 13px;
          color: #666;
        }

        .card-body {
          padding: 16px;
        }

        .card-summary {
          font-size: 14px;
          color: #444;
          line-height: 1.5;
          margin-bottom: 12px;
          display: -webkit-box;
          -webkit-line-clamp: 3;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }

        .agent-list {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
          margin-bottom: 12px;
        }

        .agent-tag {
          background: #e0e7ff;
          color: #3730a3;
          padding: 4px 10px;
          border-radius: 16px;
          font-size: 12px;
          font-weight: 500;
        }

        .consensus-badge {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          padding: 4px 10px;
          border-radius: 16px;
          font-size: 12px;
          font-weight: 500;
        }

        .consensus-badge.reached {
          background: #d1fae5;
          color: #065f46;
        }

        .consensus-badge.not-reached {
          background: #fef3c7;
          color: #92400e;
        }

        .card-footer {
          padding: 12px 16px;
          border-top: 1px solid #f3f4f6;
          display: flex;
          justify-content: space-between;
          align-items: center;
        }

        .view-count {
          font-size: 13px;
          color: #666;
        }

        .card-actions {
          display: flex;
          gap: 8px;
        }

        .action-btn {
          padding: 6px 12px;
          border: 1px solid #ddd;
          border-radius: 6px;
          background: white;
          font-size: 13px;
          cursor: pointer;
          transition: all 0.2s;
        }

        .action-btn:hover {
          border-color: #4f46e5;
          color: #4f46e5;
        }

        .action-btn.primary {
          background: #4f46e5;
          color: white;
          border-color: #4f46e5;
        }

        .action-btn.primary:hover {
          background: #4338ca;
        }

        .loading-state, .error-state, .empty-state {
          text-align: center;
          padding: 48px 24px;
          color: #666;
        }

        .error-state {
          color: #dc2626;
        }

        .retry-btn {
          margin-top: 16px;
          padding: 10px 20px;
          background: #4f46e5;
          color: white;
          border: none;
          border-radius: 8px;
          cursor: pointer;
        }

        /* Modal styles */
        .modal-overlay {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0, 0, 0, 0.5);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
        }

        .modal-content {
          background: white;
          border-radius: 12px;
          max-width: 600px;
          width: 90%;
          max-height: 90vh;
          overflow-y: auto;
        }

        .modal-header {
          padding: 20px;
          border-bottom: 1px solid #e5e7eb;
          display: flex;
          justify-content: space-between;
          align-items: center;
        }

        .modal-header h2 {
          margin: 0;
          font-size: 18px;
        }

        .close-btn {
          background: none;
          border: none;
          font-size: 24px;
          cursor: pointer;
          color: #666;
        }

        .modal-body {
          padding: 20px;
        }

        .embed-section {
          margin-bottom: 20px;
        }

        .embed-section label {
          display: block;
          font-size: 14px;
          font-weight: 500;
          margin-bottom: 8px;
          color: #374151;
        }

        .embed-input-group {
          display: flex;
          gap: 8px;
        }

        .embed-input {
          flex: 1;
          padding: 10px 12px;
          border: 1px solid #ddd;
          border-radius: 6px;
          font-family: monospace;
          font-size: 13px;
          background: #f9fafb;
        }

        .embed-textarea {
          width: 100%;
          padding: 10px 12px;
          border: 1px solid #ddd;
          border-radius: 6px;
          font-family: monospace;
          font-size: 13px;
          background: #f9fafb;
          resize: vertical;
          min-height: 100px;
        }

        .copy-btn {
          padding: 10px 16px;
          background: #4f46e5;
          color: white;
          border: none;
          border-radius: 6px;
          cursor: pointer;
          white-space: nowrap;
        }

        .copy-btn:hover {
          background: #4338ca;
        }

        .copy-btn.copied {
          background: #059669;
        }

        .embed-preview {
          margin-top: 20px;
          padding: 16px;
          background: #f9fafb;
          border-radius: 8px;
        }

        .embed-preview h3 {
          font-size: 14px;
          margin: 0 0 12px 0;
          color: #374151;
        }

        .preview-frame {
          border: 1px solid #e5e7eb;
          border-radius: 8px;
          overflow: hidden;
        }
      `}</style>

      <div className="gallery-header">
        <h1>Public Debate Gallery</h1>
        <p>Browse and share notable AI debates from the Aragora community</p>
      </div>

      <div className="gallery-controls">
        <input
          type="text"
          className="search-input"
          placeholder="Search debates by title, topic, or agent..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        <div className="filter-buttons">
          <button
            className={`filter-btn ${filterMode === 'all' ? 'active' : ''}`}
            onClick={() => setFilterMode('all')}
          >
            All
          </button>
          <button
            className={`filter-btn ${filterMode === 'featured' ? 'active' : ''}`}
            onClick={() => setFilterMode('featured')}
          >
            Featured
          </button>
          <button
            className={`filter-btn ${filterMode === 'consensus' ? 'active' : ''}`}
            onClick={() => setFilterMode('consensus')}
          >
            Consensus
          </button>
          <button
            className={`filter-btn ${filterMode === 'no-consensus' ? 'active' : ''}`}
            onClick={() => setFilterMode('no-consensus')}
          >
            No Consensus
          </button>
        </div>
      </div>

      {!loading && !error && (
        <div className="gallery-stats">
          <div className="stat-item">
            <div className="stat-value">{entries.length}</div>
            <div className="stat-label">Total Debates</div>
          </div>
          <div className="stat-item">
            <div className="stat-value">{entries.filter((e) => e.featured).length}</div>
            <div className="stat-label">Featured</div>
          </div>
          <div className="stat-item">
            <div className="stat-value">{entries.filter((e) => e.consensus_reached).length}</div>
            <div className="stat-label">Consensus</div>
          </div>
          <div className="stat-item">
            <div className="stat-value">
              {formatViews(entries.reduce((sum, e) => sum + e.views, 0))}
            </div>
            <div className="stat-label">Total Views</div>
          </div>
        </div>
      )}

      {loading && (
        <div className="loading-state">
          <p>Loading gallery...</p>
        </div>
      )}

      {error && (
        <div className="error-state">
          <p>{error}</p>
          <button className="retry-btn" onClick={loadEntries}>
            Retry
          </button>
        </div>
      )}

      {!loading && !error && filteredEntries.length === 0 && (
        <div className="empty-state">
          <p>No debates found matching your criteria.</p>
        </div>
      )}

      {!loading && !error && filteredEntries.length > 0 && (
        <div className="gallery-grid">
          {filteredEntries.map((entry) => (
            <div key={entry.id} className={`debate-card ${entry.featured ? 'featured' : ''}`}>
              <div className="card-header">
                <h3 className="card-title">
                  {entry.title}
                  {entry.featured && <span className="featured-badge">Featured</span>}
                </h3>
                <div className="card-meta">
                  <span>{formatDate(entry.created_at)}</span>
                  <span>{entry.agents.length} agents</span>
                </div>
              </div>
              <div className="card-body">
                <p className="card-summary">{entry.summary}</p>
                <div className="agent-list">
                  {entry.agents.map((agent) => (
                    <span key={agent} className="agent-tag">
                      {agent}
                    </span>
                  ))}
                </div>
                <span
                  className={`consensus-badge ${entry.consensus_reached ? 'reached' : 'not-reached'}`}
                >
                  {entry.consensus_reached ? '✓ Consensus Reached' : '○ No Consensus'}
                </span>
              </div>
              <div className="card-footer">
                <span className="view-count">{formatViews(entry.views)} views</span>
                <div className="card-actions">
                  <button
                    className="action-btn"
                    onClick={() => getEmbedData(entry)}
                    title="Share or embed this debate"
                  >
                    Share
                  </button>
                  <button
                    className="action-btn primary"
                    onClick={() => window.open(`/debate/${entry.debate_id}`, '_blank')}
                    title="View full debate"
                  >
                    View
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Share/Embed Modal */}
      {showEmbedModal && selectedEntry && (
        <div className="modal-overlay" onClick={() => setShowEmbedModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Share Debate</h2>
              <button className="close-btn" onClick={() => setShowEmbedModal(false)}>
                &times;
              </button>
            </div>
            <div className="modal-body">
              <div className="embed-section">
                <label>Direct Link</label>
                <div className="embed-input-group">
                  <input
                    type="text"
                    className="embed-input"
                    value={`${window.location.origin}/debate/${selectedEntry.debate_id}`}
                    readOnly
                  />
                  <button
                    className={`copy-btn ${copiedField === 'link' ? 'copied' : ''}`}
                    onClick={() =>
                      copyToClipboard(
                        `${window.location.origin}/debate/${selectedEntry.debate_id}`,
                        'link',
                      )
                    }
                  >
                    {copiedField === 'link' ? 'Copied!' : 'Copy'}
                  </button>
                </div>
              </div>

              {embedData && (
                <>
                  <div className="embed-section">
                    <label>Embed URL</label>
                    <div className="embed-input-group">
                      <input
                        type="text"
                        className="embed-input"
                        value={embedData.embed_url}
                        readOnly
                      />
                      <button
                        className={`copy-btn ${copiedField === 'embedUrl' ? 'copied' : ''}`}
                        onClick={() => copyToClipboard(embedData.embed_url, 'embedUrl')}
                      >
                        {copiedField === 'embedUrl' ? 'Copied!' : 'Copy'}
                      </button>
                    </div>
                  </div>

                  <div className="embed-section">
                    <label>Embed HTML</label>
                    <textarea className="embed-textarea" value={embedData.embed_html} readOnly />
                    <button
                      className={`copy-btn ${copiedField === 'embedHtml' ? 'copied' : ''}`}
                      onClick={() => copyToClipboard(embedData.embed_html, 'embedHtml')}
                      style={{ marginTop: '8px' }}
                    >
                      {copiedField === 'embedHtml' ? 'Copied!' : 'Copy HTML'}
                    </button>
                  </div>

                  <div className="embed-preview">
                    <h3>Preview</h3>
                    <div
                      className="preview-frame"
                      dangerouslySetInnerHTML={{ __html: sanitizeHtml(embedData.embed_html) }}
                    />
                  </div>
                </>
              )}

              {!embedData && (
                <div className="loading-state">
                  <p>Loading embed data...</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default PublicGallery;
