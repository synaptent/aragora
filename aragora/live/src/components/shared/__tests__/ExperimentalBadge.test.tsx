/**
 * Tests for ExperimentalBadge, ExperimentalTag, and ExperimentalBanner components
 *
 * Tests cover:
 * - Badge visibility for different statuses
 * - Status-specific styling
 * - Size variations
 * - Tooltip/title attributes
 */

import { render, screen } from '@testing-library/react';
import { ExperimentalBadge, ExperimentalTag, ExperimentalBanner } from '../ExperimentalBadge';

describe('ExperimentalBadge', () => {
  describe('visibility', () => {
    it('does not render for stable status', () => {
      const { container } = render(<ExperimentalBadge status="stable" />);
      expect(container.firstChild).toBeNull();
    });

    it('renders for beta status', () => {
      render(<ExperimentalBadge status="beta" />);
      expect(screen.getByText('BETA')).toBeInTheDocument();
    });

    it('renders for alpha status', () => {
      render(<ExperimentalBadge status="alpha" />);
      expect(screen.getByText('ALPHA')).toBeInTheDocument();
    });

    it('renders for deprecated status', () => {
      render(<ExperimentalBadge status="deprecated" />);
      expect(screen.getByText('DEPRECATED')).toBeInTheDocument();
    });
  });

  describe('styling', () => {
    it('applies beta colors', () => {
      render(<ExperimentalBadge status="beta" />);
      const badge = screen.getByText('BETA');
      expect(badge).toHaveClass('text-[var(--acid-cyan)]');
    });

    it('applies alpha colors', () => {
      render(<ExperimentalBadge status="alpha" />);
      const badge = screen.getByText('ALPHA');
      expect(badge).toHaveClass('text-[var(--acid-yellow)]');
    });

    it('applies deprecated colors', () => {
      render(<ExperimentalBadge status="deprecated" />);
      const badge = screen.getByText('DEPRECATED');
      expect(badge).toHaveClass('text-acid-red');
    });
  });

  describe('sizes', () => {
    it('applies medium size by default', () => {
      render(<ExperimentalBadge status="beta" />);
      const badge = screen.getByText('BETA');
      expect(badge).toHaveClass('text-[10px]');
    });

    it('applies small size', () => {
      render(<ExperimentalBadge status="beta" size="sm" />);
      const badge = screen.getByText('BETA');
      expect(badge).toHaveClass('text-[8px]');
    });
  });

  describe('tooltip', () => {
    it('has tooltip for beta status', () => {
      render(<ExperimentalBadge status="beta" />);
      const badge = screen.getByText('BETA');
      expect(badge).toHaveAttribute('title', expect.stringContaining('mostly complete'));
    });

    it('has tooltip for alpha status', () => {
      render(<ExperimentalBadge status="alpha" />);
      const badge = screen.getByText('ALPHA');
      expect(badge).toHaveAttribute('title', expect.stringContaining('experimental'));
    });

    it('has tooltip for deprecated status', () => {
      render(<ExperimentalBadge status="deprecated" />);
      const badge = screen.getByText('DEPRECATED');
      expect(badge).toHaveAttribute('title', expect.stringContaining('deprecated'));
    });
  });

  describe('custom className', () => {
    it('applies custom className', () => {
      render(<ExperimentalBadge status="beta" className="my-class" />);
      const badge = screen.getByText('BETA');
      expect(badge).toHaveClass('my-class');
    });
  });
});

describe('ExperimentalTag', () => {
  it('does not render for stable status', () => {
    const { container } = render(<ExperimentalTag status="stable" />);
    expect(container.firstChild).toBeNull();
  });

  it('renders bracketed label for beta', () => {
    render(<ExperimentalTag status="beta" />);
    expect(screen.getByText('[BETA]')).toBeInTheDocument();
  });

  it('renders bracketed label for alpha', () => {
    render(<ExperimentalTag status="alpha" />);
    expect(screen.getByText('[ALPHA]')).toBeInTheDocument();
  });

  it('has tooltip', () => {
    render(<ExperimentalTag status="alpha" />);
    const tag = screen.getByText('[ALPHA]');
    expect(tag).toHaveAttribute('title');
  });
});

describe('ExperimentalBanner', () => {
  it('does not render for stable status', () => {
    const { container } = render(<ExperimentalBanner status="stable" featureName="Test Feature" />);
    expect(container.firstChild).toBeNull();
  });

  it('renders for beta status with feature name', () => {
    render(<ExperimentalBanner status="beta" featureName="Graph Debates" />);
    expect(screen.getByText('BETA')).toBeInTheDocument();
    expect(screen.getByText('Graph Debates')).toBeInTheDocument();
  });

  it('shows tooltip text as description', () => {
    render(<ExperimentalBanner status="alpha" featureName="Test" />);
    expect(screen.getByText(/experimental/)).toBeInTheDocument();
  });

  it('contains nested ExperimentalBadge', () => {
    render(<ExperimentalBanner status="deprecated" featureName="Old Feature" />);
    expect(screen.getByText('DEPRECATED')).toBeInTheDocument();
    expect(screen.getByText('Old Feature')).toBeInTheDocument();
  });
});
