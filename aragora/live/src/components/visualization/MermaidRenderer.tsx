'use client';

import { useState, useEffect, useRef, useCallback } from 'react';

interface MermaidRendererProps {
  diagram: string;
  className?: string;
}

/**
 * Renders a Mermaid.js diagram using dynamic import.
 * Supports zoom/pan and copy-to-clipboard functionality.
 */
export function MermaidRenderer({ diagram, className = '' }: MermaidRendererProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);

  // Render Mermaid diagram
  useEffect(() => {
    if (!diagram) {
      setLoading(false);
      return;
    }

    const renderDiagram = async () => {
      try {
        setLoading(true);
        setError(null);

        // Dynamically import mermaid
        const mermaid = (await import('mermaid')).default;

        // Initialize mermaid with theme settings
        mermaid.initialize({
          startOnLoad: false,
          theme: 'dark',
          themeVariables: {
            darkMode: true,
            background: '#0a0a0a',
            primaryColor: '#00ff00',
            primaryTextColor: '#ffffff',
            primaryBorderColor: '#00ff00',
            lineColor: '#00ff00',
            secondaryColor: '#1a1a1a',
            tertiaryColor: '#2a2a2a',
          },
          flowchart: { htmlLabels: true, curve: 'basis' },
          securityLevel: 'loose',
        });

        // Render the diagram
        const id = `mermaid-${Date.now()}`;
        const { svg: renderedSvg } = await mermaid.render(id, diagram);
        setSvg(renderedSvg);
      } catch (err) {
        console.error('Mermaid render error:', err);
        setError(err instanceof Error ? err.message : 'Failed to render diagram');
      } finally {
        setLoading(false);
      }
    };

    renderDiagram();
  }, [diagram]);

  // Copy diagram code to clipboard
  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(diagram);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  }, [diagram]);

  // Download as SVG
  const handleDownload = useCallback(() => {
    if (!svg) return;

    const blob = new Blob([svg], { type: 'image/svg+xml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'argument-map.svg';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [svg]);

  if (!diagram) {
    return (
      <div
        className={`flex items-center justify-center p-8 border border-[var(--accent)]/20 bg-surface/30 ${className}`}
      >
        <p className="text-text-muted text-sm font-theme-data">No diagram to display</p>
      </div>
    );
  }

  return (
    <div className={`relative ${className}`}>
      {/* Controls */}
      <div className="absolute top-2 right-2 z-10 flex gap-2">
        <button
          onClick={handleCopy}
          className="px-3 py-1 text-xs font-theme-data bg-surface/90 border border-[var(--accent)]/20 text-[var(--accent)] hover:bg-surface transition-colors"
        >
          {copied ? 'Copied!' : 'Copy Code'}
        </button>
        <button
          onClick={handleDownload}
          disabled={!svg}
          className="px-3 py-1 text-xs font-theme-data bg-surface/90 border border-[var(--accent)]/20 text-[var(--acid-cyan)] hover:bg-surface transition-colors disabled:opacity-50"
        >
          Download SVG
        </button>
      </div>

      {/* Loading State */}
      {loading && (
        <div className="flex items-center justify-center p-16 border border-[var(--accent)]/20 bg-surface/30">
          <div className="text-center">
            <div className="w-8 h-8 border-2 border-[var(--accent)]/30 border-t-acid-green rounded-full animate-spin mx-auto mb-4" />
            <p className="text-text-muted text-sm font-theme-data">Rendering diagram...</p>
          </div>
        </div>
      )}

      {/* Error State */}
      {error && !loading && (
        <div className="border border-warning/30 bg-warning/10 p-4">
          <p className="text-warning text-sm font-theme-data mb-2">Failed to render diagram:</p>
          <pre className="text-xs text-text-muted overflow-x-auto">{error}</pre>
          <details className="mt-4">
            <summary className="text-xs text-text-muted cursor-pointer hover:text-[var(--accent)]">
              Show diagram code
            </summary>
            <pre className="mt-2 p-2 bg-bg/50 text-xs font-theme-data text-text-muted overflow-x-auto max-h-48">
              {diagram}
            </pre>
          </details>
        </div>
      )}

      {/* Rendered Diagram */}
      {svg && !loading && !error && (
        <div
          ref={containerRef}
          className="border border-[var(--accent)]/20 bg-bg overflow-auto p-4"
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      )}

      {/* Raw Code View */}
      <details className="mt-4">
        <summary className="text-xs font-theme-data text-text-muted cursor-pointer hover:text-[var(--accent)]">
          View Mermaid source
        </summary>
        <pre className="mt-2 p-3 bg-surface/50 border border-[var(--accent)]/10 text-xs font-theme-data text-text overflow-x-auto max-h-64">
          {diagram}
        </pre>
      </details>
    </div>
  );
}

export default MermaidRenderer;
