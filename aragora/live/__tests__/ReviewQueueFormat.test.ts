/**
 * Tests for the review-queue shared formatting helpers.
 */

import {
  ciGlyph,
  formatAge,
  formatDecisionSeconds,
  toneColor,
  verdictGlyph,
} from '../src/components/review-queue/format';

describe('formatAge', () => {
  it('returns dash for null/undefined', () => {
    expect(formatAge(null)).toBe('—');
    expect(formatAge(undefined)).toBe('—');
  });

  it('formats seconds, minutes, hours and days', () => {
    expect(formatAge(12)).toBe('12s');
    expect(formatAge(90)).toBe('1m');
    expect(formatAge(60 * 60 * 3)).toBe('3h');
    expect(formatAge(60 * 60 * 72)).toBe('3d');
  });
});

describe('formatDecisionSeconds', () => {
  it('handles null', () => {
    expect(formatDecisionSeconds(null)).toBe('—');
  });

  it('handles sub-second, seconds, and minutes', () => {
    expect(formatDecisionSeconds(0.25)).toBe('250ms');
    expect(formatDecisionSeconds(12)).toBe('12.0s');
    expect(formatDecisionSeconds(125)).toBe('2m05s');
  });
});

describe('ciGlyph', () => {
  it('neutral on no checks', () => {
    expect(ciGlyph({ success: 0, failure: 0, pending: 0, total: 0 })).toMatchObject({
      tone: 'neutral',
      glyph: '·',
    });
  });

  it('fail wins over pending and ok', () => {
    expect(ciGlyph({ success: 3, failure: 1, pending: 2, total: 6 })).toMatchObject({
      tone: 'fail',
    });
  });

  it('warn when only pending', () => {
    expect(ciGlyph({ success: 1, failure: 0, pending: 2, total: 3 })).toMatchObject({
      tone: 'warn',
    });
  });

  it('ok when all green', () => {
    expect(ciGlyph({ success: 4, failure: 0, pending: 0, total: 4 })).toMatchObject({ tone: 'ok' });
  });
});

describe('verdictGlyph', () => {
  it('neutral when no brief', () => {
    expect(verdictGlyph(false, null)).toMatchObject({ tone: 'neutral' });
  });

  it('matches known verdicts', () => {
    expect(verdictGlyph(true, 'approve_candidate').tone).toBe('ok');
    expect(verdictGlyph(true, 'needs_human_attention').tone).toBe('warn');
    expect(verdictGlyph(true, 'repair_first').tone).toBe('fail');
  });

  it('falls back to neutral on unknown verdicts', () => {
    expect(verdictGlyph(true, 'something-else').tone).toBe('neutral');
  });
});

describe('toneColor', () => {
  it('maps every tone', () => {
    expect(toneColor('ok')).toContain('green');
    expect(toneColor('warn')).toContain('yellow');
    expect(toneColor('fail')).toContain('red');
    expect(toneColor('neutral')).toContain('slate');
  });
});
