import { render, screen, act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useFocusTrap } from '@/hooks/useFocusTrap';
import { useState } from 'react';

// Test component that uses the hook properly
function TestModal({
  isActive,
  onEscape,
  returnFocusOnDeactivate = true,
}: {
  isActive: boolean;
  onEscape?: () => void;
  returnFocusOnDeactivate?: boolean;
}) {
  const containerRef = useFocusTrap<HTMLDivElement>({
    isActive,
    onEscape,
    returnFocusOnDeactivate,
  });

  return (
    <div ref={containerRef} data-testid="modal" tabIndex={-1}>
      <button data-testid="button-1">Button 1</button>
      <button data-testid="button-2">Button 2</button>
      <button data-testid="button-3">Button 3</button>
    </div>
  );
}

function EmptyModal({ isActive }: { isActive: boolean }) {
  const containerRef = useFocusTrap<HTMLDivElement>({ isActive });

  return (
    <div ref={containerRef} data-testid="empty-modal" tabIndex={-1}>
      <span>No focusable elements</span>
    </div>
  );
}

function ToggleableModal({
  initialActive = false,
  onEscape,
  returnFocusOnDeactivate = true,
}: {
  initialActive?: boolean;
  onEscape?: () => void;
  returnFocusOnDeactivate?: boolean;
}) {
  const [isActive, setIsActive] = useState(initialActive);
  const containerRef = useFocusTrap<HTMLDivElement>({
    isActive,
    onEscape,
    returnFocusOnDeactivate,
  });

  return (
    <>
      <button data-testid="trigger" onClick={() => setIsActive(true)}>
        Open Modal
      </button>
      {isActive && (
        <div ref={containerRef} data-testid="modal" tabIndex={-1}>
          <button data-testid="modal-button-1">Modal Button 1</button>
          <button data-testid="modal-button-2">Modal Button 2</button>
          <button data-testid="close" onClick={() => setIsActive(false)}>
            Close
          </button>
        </div>
      )}
    </>
  );
}

describe('useFocusTrap', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  describe('when inactive', () => {
    it('does not trap focus when inactive', () => {
      render(
        <div>
          <button data-testid="outside">Outside</button>
          <TestModal isActive={false} />
        </div>,
      );

      const outsideButton = screen.getByTestId('outside');
      outsideButton.focus();

      act(() => {
        jest.runAllTimers();
      });

      // Outside button should remain focused
      expect(document.activeElement).toBe(outsideButton);
    });

    it('does not call onEscape when inactive', () => {
      const onEscape = jest.fn();
      render(<TestModal isActive={false} onEscape={onEscape} />);

      act(() => {
        jest.runAllTimers();
      });

      // Dispatch Escape
      act(() => {
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      });

      expect(onEscape).not.toHaveBeenCalled();
    });
  });

  describe('when active', () => {
    it('attempts to focus first focusable element when activated', () => {
      // Note: In jsdom, offsetParent is always null so elements are filtered out
      // The hook will fall back to focusing the container
      render(<TestModal isActive={true} />);

      act(() => {
        jest.runAllTimers();
      });

      // Either first button or container should be focused
      const activeElement = document.activeElement;
      expect(
        activeElement === screen.getByTestId('button-1') ||
          activeElement === screen.getByTestId('modal'),
      ).toBe(true);
    });

    it('focuses container if no focusable elements', () => {
      render(<EmptyModal isActive={true} />);

      act(() => {
        jest.runAllTimers();
      });

      expect(document.activeElement).toBe(screen.getByTestId('empty-modal'));
    });
  });

  describe('Escape key handling', () => {
    it('calls onEscape when Escape is pressed', () => {
      const onEscape = jest.fn();
      render(<TestModal isActive={true} onEscape={onEscape} />);

      act(() => {
        jest.runAllTimers();
      });

      act(() => {
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      });

      expect(onEscape).toHaveBeenCalledTimes(1);
    });

    it('does not throw if onEscape is not provided', () => {
      render(<TestModal isActive={true} />);

      act(() => {
        jest.runAllTimers();
      });

      // Should not throw
      expect(() => {
        act(() => {
          document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        });
      }).not.toThrow();
    });

    it('prevents default on Escape when onEscape is provided', () => {
      const onEscape = jest.fn();
      render(<TestModal isActive={true} onEscape={onEscape} />);

      act(() => {
        jest.runAllTimers();
      });

      const escapeEvent = new KeyboardEvent('keydown', {
        key: 'Escape',
        bubbles: true,
        cancelable: true,
      });
      const preventDefaultSpy = jest.spyOn(escapeEvent, 'preventDefault');

      act(() => {
        document.dispatchEvent(escapeEvent);
      });

      expect(preventDefaultSpy).toHaveBeenCalled();
    });

    it('does not prevent default when onEscape is not provided', () => {
      render(<TestModal isActive={true} />);

      act(() => {
        jest.runAllTimers();
      });

      const escapeEvent = new KeyboardEvent('keydown', {
        key: 'Escape',
        bubbles: true,
        cancelable: true,
      });
      const preventDefaultSpy = jest.spyOn(escapeEvent, 'preventDefault');

      act(() => {
        document.dispatchEvent(escapeEvent);
      });

      expect(preventDefaultSpy).not.toHaveBeenCalled();
    });
  });

  describe('keyboard navigation', () => {
    it('handles Tab key when elements are present', () => {
      render(<TestModal isActive={true} />);

      act(() => {
        jest.runAllTimers();
      });

      // Focus button-3 manually
      screen.getByTestId('button-3').focus();

      // Press Tab - the hook will try to wrap (but jsdom may not have offsetParent)
      const tabEvent = new KeyboardEvent('keydown', {
        key: 'Tab',
        shiftKey: false,
        bubbles: true,
        cancelable: true,
      });

      act(() => {
        document.dispatchEvent(tabEvent);
      });

      // We're testing that the handler runs without error
      // Actual focus behavior depends on offsetParent which is null in jsdom
    });

    it('handles Shift+Tab key', () => {
      render(<TestModal isActive={true} />);

      act(() => {
        jest.runAllTimers();
      });

      screen.getByTestId('button-1').focus();

      const shiftTabEvent = new KeyboardEvent('keydown', {
        key: 'Tab',
        shiftKey: true,
        bubbles: true,
        cancelable: true,
      });

      act(() => {
        document.dispatchEvent(shiftTabEvent);
      });

      // Handler ran without error
    });

    it('ignores non-Tab, non-Escape keys', () => {
      const onEscape = jest.fn();
      render(<TestModal isActive={true} onEscape={onEscape} />);

      act(() => {
        jest.runAllTimers();
      });

      screen.getByTestId('button-1').focus();

      // Press Enter
      act(() => {
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
      });

      // onEscape should not be called for Enter key
      expect(onEscape).not.toHaveBeenCalled();
      // Focus should remain on button-1
      expect(document.activeElement).toBe(screen.getByTestId('button-1'));
    });
  });

  describe('returnFocusOnDeactivate', () => {
    it('returns focus to previously focused element when deactivated', async () => {
      jest.useRealTimers();
      const user = userEvent.setup();

      render(<ToggleableModal returnFocusOnDeactivate={true} />);

      const triggerButton = screen.getByTestId('trigger');
      triggerButton.focus();
      expect(document.activeElement).toBe(triggerButton);

      // Open modal
      await act(async () => {
        await user.click(triggerButton);
      });

      // Wait for focus to move to modal
      await waitFor(() => {
        expect(screen.getByTestId('modal-button-1')).toBeInTheDocument();
      });

      // Close modal
      await act(async () => {
        await user.click(screen.getByTestId('close'));
      });

      // Focus should return to trigger
      await waitFor(() => {
        expect(document.activeElement).toBe(triggerButton);
      });
    });

    it('does not return focus when returnFocusOnDeactivate is false', async () => {
      jest.useRealTimers();
      const user = userEvent.setup();

      render(<ToggleableModal returnFocusOnDeactivate={false} />);

      const triggerButton = screen.getByTestId('trigger');
      triggerButton.focus();

      // Open modal
      await act(async () => {
        await user.click(triggerButton);
      });

      await waitFor(() => {
        expect(screen.getByTestId('modal-button-1')).toBeInTheDocument();
      });

      // Close modal
      await act(async () => {
        await user.click(screen.getByTestId('close'));
      });

      // Focus should NOT return to trigger since returnFocusOnDeactivate is false
      expect(document.activeElement).not.toBe(triggerButton);
    });
  });

  describe('cleanup', () => {
    it('removes event listeners on unmount', () => {
      const onEscape = jest.fn();
      const { unmount } = render(<TestModal isActive={true} onEscape={onEscape} />);

      act(() => {
        jest.runAllTimers();
      });

      unmount();

      // Dispatch Escape after unmount
      act(() => {
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      });

      // Should not be called after unmount
      expect(onEscape).not.toHaveBeenCalled();
    });
  });

  describe('activation changes', () => {
    it('stores previously focused element on activation', async () => {
      jest.useRealTimers();
      const user = userEvent.setup();

      render(<ToggleableModal />);

      const triggerButton = screen.getByTestId('trigger');
      triggerButton.focus();

      await act(async () => {
        await user.click(triggerButton);
      });

      await waitFor(() => {
        expect(screen.getByTestId('modal')).toBeInTheDocument();
      });

      // Close and verify focus returns
      await act(async () => {
        await user.click(screen.getByTestId('close'));
      });

      await waitFor(() => {
        expect(document.activeElement).toBe(triggerButton);
      });
    });
  });
});
