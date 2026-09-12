'use client';

import { useMemo } from 'react';

interface InputDetectorProps {
  text: string;
  onTemplateSelect: (templateName: string) => void;
}

interface Detection {
  type: 'structured' | 'json' | 'url' | 'freeform';
  message: string;
  icon: string;
  template?: { name: string; label: string };
}

export function InputDetector({ text, onTemplateSelect }: InputDetectorProps) {
  const detection = useMemo((): Detection | null => {
    if (!text.trim()) return null;

    // JSON detection
    if (text.trim().startsWith('{') || text.trim().startsWith('[')) {
      try {
        const parsed = JSON.parse(text);
        const count = Array.isArray(parsed) ? parsed.length : 1;
        return { type: 'json', message: `Detected JSON import (${count} items)`, icon: '{ }' };
      } catch {
        return { type: 'json', message: 'Detected JSON (invalid syntax)', icon: '{ }' };
      }
    }

    // URL detection
    if (text.trim().match(/^https?:\/\//)) {
      return {
        type: 'url',
        message: 'Detected URL - will extract ideas from content',
        icon: '\u{1F310}',
      };
    }

    // Structured list detection
    const lines = text.split('\n').filter((l) => l.trim());
    const bulletLines = lines.filter((l) => /^\s*[-*\u2022\d.]+\s/.test(l));
    if (bulletLines.length >= 3 && bulletLines.length / lines.length > 0.6) {
      // Check for template patterns
      const lower = text.toLowerCase();
      let template: Detection['template'];
      if (
        lower.includes('code review') ||
        lower.includes('pull request') ||
        lower.includes('pr review')
      ) {
        template = { name: 'code_review', label: 'Code Review' };
      } else if (
        lower.includes('security') ||
        lower.includes('vulnerability') ||
        lower.includes('pentest')
      ) {
        template = { name: 'security_audit', label: 'Security Audit' };
      } else if (
        lower.includes('incident') ||
        lower.includes('postmortem') ||
        lower.includes('outage')
      ) {
        template = { name: 'incident_analysis', label: 'Incident Analysis' };
      }

      return {
        type: 'structured',
        message: `Detected structured list (${bulletLines.length} items)`,
        icon: '\u2261',
        template,
      };
    }

    // Free-form text
    if (lines.length >= 1) {
      const words = text.split(/\s+/).length;
      return {
        type: 'freeform',
        message: `Free-form brain dump (${words} words)`,
        icon: '\u{1F4AD}',
      };
    }

    return null;
  }, [text]);

  if (!detection) return null;

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 text-xs font-theme-data rounded bg-bg border border-border">
      <span>{detection.icon}</span>
      <span className="text-text-muted">{detection.message}</span>
      {detection.template && (
        <button
          onClick={() => onTemplateSelect(detection.template!.name)}
          className="ml-auto text-[var(--accent)] hover:underline"
        >
          Use {detection.template.label} template?
        </button>
      )}
    </div>
  );
}
