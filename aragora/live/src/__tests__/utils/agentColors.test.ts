/**
 * Tests for agent colors utilities
 */

import { AGENT_COLORS, getAgentColors, getAgentTextColor } from '@/utils/agentColors';

describe('agentColors utilities', () => {
  describe('AGENT_COLORS constant', () => {
    it('has gemini color scheme', () => {
      expect(AGENT_COLORS.gemini).toBeDefined();
      expect(AGENT_COLORS.gemini.bg).toContain('purple');
      expect(AGENT_COLORS.gemini.text).toContain('purple');
    });

    it('has codex color scheme', () => {
      expect(AGENT_COLORS.codex).toBeDefined();
      expect(AGENT_COLORS.codex.bg).toContain('gold');
      expect(AGENT_COLORS.codex.text).toContain('gold');
    });

    it('has claude color scheme', () => {
      expect(AGENT_COLORS.claude).toBeDefined();
      expect(AGENT_COLORS.claude.bg).toContain('cyan');
      expect(AGENT_COLORS.claude.text).toContain('cyan');
    });

    it('has grok color scheme', () => {
      expect(AGENT_COLORS.grok).toBeDefined();
      expect(AGENT_COLORS.grok.bg).toContain('crimson');
      expect(AGENT_COLORS.grok.text).toContain('crimson');
    });

    it('has default color scheme', () => {
      expect(AGENT_COLORS.default).toBeDefined();
      expect(AGENT_COLORS.default.bg).toContain('green');
      expect(AGENT_COLORS.default.text).toContain('green');
    });

    it('all schemes have required properties', () => {
      Object.values(AGENT_COLORS).forEach((scheme) => {
        expect(scheme).toHaveProperty('bg');
        expect(scheme).toHaveProperty('text');
        expect(scheme).toHaveProperty('border');
        expect(typeof scheme.bg).toBe('string');
        expect(typeof scheme.text).toBe('string');
        expect(typeof scheme.border).toBe('string');
      });
    });
  });

  describe('getAgentColors', () => {
    it('returns gemini colors for gemini variants', () => {
      expect(getAgentColors('gemini')).toBe(AGENT_COLORS.gemini);
      expect(getAgentColors('gemini-pro')).toBe(AGENT_COLORS.gemini);
      expect(getAgentColors('gemini-1.5-flash')).toBe(AGENT_COLORS.gemini);
      expect(getAgentColors('GEMINI')).toBe(AGENT_COLORS.gemini);
    });

    it('returns codex colors for OpenAI variants', () => {
      expect(getAgentColors('codex')).toBe(AGENT_COLORS.codex);
      expect(getAgentColors('codex-davinci')).toBe(AGENT_COLORS.codex);
      expect(getAgentColors('gpt-4')).toBe(AGENT_COLORS.codex);
      expect(getAgentColors('gpt-4-turbo')).toBe(AGENT_COLORS.codex);
      expect(getAgentColors('gpt-3.5-turbo')).toBe(AGENT_COLORS.codex);
      expect(getAgentColors('openai-gpt4')).toBe(AGENT_COLORS.codex);
    });

    it('returns claude colors for Anthropic variants', () => {
      expect(getAgentColors('claude')).toBe(AGENT_COLORS.claude);
      expect(getAgentColors('claude-3-opus')).toBe(AGENT_COLORS.claude);
      expect(getAgentColors('claude-3-sonnet')).toBe(AGENT_COLORS.claude);
      expect(getAgentColors('claude-instant')).toBe(AGENT_COLORS.claude);
      expect(getAgentColors('anthropic-claude')).toBe(AGENT_COLORS.claude);
    });

    it('returns grok colors for xAI variants', () => {
      expect(getAgentColors('grok')).toBe(AGENT_COLORS.grok);
      expect(getAgentColors('grok-1')).toBe(AGENT_COLORS.grok);
      expect(getAgentColors('grok-explorer')).toBe(AGENT_COLORS.grok);
      expect(getAgentColors('xai-grok')).toBe(AGENT_COLORS.grok);
    });

    it('returns default colors for unknown agents', () => {
      expect(getAgentColors('unknown')).toBe(AGENT_COLORS.default);
      expect(getAgentColors('some-other-model')).toBe(AGENT_COLORS.default);
      expect(getAgentColors('')).toBe(AGENT_COLORS.default);
    });

    it('is case insensitive', () => {
      expect(getAgentColors('GEMINI')).toBe(AGENT_COLORS.gemini);
      expect(getAgentColors('Claude')).toBe(AGENT_COLORS.claude);
      expect(getAgentColors('GPT-4')).toBe(AGENT_COLORS.codex);
      expect(getAgentColors('GROK')).toBe(AGENT_COLORS.grok);
    });

    it('returns complete color scheme object', () => {
      const scheme = getAgentColors('gemini');
      expect(scheme).toHaveProperty('bg');
      expect(scheme).toHaveProperty('text');
      expect(scheme).toHaveProperty('border');
      expect(scheme).toHaveProperty('glow');
      expect(scheme).toHaveProperty('tab');
    });
  });

  describe('getAgentTextColor', () => {
    it('returns text color for gemini', () => {
      expect(getAgentTextColor('gemini')).toBe('text-purple');
    });

    it('returns text color for codex/gpt', () => {
      expect(getAgentTextColor('gpt-4')).toBe('text-gold');
    });

    it('returns text color for claude', () => {
      expect(getAgentTextColor('claude-3')).toBe('text-acid-cyan');
    });

    it('returns text color for grok', () => {
      expect(getAgentTextColor('grok')).toBe('text-crimson');
    });

    it('returns default text color for unknown', () => {
      expect(getAgentTextColor('unknown')).toBe('text-acid-green');
    });

    it('is case insensitive', () => {
      expect(getAgentTextColor('CLAUDE')).toBe('text-acid-cyan');
    });
  });
});
