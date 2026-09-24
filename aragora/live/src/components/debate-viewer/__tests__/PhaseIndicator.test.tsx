/**
 * Tests for PhaseIndicator component
 *
 * Tests cover:
 * - Default rendering
 * - Compact mode
 * - Progress display
 * - Complete state
 * - Phase transitions
 * - PhaseChip component
 */

import { render, screen } from '@testing-library/react';
import { PhaseIndicator, PhaseChip, DEBATE_PHASES } from '../PhaseIndicator';

describe('PhaseIndicator', () => {
  describe('default rendering', () => {
    it('renders round number and phase name', () => {
      render(<PhaseIndicator currentRound={0} />);

      expect(screen.getByText(/Round 0/)).toBeInTheDocument();
      expect(screen.getByText(/Context Gathering/)).toBeInTheDocument();
    });

    it('renders cognitive mode', () => {
      render(<PhaseIndicator currentRound={0} />);

      expect(screen.getByText(/Researcher Mode/)).toBeInTheDocument();
    });

    it('renders phase description', () => {
      render(<PhaseIndicator currentRound={0} />);

      expect(screen.getByText(/Gathering background information/)).toBeInTheDocument();
    });

    it('renders progress bar by default', () => {
      render(<PhaseIndicator currentRound={4} totalRounds={9} />);

      expect(screen.getByText('Progress')).toBeInTheDocument();
      // Round 5 of 9 = ~56%
      expect(screen.getByText('56%')).toBeInTheDocument();
    });
  });

  describe('phase progression', () => {
    it('shows Initial Analysis for round 1', () => {
      render(<PhaseIndicator currentRound={1} />);

      expect(screen.getByText(/Round 1/)).toBeInTheDocument();
      expect(screen.getByText(/Initial Analysis/)).toBeInTheDocument();
      expect(screen.getByText(/Analyst Mode/)).toBeInTheDocument();
    });

    it('shows Skeptical Review for round 2', () => {
      render(<PhaseIndicator currentRound={2} />);

      expect(screen.getByText(/Round 2/)).toBeInTheDocument();
      expect(screen.getByText(/Skeptical Review/)).toBeInTheDocument();
    });

    it('shows Final Adjudication for round 8', () => {
      render(<PhaseIndicator currentRound={8} />);

      expect(screen.getByText(/Round 8/)).toBeInTheDocument();
      expect(screen.getByText(/Final Adjudication/)).toBeInTheDocument();
    });

    it('handles out of bounds round by using last phase', () => {
      render(<PhaseIndicator currentRound={100} />);

      // Should show last phase (Final Adjudication)
      expect(screen.getByText(/Final Adjudication/)).toBeInTheDocument();
    });
  });

  describe('complete state', () => {
    it('shows COMPLETE badge when isComplete is true', () => {
      render(<PhaseIndicator currentRound={8} isComplete={true} />);

      expect(screen.getByText('COMPLETE')).toBeInTheDocument();
    });

    it('does not show COMPLETE badge when isComplete is false', () => {
      render(<PhaseIndicator currentRound={8} isComplete={false} />);

      expect(screen.queryByText('COMPLETE')).not.toBeInTheDocument();
    });
  });

  describe('compact mode', () => {
    it('renders in compact format', () => {
      render(<PhaseIndicator currentRound={2} compact={true} />);

      expect(screen.getByText(/R2:/)).toBeInTheDocument();
      expect(screen.getByText(/Skeptical Review/)).toBeInTheDocument();
    });

    it('shows [COMPLETE] in compact mode when complete', () => {
      render(<PhaseIndicator currentRound={8} compact={true} isComplete={true} />);

      expect(screen.getByText('[COMPLETE]')).toBeInTheDocument();
    });

    it('does not show progress bar in compact mode', () => {
      render(<PhaseIndicator currentRound={4} compact={true} />);

      expect(screen.queryByText('Progress')).not.toBeInTheDocument();
    });
  });

  describe('progress bar', () => {
    it('calculates progress correctly', () => {
      render(<PhaseIndicator currentRound={3} totalRounds={9} />);

      // Round 4 of 9 = 44%
      expect(screen.getByText('44%')).toBeInTheDocument();
    });

    it('shows 100% when complete', () => {
      render(<PhaseIndicator currentRound={8} totalRounds={9} isComplete={true} />);

      expect(screen.getByText('100%')).toBeInTheDocument();
    });

    it('hides progress bar when showProgress is false', () => {
      render(<PhaseIndicator currentRound={4} showProgress={false} />);

      expect(screen.queryByText('Progress')).not.toBeInTheDocument();
    });

    it('renders phase markers', () => {
      const { container } = render(<PhaseIndicator currentRound={4} />);

      // Should have 9 phase markers
      const markers = container.querySelectorAll('[title^="R"]');
      expect(markers.length).toBe(9);
    });
  });

  describe('emojis', () => {
    it('renders emoji for each phase', () => {
      DEBATE_PHASES.forEach((phase, index) => {
        const { container } = render(<PhaseIndicator currentRound={index} />);
        expect(container.textContent).toContain(phase.emoji);
      });
    });
  });
});

describe('PhaseChip', () => {
  it('renders round number', () => {
    render(<PhaseChip round={3} />);

    expect(screen.getByText(/R3/)).toBeInTheDocument();
  });

  it('renders emoji for the phase', () => {
    const { container } = render(<PhaseChip round={0} />);

    // Magnifying glass emoji for round 0
    expect(container.textContent).toContain(DEBATE_PHASES[0].emoji);
  });

  it('has title with phase description', () => {
    render(<PhaseChip round={2} />);

    const chip = screen.getByText(/R2/).closest('span');
    expect(chip).toHaveAttribute('title', DEBATE_PHASES[2].description);
  });

  it('handles out of bounds round', () => {
    render(<PhaseChip round={99} />);

    // Should show last phase emoji
    expect(screen.getByText(/R99/)).toBeInTheDocument();
  });
});

describe('DEBATE_PHASES constant', () => {
  it('has 9 phases', () => {
    expect(DEBATE_PHASES).toHaveLength(9);
  });

  it('phases are numbered 0-8', () => {
    DEBATE_PHASES.forEach((phase, index) => {
      expect(phase.number).toBe(index);
    });
  });

  it('each phase has required properties', () => {
    DEBATE_PHASES.forEach((phase) => {
      expect(phase).toHaveProperty('number');
      expect(phase).toHaveProperty('name');
      expect(phase).toHaveProperty('emoji');
      expect(phase).toHaveProperty('cognitiveMode');
      expect(phase).toHaveProperty('description');
    });
  });
});
