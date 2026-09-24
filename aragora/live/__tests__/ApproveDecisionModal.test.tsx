/**
 * Tests for the 3-way ApproveDecisionModal.
 *
 * Covers the four decision paths + the keyboard shortcuts required by
 * the Mode 3 UI design:
 *
 *   g          → Generate brief first
 *   a          → Approve anyway
 *   Esc        → Cancel
 *   click      → button click parity with keyboard
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { ApproveDecisionModal } from '../src/components/review-queue/ApproveDecisionModal';

describe('ApproveDecisionModal', () => {
  const baseProps = {
    prNumber: 6389,
    onGenerate: jest.fn(),
    onApproveAnyway: jest.fn(),
    onClose: jest.fn(),
  };

  beforeEach(() => {
    baseProps.onGenerate.mockReset();
    baseProps.onApproveAnyway.mockReset();
    baseProps.onClose.mockReset();
  });

  it('renders dialog metadata with the PR number', () => {
    render(<ApproveDecisionModal {...baseProps} state="absent" />);
    const dialog = screen.getByTestId('approve-decision-modal-6389');
    expect(dialog).toHaveAttribute('role', 'dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toHaveAttribute('aria-labelledby');
    expect(screen.getByText(/Approve PR #6389\?/)).toBeInTheDocument();
  });

  it('clicking Generate triggers onGenerate', () => {
    render(<ApproveDecisionModal {...baseProps} state="absent" />);
    fireEvent.click(screen.getByTestId('approve-decision-generate-6389'));
    expect(baseProps.onGenerate).toHaveBeenCalledTimes(1);
    expect(baseProps.onApproveAnyway).not.toHaveBeenCalled();
    expect(baseProps.onClose).not.toHaveBeenCalled();
  });

  it('clicking Approve anyway triggers onApproveAnyway', () => {
    render(<ApproveDecisionModal {...baseProps} state="running" />);
    fireEvent.click(screen.getByTestId('approve-decision-approve-anyway-6389'));
    expect(baseProps.onApproveAnyway).toHaveBeenCalledTimes(1);
  });

  it('clicking Cancel triggers onClose', () => {
    render(<ApproveDecisionModal {...baseProps} state="queued" />);
    fireEvent.click(screen.getByTestId('approve-decision-cancel-6389'));
    expect(baseProps.onClose).toHaveBeenCalledTimes(1);
  });

  it('clicking the backdrop triggers onClose', () => {
    render(<ApproveDecisionModal {...baseProps} state="queued" />);
    fireEvent.click(screen.getByTestId('approve-decision-backdrop'));
    expect(baseProps.onClose).toHaveBeenCalledTimes(1);
  });

  it('"g" shortcut triggers onGenerate', () => {
    render(<ApproveDecisionModal {...baseProps} state="absent" />);
    fireEvent.keyDown(window, { key: 'g' });
    expect(baseProps.onGenerate).toHaveBeenCalledTimes(1);
  });

  it('"a" shortcut triggers onApproveAnyway', () => {
    render(<ApproveDecisionModal {...baseProps} state="absent" />);
    fireEvent.keyDown(window, { key: 'a' });
    expect(baseProps.onApproveAnyway).toHaveBeenCalledTimes(1);
  });

  it('"Escape" shortcut triggers onClose', () => {
    render(<ApproveDecisionModal {...baseProps} state="running" />);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(baseProps.onClose).toHaveBeenCalledTimes(1);
  });

  it('renders retry copy when state is failed', () => {
    render(<ApproveDecisionModal {...baseProps} state="failed" />);
    expect(screen.getByTestId('approve-decision-generate-6389')).toHaveTextContent(
      /Retry generation/i,
    );
  });

  it('renders regenerate copy when state is stale', () => {
    render(<ApproveDecisionModal {...baseProps} state="stale" />);
    expect(screen.getByTestId('approve-decision-generate-6389')).toHaveTextContent(/Regenerate/i);
  });

  it('renders verdict disagreement copy when state is ready but verdict disagrees', () => {
    render(<ApproveDecisionModal {...baseProps} state="ready" verdict="needs_human_attention" />);
    expect(screen.getByTestId('approve-decision-modal-6389')).toHaveTextContent(
      /needs_human_attention/,
    );
  });

  it('removes window keydown listener on unmount', () => {
    const { unmount } = render(<ApproveDecisionModal {...baseProps} state="absent" />);
    unmount();
    // After unmount, pressing 'g' should not call onGenerate.
    fireEvent.keyDown(window, { key: 'g' });
    expect(baseProps.onGenerate).not.toHaveBeenCalled();
  });
});
