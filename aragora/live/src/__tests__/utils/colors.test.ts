/**
 * Tests for color utilities
 */

import {
  getEloColor,
  getConsistencyColor,
  getConfidenceColor,
  getRankBadge,
  getStatusColor,
  getTypeBadge,
  getScoreColor,
  getInsightTypeColor,
  getFlipTypeColor,
  getDomainColor,
} from '@/utils/colors';

describe('color utilities', () => {
  describe('getEloColor', () => {
    it('returns green for high ELO (>= 1600)', () => {
      expect(getEloColor(1600)).toBe('text-green-400');
      expect(getEloColor(1800)).toBe('text-green-400');
      expect(getEloColor(2000)).toBe('text-green-400');
    });

    it('returns yellow for medium-high ELO (1500-1599)', () => {
      expect(getEloColor(1500)).toBe('text-yellow-400');
      expect(getEloColor(1550)).toBe('text-yellow-400');
      expect(getEloColor(1599)).toBe('text-yellow-400');
    });

    it('returns orange for medium ELO (1400-1499)', () => {
      expect(getEloColor(1400)).toBe('text-orange-400');
      expect(getEloColor(1450)).toBe('text-orange-400');
      expect(getEloColor(1499)).toBe('text-orange-400');
    });

    it('returns red for low ELO (< 1400)', () => {
      expect(getEloColor(1399)).toBe('text-red-400');
      expect(getEloColor(1200)).toBe('text-red-400');
      expect(getEloColor(1000)).toBe('text-red-400');
    });
  });

  describe('getConsistencyColor', () => {
    it('returns green for high consistency (>= 0.8)', () => {
      expect(getConsistencyColor(0.8)).toBe('text-green-400');
      expect(getConsistencyColor(0.9)).toBe('text-green-400');
      expect(getConsistencyColor(1.0)).toBe('text-green-400');
    });

    it('returns yellow for medium consistency (0.6-0.79)', () => {
      expect(getConsistencyColor(0.6)).toBe('text-yellow-400');
      expect(getConsistencyColor(0.7)).toBe('text-yellow-400');
      expect(getConsistencyColor(0.79)).toBe('text-yellow-400');
    });

    it('returns red for low consistency (< 0.6)', () => {
      expect(getConsistencyColor(0.59)).toBe('text-red-400');
      expect(getConsistencyColor(0.3)).toBe('text-red-400');
      expect(getConsistencyColor(0)).toBe('text-red-400');
    });
  });

  describe('getConfidenceColor', () => {
    it('returns green for high confidence (>= 0.8)', () => {
      expect(getConfidenceColor(0.8)).toBe('text-green-400');
      expect(getConfidenceColor(1.0)).toBe('text-green-400');
    });

    it('returns yellow for medium confidence (0.6-0.79)', () => {
      expect(getConfidenceColor(0.6)).toBe('text-yellow-400');
      expect(getConfidenceColor(0.75)).toBe('text-yellow-400');
    });

    it('returns red for low confidence (< 0.6)', () => {
      expect(getConfidenceColor(0.5)).toBe('text-red-400');
      expect(getConfidenceColor(0)).toBe('text-red-400');
    });
  });

  describe('getRankBadge', () => {
    it('returns gold styling for rank 1', () => {
      expect(getRankBadge(1)).toBe('bg-yellow-500/20 text-yellow-400 border-yellow-500/30');
    });

    it('returns silver styling for rank 2', () => {
      expect(getRankBadge(2)).toBe('bg-gray-400/20 text-gray-300 border-gray-400/30');
    });

    it('returns bronze styling for rank 3', () => {
      expect(getRankBadge(3)).toBe('bg-amber-600/20 text-amber-500 border-amber-600/30');
    });

    it('returns default styling for ranks > 3', () => {
      expect(getRankBadge(4)).toBe('bg-surface text-text-muted border-border');
      expect(getRankBadge(10)).toBe('bg-surface text-text-muted border-border');
      expect(getRankBadge(100)).toBe('bg-surface text-text-muted border-border');
    });
  });

  describe('getStatusColor', () => {
    it('returns green for positive statuses', () => {
      expect(getStatusColor('healthy')).toBe('text-green-400');
      expect(getStatusColor('ok')).toBe('text-green-400');
      expect(getStatusColor('good')).toBe('text-green-400');
    });

    it('returns yellow for warning statuses', () => {
      expect(getStatusColor('degraded')).toBe('text-yellow-400');
      expect(getStatusColor('warning')).toBe('text-yellow-400');
    });

    it('returns red for error statuses', () => {
      expect(getStatusColor('down')).toBe('text-red-400');
      expect(getStatusColor('error')).toBe('text-red-400');
      expect(getStatusColor('critical')).toBe('text-red-400');
    });

    it('returns muted for unknown statuses', () => {
      expect(getStatusColor('unknown')).toBe('text-text-muted');
      expect(getStatusColor('other')).toBe('text-text-muted');
    });

    it('is case insensitive', () => {
      expect(getStatusColor('HEALTHY')).toBe('text-green-400');
      expect(getStatusColor('Degraded')).toBe('text-yellow-400');
      expect(getStatusColor('ERROR')).toBe('text-red-400');
    });
  });

  describe('getTypeBadge', () => {
    it('returns correct styling for insight types', () => {
      expect(getTypeBadge('insight')).toBe('bg-blue-500/20 text-blue-400 border-blue-500/30');
      expect(getTypeBadge('pattern')).toBe('bg-purple-500/20 text-purple-400 border-purple-500/30');
      expect(getTypeBadge('anomaly')).toBe('bg-red-500/20 text-red-400 border-red-500/30');
      expect(getTypeBadge('trend')).toBe('bg-green-500/20 text-green-400 border-green-500/30');
    });

    it('returns correct styling for debate roles', () => {
      expect(getTypeBadge('pro')).toBe('bg-green-500/20 text-green-400 border-green-500/30');
      expect(getTypeBadge('con')).toBe('bg-red-500/20 text-red-400 border-red-500/30');
      expect(getTypeBadge('judge')).toBe('bg-purple-500/20 text-purple-400 border-purple-500/30');
    });

    it('returns default styling for unknown types', () => {
      expect(getTypeBadge('unknown')).toBe('bg-surface text-text-muted border-border');
    });

    it('is case insensitive', () => {
      expect(getTypeBadge('INSIGHT')).toBe('bg-blue-500/20 text-blue-400 border-blue-500/30');
      expect(getTypeBadge('Pro')).toBe('bg-green-500/20 text-green-400 border-green-500/30');
    });
  });

  describe('getScoreColor', () => {
    it('returns green for high scores (>= 0.7)', () => {
      expect(getScoreColor(0.7)).toBe('text-green-400');
      expect(getScoreColor(0.9)).toBe('text-green-400');
      expect(getScoreColor(1.0)).toBe('text-green-400');
    });

    it('returns yellow for medium scores (0.4-0.69)', () => {
      expect(getScoreColor(0.4)).toBe('text-yellow-400');
      expect(getScoreColor(0.5)).toBe('text-yellow-400');
      expect(getScoreColor(0.69)).toBe('text-yellow-400');
    });

    it('returns red for low scores (< 0.4)', () => {
      expect(getScoreColor(0.39)).toBe('text-red-400');
      expect(getScoreColor(0.2)).toBe('text-red-400');
      expect(getScoreColor(0)).toBe('text-red-400');
    });

    it('normalizes percentage values (> 1) to decimal', () => {
      expect(getScoreColor(70)).toBe('text-green-400');
      expect(getScoreColor(50)).toBe('text-yellow-400');
      expect(getScoreColor(30)).toBe('text-red-400');
    });
  });

  describe('getInsightTypeColor', () => {
    it('returns correct styling for consensus', () => {
      expect(getInsightTypeColor('consensus')).toBe(
        'bg-green-500/20 text-green-400 border-green-500/30',
      );
    });

    it('returns correct styling for pattern', () => {
      expect(getInsightTypeColor('pattern')).toBe(
        'bg-blue-500/20 text-blue-400 border-blue-500/30',
      );
    });

    it('returns correct styling for agent_performance', () => {
      expect(getInsightTypeColor('agent_performance')).toBe(
        'bg-purple-500/20 text-purple-400 border-purple-500/30',
      );
    });

    it('returns correct styling for divergence', () => {
      expect(getInsightTypeColor('divergence')).toBe(
        'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
      );
    });

    it('returns gray styling for unknown types', () => {
      expect(getInsightTypeColor('unknown')).toBe(
        'bg-gray-500/20 text-gray-400 border-gray-500/30',
      );
    });
  });

  describe('getFlipTypeColor', () => {
    it('returns correct styling for contradiction', () => {
      expect(getFlipTypeColor('contradiction')).toBe(
        'bg-red-500/20 text-red-400 border-red-500/30',
      );
    });

    it('returns correct styling for retraction', () => {
      expect(getFlipTypeColor('retraction')).toBe(
        'bg-orange-500/20 text-orange-400 border-orange-500/30',
      );
    });

    it('returns correct styling for qualification', () => {
      expect(getFlipTypeColor('qualification')).toBe(
        'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
      );
    });

    it('returns correct styling for refinement', () => {
      expect(getFlipTypeColor('refinement')).toBe(
        'bg-green-500/20 text-green-400 border-green-500/30',
      );
    });

    it('returns gray styling for unknown types', () => {
      expect(getFlipTypeColor('unknown')).toBe('bg-gray-500/20 text-gray-400 border-gray-500/30');
    });
  });

  describe('getDomainColor', () => {
    it('returns correct styling for technical', () => {
      expect(getDomainColor('technical')).toBe('bg-blue-500/20 text-blue-400 border-blue-500/30');
    });

    it('returns correct styling for ethics', () => {
      expect(getDomainColor('ethics')).toBe(
        'bg-purple-500/20 text-purple-400 border-purple-500/30',
      );
    });

    it('returns correct styling for creative', () => {
      expect(getDomainColor('creative')).toBe('bg-pink-500/20 text-pink-400 border-pink-500/30');
    });

    it('returns correct styling for analytical', () => {
      expect(getDomainColor('analytical')).toBe('bg-cyan-500/20 text-cyan-400 border-cyan-500/30');
    });

    it('returns correct styling for general', () => {
      expect(getDomainColor('general')).toBe('bg-gray-500/20 text-gray-400 border-gray-500/30');
    });

    it('returns general styling for unknown domains', () => {
      expect(getDomainColor('unknown')).toBe('bg-gray-500/20 text-gray-400 border-gray-500/30');
    });
  });
});
