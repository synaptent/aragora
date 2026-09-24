/**
 * Tests for AccessibleOverlay component
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { AccessibleOverlay, ModalBackdrop } from '@/components/shared/AccessibleOverlay';

describe('AccessibleOverlay', () => {
  const mockOnClose = jest.fn();

  beforeEach(() => {
    mockOnClose.mockClear();
  });

  it('renders when isOpen is true', () => {
    render(
      <AccessibleOverlay onClose={mockOnClose} isOpen={true}>
        <div data-testid="content">Modal content</div>
      </AccessibleOverlay>,
    );

    expect(screen.getByTestId('content')).toBeInTheDocument();
  });

  it('does not render when isOpen is false', () => {
    render(
      <AccessibleOverlay onClose={mockOnClose} isOpen={false}>
        <div data-testid="content">Modal content</div>
      </AccessibleOverlay>,
    );

    expect(screen.queryByTestId('content')).not.toBeInTheDocument();
  });

  it('has correct ARIA attributes', () => {
    render(
      <AccessibleOverlay onClose={mockOnClose} ariaLabel="Test modal">
        <div>Content</div>
      </AccessibleOverlay>,
    );

    const overlay = screen.getByRole('dialog');
    expect(overlay).toHaveAttribute('aria-modal', 'true');
    expect(overlay).toHaveAttribute('aria-label', 'Test modal');
  });

  it('calls onClose when Escape is pressed', () => {
    render(
      <AccessibleOverlay onClose={mockOnClose}>
        <div>Content</div>
      </AccessibleOverlay>,
    );

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(mockOnClose).toHaveBeenCalledTimes(1);
  });

  it('calls onClose when overlay background is clicked', () => {
    render(
      <AccessibleOverlay onClose={mockOnClose}>
        <div data-testid="content">Content</div>
      </AccessibleOverlay>,
    );

    const overlay = screen.getByRole('dialog');
    fireEvent.click(overlay);

    expect(mockOnClose).toHaveBeenCalledTimes(1);
  });

  it('does not call onClose when content is clicked', () => {
    render(
      <AccessibleOverlay onClose={mockOnClose}>
        <div data-testid="content" onClick={(e) => e.stopPropagation()}>
          Content
        </div>
      </AccessibleOverlay>,
    );

    fireEvent.click(screen.getByTestId('content'));

    expect(mockOnClose).not.toHaveBeenCalled();
  });

  it('applies custom className', () => {
    render(
      <AccessibleOverlay onClose={mockOnClose} className="custom-class">
        <div>Content</div>
      </AccessibleOverlay>,
    );

    const overlay = screen.getByRole('dialog');
    expect(overlay).toHaveClass('custom-class');
  });

  it('uses default ariaLabel when not provided', () => {
    render(
      <AccessibleOverlay onClose={mockOnClose}>
        <div>Content</div>
      </AccessibleOverlay>,
    );

    const overlay = screen.getByRole('dialog');
    expect(overlay).toHaveAttribute('aria-label', 'Close modal');
  });
});

describe('ModalBackdrop', () => {
  const mockOnClose = jest.fn();

  beforeEach(() => {
    mockOnClose.mockClear();
  });

  it('renders with role button', () => {
    render(<ModalBackdrop onClose={mockOnClose} />);

    expect(screen.getByRole('button')).toBeInTheDocument();
  });

  it('has aria-label for screen readers', () => {
    render(<ModalBackdrop onClose={mockOnClose} />);

    expect(screen.getByRole('button')).toHaveAttribute('aria-label', 'Close modal');
  });

  it('is keyboard focusable', () => {
    render(<ModalBackdrop onClose={mockOnClose} />);

    expect(screen.getByRole('button')).toHaveAttribute('tabIndex', '0');
  });

  it('calls onClose when clicked', () => {
    render(<ModalBackdrop onClose={mockOnClose} />);

    fireEvent.click(screen.getByRole('button'));

    expect(mockOnClose).toHaveBeenCalledTimes(1);
  });

  it('calls onClose on Escape key', () => {
    render(<ModalBackdrop onClose={mockOnClose} />);

    fireEvent.keyDown(screen.getByRole('button'), { key: 'Escape' });

    expect(mockOnClose).toHaveBeenCalledTimes(1);
  });

  it('applies custom className', () => {
    render(<ModalBackdrop onClose={mockOnClose} className="custom-backdrop" />);

    expect(screen.getByRole('button')).toHaveClass('custom-backdrop');
  });
});
