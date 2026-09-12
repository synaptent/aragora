/**
 * Tests for SidebarContext
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { SidebarProvider, useSidebar } from '../SidebarContext';

// Test component that uses the sidebar context
function TestConsumer() {
  const { isOpen, open, close, toggle } = useSidebar();
  return (
    <div>
      <span data-testid="status">{isOpen ? 'open' : 'closed'}</span>
      <button onClick={open}>Open</button>
      <button onClick={close}>Close</button>
      <button onClick={toggle}>Toggle</button>
    </div>
  );
}

describe('SidebarContext', () => {
  beforeEach(() => {
    document.body.style.overflow = '';
  });

  describe('SidebarProvider', () => {
    it('provides initial closed state', () => {
      render(
        <SidebarProvider>
          <TestConsumer />
        </SidebarProvider>,
      );

      expect(screen.getByTestId('status')).toHaveTextContent('closed');
    });

    it('opens sidebar when open is called', () => {
      render(
        <SidebarProvider>
          <TestConsumer />
        </SidebarProvider>,
      );

      fireEvent.click(screen.getByText('Open'));
      expect(screen.getByTestId('status')).toHaveTextContent('open');
    });

    it('closes sidebar when close is called', () => {
      render(
        <SidebarProvider>
          <TestConsumer />
        </SidebarProvider>,
      );

      fireEvent.click(screen.getByText('Open'));
      expect(screen.getByTestId('status')).toHaveTextContent('open');

      fireEvent.click(screen.getByText('Close'));
      expect(screen.getByTestId('status')).toHaveTextContent('closed');
    });

    it('toggles sidebar when toggle is called', () => {
      render(
        <SidebarProvider>
          <TestConsumer />
        </SidebarProvider>,
      );

      expect(screen.getByTestId('status')).toHaveTextContent('closed');

      fireEvent.click(screen.getByText('Toggle'));
      expect(screen.getByTestId('status')).toHaveTextContent('open');

      fireEvent.click(screen.getByText('Toggle'));
      expect(screen.getByTestId('status')).toHaveTextContent('closed');
    });

    it('closes sidebar on Escape key', () => {
      render(
        <SidebarProvider>
          <TestConsumer />
        </SidebarProvider>,
      );

      fireEvent.click(screen.getByText('Open'));
      expect(screen.getByTestId('status')).toHaveTextContent('open');

      fireEvent.keyDown(document, { key: 'Escape' });
      expect(screen.getByTestId('status')).toHaveTextContent('closed');
    });

    it('does not close on Escape when already closed', () => {
      render(
        <SidebarProvider>
          <TestConsumer />
        </SidebarProvider>,
      );

      expect(screen.getByTestId('status')).toHaveTextContent('closed');
      fireEvent.keyDown(document, { key: 'Escape' });
      expect(screen.getByTestId('status')).toHaveTextContent('closed');
    });

    it('prevents body scroll when open', () => {
      render(
        <SidebarProvider>
          <TestConsumer />
        </SidebarProvider>,
      );

      expect(document.body.style.overflow).toBe('');

      fireEvent.click(screen.getByText('Open'));
      expect(document.body.style.overflow).toBe('hidden');

      fireEvent.click(screen.getByText('Close'));
      expect(document.body.style.overflow).toBe('');
    });
  });

  describe('useSidebar', () => {
    it('throws error when used outside provider', () => {
      // Suppress console.error for this test
      const consoleSpy = jest.spyOn(console, 'error').mockImplementation();

      expect(() => {
        render(<TestConsumer />);
      }).toThrow('useSidebar must be used within a SidebarProvider');

      consoleSpy.mockRestore();
    });
  });
});
