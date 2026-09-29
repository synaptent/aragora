'use client';

import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL } from '@/config';

interface MarketplaceTemplate {
  id: string;
  name: string;
  description: string;
  author_id: string;
  author_name: string;
  category: string;
  pattern: string;
  tags: string[];
  download_count: number;
  rating: number;
  rating_count: number;
  created_at: number;
  updated_at: number;
  workflow_definition?: { nodes: unknown[]; edges: unknown[] };
}

interface TemplateReview {
  id: string;
  user_name: string;
  rating: number;
  title: string;
  content: string;
  created_at: number;
  helpful_count: number;
}

interface Category {
  id: string;
  name: string;
  template_count: number;
}

interface TemplateMarketplaceProps {
  onImport?: (template: MarketplaceTemplate) => void;
}

const SORT_OPTIONS = [
  { value: 'rating', label: 'Highest Rated' },
  { value: 'downloads', label: 'Most Downloaded' },
  { value: 'newest', label: 'Newest' },
  { value: 'updated', label: 'Recently Updated' },
];

function StarRating({ rating, size = 'sm' }: { rating: number; size?: 'sm' | 'lg' }) {
  const fullStars = Math.floor(rating);
  const hasHalf = rating - fullStars >= 0.5;
  const emptyStars = 5 - fullStars - (hasHalf ? 1 : 0);
  const starSize = size === 'sm' ? 'text-xs' : 'text-lg';

  return (
    <span className={`font-theme-data ${starSize} text-[var(--acid-yellow)]`}>
      {'★'.repeat(fullStars)}
      {hasHalf && '☆'}
      <span className="text-text-muted/30">{'☆'.repeat(emptyStars)}</span>
    </span>
  );
}

export function TemplateMarketplace({ onImport }: TemplateMarketplaceProps) {
  const [templates, setTemplates] = useState<MarketplaceTemplate[]>([]);
  const [featured, setFeatured] = useState<MarketplaceTemplate[]>([]);
  const [trending, setTrending] = useState<MarketplaceTemplate[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState('rating');
  const [selectedTemplate, setSelectedTemplate] = useState<MarketplaceTemplate | null>(null);
  const [, _setTemplateReviews] = useState<TemplateReview[]>([]);
  const [activeTab, setActiveTab] = useState<'browse' | 'featured' | 'trending'>('browse');

  // Rating modal state
  const [showRatingModal, setShowRatingModal] = useState(false);
  const [ratingValue, setRatingValue] = useState(5);
  const [reviewTitle, setReviewTitle] = useState('');
  const [reviewContent, setReviewContent] = useState('');
  const [submittingRating, setSubmittingRating] = useState(false);

  const [importingTemplate, setImportingTemplate] = useState<string | null>(null);

  const fetchTemplates = useCallback(async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (selectedCategory) params.set('category', selectedCategory);
      if (searchQuery) params.set('search', searchQuery);
      if (sortBy) params.set('sort_by', sortBy);

      const response = await fetch(
        `${API_BASE_URL}/api/marketplace/templates?${params.toString()}`,
      );
      if (!response.ok) throw new Error('Failed to fetch templates');

      const data = await response.json();
      setTemplates(data.templates || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch templates');
    } finally {
      setLoading(false);
    }
  }, [selectedCategory, searchQuery, sortBy]);

  const fetchFeatured = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/marketplace/featured`);
      if (response.ok) {
        const data = await response.json();
        setFeatured(data.featured || []);
      }
    } catch {
      // Silently fail for featured
    }
  }, []);

  const fetchTrending = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/marketplace/trending`);
      if (response.ok) {
        const data = await response.json();
        setTrending(data.trending || []);
      }
    } catch {
      // Silently fail for trending
    }
  }, []);

  const fetchCategories = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/marketplace/categories`);
      if (response.ok) {
        const data = await response.json();
        setCategories(data.categories || []);
      }
    } catch {
      // Silently fail for categories
    }
  }, []);

  const fetchTemplateDetails = async (templateId: string) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/marketplace/templates/${templateId}`);
      if (response.ok) {
        const data = await response.json();
        setSelectedTemplate(data);
      }
    } catch {
      // Silently fail
    }
  };

  const handleImportTemplate = async (templateId: string) => {
    setImportingTemplate(templateId);
    try {
      const response = await fetch(
        `${API_BASE_URL}/api/marketplace/templates/${templateId}/import`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include' },
      );

      if (!response.ok) throw new Error('Failed to import template');

      const data = await response.json();
      if (onImport && data.workflow_definition) {
        onImport({ ...selectedTemplate!, workflow_definition: data.workflow_definition });
      }
      alert('Template imported successfully!');
    } catch (err) {
      alert(`Import failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setImportingTemplate(null);
    }
  };

  const handleRateTemplate = async () => {
    if (!selectedTemplate) return;

    setSubmittingRating(true);
    try {
      // Submit rating
      await fetch(`${API_BASE_URL}/api/marketplace/templates/${selectedTemplate.id}/rate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ rating: ratingValue }),
      });

      // Submit review if provided
      if (reviewTitle && reviewContent) {
        await fetch(`${API_BASE_URL}/api/marketplace/templates/${selectedTemplate.id}/reviews`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ rating: ratingValue, title: reviewTitle, content: reviewContent }),
        });
      }

      setShowRatingModal(false);
      setRatingValue(5);
      setReviewTitle('');
      setReviewContent('');
      fetchTemplates(); // Refresh to show updated rating
    } catch {
      alert('Failed to submit rating');
    } finally {
      setSubmittingRating(false);
    }
  };

  useEffect(() => {
    fetchTemplates();
    fetchCategories();
    fetchFeatured();
    fetchTrending();
  }, [fetchTemplates, fetchCategories, fetchFeatured, fetchTrending]);

  const renderTemplateCard = (template: MarketplaceTemplate) => (
    <button
      key={template.id}
      onClick={() => {
        setSelectedTemplate(template);
        fetchTemplateDetails(template.id);
      }}
      className={`card p-4 text-left transition-all hover:border-[var(--accent)]/60 ${
        selectedTemplate?.id === template.id ? 'border-[var(--accent)] bg-[var(--accent)]/5' : ''
      }`}
    >
      {/* Category Badge */}
      <div className="flex items-center justify-between mb-2">
        <span className="px-2 py-0.5 text-xs font-theme-data bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)]">
          [{template.category.toUpperCase()}]
        </span>
        <StarRating rating={template.rating} />
      </div>

      {/* Name */}
      <h3 className="font-theme-data text-[var(--accent)] font-bold mb-1">{template.name}</h3>

      {/* Author */}
      <p className="text-xs font-theme-data text-text-muted mb-2">by {template.author_name}</p>

      {/* Description */}
      <p className="text-sm font-theme-data text-text-muted mb-3 line-clamp-2">
        {template.description}
      </p>

      {/* Tags */}
      <div className="flex flex-wrap gap-1 mb-3">
        {template.tags.slice(0, 3).map((tag) => (
          <span
            key={tag}
            className="px-2 py-0.5 text-xs font-theme-data bg-surface border border-[var(--accent)]/20 text-text-muted"
          >
            {tag}
          </span>
        ))}
        {template.tags.length > 3 && (
          <span className="px-2 py-0.5 text-xs font-theme-data text-text-muted">
            +{template.tags.length - 3}
          </span>
        )}
      </div>

      {/* Stats */}
      <div className="flex items-center justify-between text-xs font-theme-data text-text-muted">
        <span>{template.download_count} downloads</span>
        <span>{template.rating_count} ratings</span>
      </div>
    </button>
  );

  if (loading && templates.length === 0) {
    return (
      <div className="card p-6">
        <div className="flex items-center gap-3">
          <div className="animate-spin w-5 h-5 border-2 border-[var(--accent)] border-t-transparent rounded-full" />
          <span className="font-theme-data text-text-muted">Loading marketplace...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="font-theme-data text-[var(--accent)] text-xl">{'>'} TEMPLATE MARKETPLACE</h2>
        <div className="text-xs font-theme-data text-text-muted">
          {templates.length} templates available
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="p-4 bg-red-500/20 border border-red-500/50 rounded text-red-400 text-sm font-theme-data">
          {error}
          <button onClick={fetchTemplates} className="ml-4 underline">
            [RETRY]
          </button>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 border-b border-[var(--accent)]/20 pb-2">
        <button
          onClick={() => setActiveTab('browse')}
          className={`px-4 py-2 text-sm font-theme-data transition-colors ${
            activeTab === 'browse'
              ? 'border border-[var(--accent)] bg-[var(--accent)]/20 text-[var(--accent)]'
              : 'border border-transparent text-text-muted hover:text-[var(--accent)]'
          }`}
        >
          [BROWSE]
        </button>
        <button
          onClick={() => setActiveTab('featured')}
          className={`px-4 py-2 text-sm font-theme-data transition-colors ${
            activeTab === 'featured'
              ? 'border border-[var(--accent)] bg-[var(--accent)]/20 text-[var(--accent)]'
              : 'border border-transparent text-text-muted hover:text-[var(--accent)]'
          }`}
        >
          [FEATURED]
        </button>
        <button
          onClick={() => setActiveTab('trending')}
          className={`px-4 py-2 text-sm font-theme-data transition-colors ${
            activeTab === 'trending'
              ? 'border border-[var(--accent)] bg-[var(--accent)]/20 text-[var(--accent)]'
              : 'border border-transparent text-text-muted hover:text-[var(--accent)]'
          }`}
        >
          [TRENDING]
        </button>
      </div>

      {activeTab === 'browse' && (
        <>
          {/* Filters */}
          <div className="card p-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {/* Search */}
              <div>
                <label className="block font-theme-data text-xs text-text-muted mb-2">Search</label>
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search templates..."
                  className="w-full bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                />
              </div>

              {/* Category */}
              <div>
                <label className="block font-theme-data text-xs text-text-muted mb-2">
                  Category
                </label>
                <select
                  value={selectedCategory || ''}
                  onChange={(e) => setSelectedCategory(e.target.value || null)}
                  className="w-full bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                >
                  <option value="">All Categories</option>
                  {categories.map((cat) => (
                    <option key={cat.id} value={cat.id}>
                      {cat.name} ({cat.template_count})
                    </option>
                  ))}
                </select>
              </div>

              {/* Sort */}
              <div>
                <label className="block font-theme-data text-xs text-text-muted mb-2">
                  Sort By
                </label>
                <select
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value)}
                  className="w-full bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                >
                  {SORT_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          {/* Template Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {templates.map(renderTemplateCard)}
          </div>

          {templates.length === 0 && !loading && (
            <div className="card p-8 text-center">
              <p className="text-text-muted font-theme-data">
                No templates match your search criteria.
              </p>
            </div>
          )}
        </>
      )}

      {activeTab === 'featured' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {featured.length > 0 ? (
            featured.map(renderTemplateCard)
          ) : (
            <div className="col-span-3 card p-8 text-center">
              <p className="text-text-muted font-theme-data">No featured templates available.</p>
            </div>
          )}
        </div>
      )}

      {activeTab === 'trending' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {trending.length > 0 ? (
            trending.map(renderTemplateCard)
          ) : (
            <div className="col-span-3 card p-8 text-center">
              <p className="text-text-muted font-theme-data">No trending templates available.</p>
            </div>
          )}
        </div>
      )}

      {/* Template Detail Modal */}
      {selectedTemplate && (
        <div className="fixed inset-0 z-[100] bg-bg/95 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="max-w-3xl w-full border border-[var(--accent)]/50 bg-surface p-6 max-h-[90vh] overflow-y-auto">
            <div className="flex justify-between items-start mb-6">
              <div>
                <div className="flex items-center gap-3 mb-2">
                  <span className="px-2 py-0.5 text-xs font-theme-data bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)]">
                    [{selectedTemplate.category.toUpperCase()}]
                  </span>
                  <StarRating rating={selectedTemplate.rating} size="lg" />
                  <span className="text-sm font-theme-data text-text-muted">
                    ({selectedTemplate.rating_count} ratings)
                  </span>
                </div>
                <h2 className="text-xl font-theme-data text-[var(--accent)]">
                  {selectedTemplate.name}
                </h2>
                <p className="text-sm font-theme-data text-text-muted mt-1">
                  by {selectedTemplate.author_name}
                </p>
              </div>
              <button
                onClick={() => setSelectedTemplate(null)}
                className="text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [X]
              </button>
            </div>

            <p className="font-theme-data text-sm text-text-muted mb-6">
              {selectedTemplate.description}
            </p>

            {/* Stats */}
            <div className="grid grid-cols-3 gap-4 p-4 bg-bg border border-[var(--accent)]/20 mb-6">
              <div className="text-center">
                <div className="text-2xl font-theme-data text-[var(--accent)]">
                  {selectedTemplate.download_count}
                </div>
                <div className="text-xs font-theme-data text-text-muted">Downloads</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-theme-data text-[var(--acid-yellow)]">
                  {(Number(selectedTemplate.rating) || 0).toFixed(1)}
                </div>
                <div className="text-xs font-theme-data text-text-muted">Rating</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
                  {selectedTemplate.pattern || 'N/A'}
                </div>
                <div className="text-xs font-theme-data text-text-muted">Pattern</div>
              </div>
            </div>

            {/* Tags */}
            <div className="flex flex-wrap gap-2 mb-6">
              {selectedTemplate.tags.map((tag) => (
                <span
                  key={tag}
                  className="px-3 py-1 text-xs font-theme-data bg-surface border border-[var(--accent)]/20 text-text-muted"
                >
                  {tag}
                </span>
              ))}
            </div>

            {/* Actions */}
            <div className="flex gap-3">
              <button
                onClick={() => setSelectedTemplate(null)}
                className="px-4 py-2 font-theme-data text-sm border border-[var(--accent)]/30
                         text-text-muted hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors"
              >
                [CLOSE]
              </button>
              <button
                onClick={() => setShowRatingModal(true)}
                className="px-4 py-2 font-theme-data text-sm border border-acid-yellow/30
                         text-[var(--acid-yellow)] hover:bg-acid-yellow/10 transition-colors"
              >
                [RATE]
              </button>
              <button
                onClick={() => handleImportTemplate(selectedTemplate.id)}
                disabled={importingTemplate === selectedTemplate.id}
                className="flex-1 px-6 py-2 font-theme-data text-sm bg-[var(--accent)] text-bg
                         hover:bg-[var(--accent)]/80 transition-colors disabled:opacity-50"
              >
                {importingTemplate === selectedTemplate.id ? '[IMPORTING...]' : '[IMPORT TEMPLATE]'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Rating Modal */}
      {showRatingModal && selectedTemplate && (
        <div className="fixed inset-0 z-[110] bg-bg/95 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="max-w-md w-full border border-acid-yellow/50 bg-surface p-6">
            <h3 className="text-lg font-theme-data text-[var(--acid-yellow)] mb-4">
              Rate {selectedTemplate.name}
            </h3>

            {/* Star Rating Input */}
            <div className="mb-4">
              <label className="block font-theme-data text-xs text-text-muted mb-2">Rating</label>
              <div className="flex gap-2">
                {[1, 2, 3, 4, 5].map((star) => (
                  <button
                    key={star}
                    onClick={() => setRatingValue(star)}
                    className={`text-2xl ${
                      star <= ratingValue ? 'text-[var(--acid-yellow)]' : 'text-text-muted/30'
                    }`}
                  >
                    ★
                  </button>
                ))}
              </div>
            </div>

            {/* Review Title (Optional) */}
            <div className="mb-4">
              <label className="block font-theme-data text-xs text-text-muted mb-2">
                Review Title (Optional)
              </label>
              <input
                type="text"
                value={reviewTitle}
                onChange={(e) => setReviewTitle(e.target.value)}
                placeholder="Great template!"
                className="w-full bg-bg border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-acid-yellow"
              />
            </div>

            {/* Review Content (Optional) */}
            <div className="mb-6">
              <label className="block font-theme-data text-xs text-text-muted mb-2">
                Review (Optional)
              </label>
              <textarea
                value={reviewContent}
                onChange={(e) => setReviewContent(e.target.value)}
                placeholder="Share your experience..."
                rows={3}
                className="w-full bg-bg border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-acid-yellow resize-none"
              />
            </div>

            <div className="flex gap-3">
              <button
                onClick={() => setShowRatingModal(false)}
                className="px-4 py-2 font-theme-data text-sm border border-[var(--accent)]/30
                         text-text-muted hover:border-[var(--accent)] transition-colors"
              >
                [CANCEL]
              </button>
              <button
                onClick={handleRateTemplate}
                disabled={submittingRating}
                className="flex-1 px-4 py-2 font-theme-data text-sm bg-acid-yellow text-bg
                         hover:bg-acid-yellow/80 transition-colors disabled:opacity-50"
              >
                {submittingRating ? '[SUBMITTING...]' : '[SUBMIT RATING]'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default TemplateMarketplace;
