/**
 * Tests for sanitize utilities
 */

import { escapeHtml, sanitizeUrl, validateFileUpload, sanitizeSuggestion } from '@/utils/sanitize';

describe('sanitize utilities', () => {
  describe('escapeHtml', () => {
    it('escapes ampersand', () => {
      expect(escapeHtml('foo & bar')).toBe('foo &amp; bar');
    });

    it('escapes less than', () => {
      expect(escapeHtml('a < b')).toBe('a &lt; b');
    });

    it('escapes greater than', () => {
      expect(escapeHtml('a > b')).toBe('a &gt; b');
    });

    it('escapes double quotes', () => {
      expect(escapeHtml('say "hello"')).toBe('say &quot;hello&quot;');
    });

    it('escapes single quotes', () => {
      expect(escapeHtml("it's")).toBe('it&#039;s');
    });

    it('escapes multiple special characters', () => {
      expect(escapeHtml('<script>alert("xss")</script>')).toBe(
        '&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;',
      );
    });

    it('returns empty string for empty input', () => {
      expect(escapeHtml('')).toBe('');
    });

    it('returns unchanged string without special chars', () => {
      expect(escapeHtml('hello world')).toBe('hello world');
    });
  });

  describe('sanitizeUrl', () => {
    it('allows http URLs', () => {
      expect(sanitizeUrl('http://example.com')).toBe('http://example.com/');
    });

    it('allows https URLs', () => {
      expect(sanitizeUrl('https://example.com/path?query=1')).toBe(
        'https://example.com/path?query=1',
      );
    });

    it('allows mailto URLs', () => {
      expect(sanitizeUrl('mailto:test@example.com')).toBe('mailto:test@example.com');
    });

    it('blocks javascript URLs', () => {
      expect(sanitizeUrl('javascript:alert(1)')).toBe('#');
    });

    it('blocks data URLs', () => {
      expect(sanitizeUrl('data:text/html,<script>alert(1)</script>')).toBe('#');
    });

    it('blocks file URLs', () => {
      expect(sanitizeUrl('file:///etc/passwd')).toBe('#');
    });

    it('returns # for invalid URLs', () => {
      expect(sanitizeUrl('not a url')).toBe('#');
    });

    it('returns # for empty string', () => {
      expect(sanitizeUrl('')).toBe('#');
    });

    it('blocks ftp URLs', () => {
      expect(sanitizeUrl('ftp://example.com')).toBe('#');
    });
  });

  describe('validateFileUpload', () => {
    const createMockFile = (name: string, size: number, type: string): File => {
      const file = new File([''], name, { type });
      Object.defineProperty(file, 'size', { value: size });
      return file;
    };

    it('accepts valid PDF file', () => {
      const file = createMockFile('doc.pdf', 1024 * 1024, 'application/pdf');
      const result = validateFileUpload(file, ['pdf']);
      expect(result.valid).toBe(true);
      expect(result.error).toBeUndefined();
    });

    it('accepts valid text file', () => {
      const file = createMockFile('doc.txt', 1024, 'text/plain');
      const result = validateFileUpload(file, ['txt', 'md']);
      expect(result.valid).toBe(true);
    });

    it('rejects file exceeding size limit', () => {
      const file = createMockFile('doc.pdf', 15 * 1024 * 1024, 'application/pdf');
      const result = validateFileUpload(file, ['pdf'], 10);
      expect(result.valid).toBe(false);
      expect(result.error).toContain('too large');
    });

    it('rejects file with wrong extension', () => {
      const file = createMockFile('doc.exe', 1024, 'application/octet-stream');
      const result = validateFileUpload(file, ['pdf', 'txt']);
      expect(result.valid).toBe(false);
      expect(result.error).toContain('Invalid file type');
    });

    it('rejects file with mismatched MIME type', () => {
      const file = createMockFile('doc.pdf', 1024, 'text/plain');
      const result = validateFileUpload(file, ['pdf']);
      expect(result.valid).toBe(false);
      expect(result.error).toContain("doesn't match extension");
    });

    it('accepts CSV file with correct MIME', () => {
      const file = createMockFile('data.csv', 1024, 'text/csv');
      const result = validateFileUpload(file, ['csv']);
      expect(result.valid).toBe(true);
    });

    it('accepts JSON file', () => {
      const file = createMockFile('config.json', 1024, 'application/json');
      const result = validateFileUpload(file, ['json']);
      expect(result.valid).toBe(true);
    });

    it('uses default 10MB size limit', () => {
      const file = createMockFile('doc.pdf', 11 * 1024 * 1024, 'application/pdf');
      const result = validateFileUpload(file, ['pdf']);
      expect(result.valid).toBe(false);
      expect(result.error).toContain('10MB');
    });

    it('accepts file without MIME check for unknown extensions', () => {
      const file = createMockFile('file.xyz', 1024, 'application/octet-stream');
      const result = validateFileUpload(file, ['xyz']);
      expect(result.valid).toBe(true);
    });
  });

  describe('sanitizeSuggestion', () => {
    it('trims whitespace', () => {
      expect(sanitizeSuggestion('  hello world  ')).toBe('hello world');
    });

    it('truncates to max length', () => {
      const long = 'a'.repeat(1500);
      const result = sanitizeSuggestion(long, 1000);
      expect(result.length).toBe(1000);
    });

    it('uses default max length of 1000', () => {
      const long = 'a'.repeat(1500);
      const result = sanitizeSuggestion(long);
      expect(result.length).toBe(1000);
    });

    it('removes control characters', () => {
      // Control characters are removed without adding spaces
      expect(sanitizeSuggestion('hello\x00\x01\x02world')).toBe('helloworld');
    });

    it('preserves newlines by converting to spaces', () => {
      expect(sanitizeSuggestion('hello\nworld')).toBe('hello world');
    });

    it('normalizes multiple spaces', () => {
      expect(sanitizeSuggestion('hello    world')).toBe('hello world');
    });

    it('returns empty string for empty input', () => {
      expect(sanitizeSuggestion('')).toBe('');
    });

    it('handles string with only whitespace', () => {
      expect(sanitizeSuggestion('   \t\n   ')).toBe('');
    });

    it('removes tab characters', () => {
      // Tabs are control characters and get removed
      expect(sanitizeSuggestion('hello\tworld')).toBe('helloworld');
    });
  });
});
