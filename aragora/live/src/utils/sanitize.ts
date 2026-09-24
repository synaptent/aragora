/**
 * Content sanitization utilities for XSS protection.
 *
 * Uses DOMPurify to sanitize HTML content from untrusted sources
 * (agent messages, user suggestions, external data).
 */

import DOMPurify from 'dompurify';

// Configure DOMPurify with safe defaults
const SAFE_CONFIG = {
  ALLOWED_TAGS: [
    'b',
    'i',
    'em',
    'strong',
    'a',
    'p',
    'br',
    'ul',
    'ol',
    'li',
    'code',
    'pre',
    'blockquote',
    'h1',
    'h2',
    'h3',
    'h4',
    'h5',
    'h6',
    'span',
    'div',
    'table',
    'thead',
    'tbody',
    'tr',
    'th',
    'td',
  ],
  ALLOWED_ATTR: ['href', 'title', 'class', 'id', 'target', 'rel'],
  ALLOW_DATA_ATTR: false,
  ADD_ATTR: ['target'],
  FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed', 'form', 'input'],
  FORBID_ATTR: ['onerror', 'onload', 'onclick', 'onmouseover', 'onfocus', 'onblur'],
};

// Strict config for plain text only (no HTML allowed)
const STRICT_CONFIG = { ALLOWED_TAGS: [] as string[], ALLOWED_ATTR: [] as string[] };

/**
 * Sanitize HTML content, allowing safe formatting tags.
 * Use for rendering agent messages, debate content, etc.
 */
export function sanitizeHtml(dirty: string): string {
  if (typeof window === 'undefined') {
    // SSR fallback - escape HTML entities
    return escapeHtml(dirty);
  }
  return DOMPurify.sanitize(dirty, SAFE_CONFIG);
}

/**
 * Sanitize to plain text only (strip all HTML).
 * Use for user inputs, search queries, etc.
 */
export function sanitizeText(dirty: string): string {
  if (typeof window === 'undefined') {
    return escapeHtml(dirty);
  }
  return DOMPurify.sanitize(dirty, STRICT_CONFIG);
}

/**
 * Escape HTML entities for safe text display.
 * Works both client and server side.
 */
export function escapeHtml(text: string): string {
  const map: Record<string, string> = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;',
  };
  return text.replace(/[&<>"']/g, (char) => map[char] || char);
}

/**
 * Validate and sanitize a URL.
 * Only allows http, https, and mailto protocols.
 */
export function sanitizeUrl(url: string): string {
  try {
    const parsed = new URL(url);
    if (!['http:', 'https:', 'mailto:'].includes(parsed.protocol)) {
      return '#';
    }
    return parsed.toString();
  } catch {
    return '#';
  }
}

/**
 * Validate file upload - check extension and MIME type.
 */
export function validateFileUpload(
  file: File,
  allowedExtensions: string[],
  maxSizeMB: number = 10,
): { valid: boolean; error?: string } {
  // Check file size
  const maxBytes = maxSizeMB * 1024 * 1024;
  if (file.size > maxBytes) {
    return { valid: false, error: `File too large. Max size: ${maxSizeMB}MB` };
  }

  // Check extension
  const ext = file.name.split('.').pop()?.toLowerCase() || '';
  if (!allowedExtensions.includes(ext)) {
    return { valid: false, error: `Invalid file type. Allowed: ${allowedExtensions.join(', ')}` };
  }

  // Check MIME type matches extension
  const mimeMap: Record<string, string[]> = {
    pdf: ['application/pdf'],
    txt: ['text/plain'],
    md: ['text/markdown', 'text/plain'],
    json: ['application/json'],
    csv: ['text/csv', 'application/csv'],
    doc: ['application/msword'],
    docx: ['application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
  };

  const allowedMimes = mimeMap[ext] || [];
  if (allowedMimes.length > 0 && !allowedMimes.includes(file.type)) {
    return {
      valid: false,
      error: `File MIME type (${file.type}) doesn't match extension (.${ext})`,
    };
  }

  return { valid: true };
}

/**
 * Sanitize user suggestion text.
 * Trims whitespace, limits length, removes control characters.
 */
export function sanitizeSuggestion(text: string, maxLength: number = 1000): string {
  return (
    text
      .trim()
      .slice(0, maxLength)
      // Remove control characters except newlines
      .replace(/[\x00-\x09\x0B\x0C\x0E-\x1F\x7F]/g, '')
      // Normalize whitespace
      .replace(/\s+/g, ' ')
  );
}
