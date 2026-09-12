/**
 * Tests for ProtectedRoute component
 *
 * Tests cover:
 * - Loading state during auth check
 * - Redirect when not authenticated
 * - Render children when authenticated
 * - Custom redirect path
 * - Tier requirements and upgrade prompt
 */

import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { ProtectedRoute } from '../ProtectedRoute';

// Mock dependencies
jest.mock('next/navigation', () => ({ useRouter: jest.fn(() => ({ push: jest.fn() })) }));

jest.mock('@/context/AuthContext', () => ({ useAuth: jest.fn() }));

jest.mock('@/components/MatrixRain', () => ({
  Scanlines: () => <div data-testid="scanlines" />,
  CRTVignette: () => <div data-testid="crt-vignette" />,
}));

import { useRouter } from 'next/navigation';
import { useAuth } from '@/context/AuthContext';

const mockUseRouter = useRouter as jest.Mock;
const mockUseAuth = useAuth as jest.Mock;

describe('ProtectedRoute', () => {
  const mockPush = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    mockUseRouter.mockReturnValue({ push: mockPush });
  });

  describe('Loading State', () => {
    it('shows loading state while auth is checking', () => {
      mockUseAuth.mockReturnValue({ isAuthenticated: false, isLoading: true, organization: null });

      render(
        <ProtectedRoute>
          <div>Protected Content</div>
        </ProtectedRoute>,
      );

      expect(screen.getByText('AUTHENTICATING...')).toBeInTheDocument();
      expect(screen.getByText('Verifying credentials')).toBeInTheDocument();
      expect(screen.queryByText('Protected Content')).not.toBeInTheDocument();
    });
  });

  describe('Not Authenticated', () => {
    beforeEach(() => {
      mockUseAuth.mockReturnValue({ isAuthenticated: false, isLoading: false, organization: null });
    });

    it('shows authentication required message', () => {
      render(
        <ProtectedRoute>
          <div>Protected Content</div>
        </ProtectedRoute>,
      );

      expect(screen.getByText('AUTHENTICATION REQUIRED')).toBeInTheDocument();
      expect(screen.getByText('Redirecting to login...')).toBeInTheDocument();
    });

    it('redirects to login with return URL', async () => {
      render(
        <ProtectedRoute>
          <div>Protected Content</div>
        </ProtectedRoute>,
      );

      await waitFor(() => {
        expect(mockPush).toHaveBeenCalled();
        expect(mockPush.mock.calls[0][0]).toMatch(/^\/auth\/login\?returnUrl=/);
      });
    });

    it('uses custom redirectTo path', async () => {
      render(
        <ProtectedRoute redirectTo="/custom-return">
          <div>Protected Content</div>
        </ProtectedRoute>,
      );

      await waitFor(() => {
        expect(mockPush).toHaveBeenCalledWith('/auth/login?returnUrl=%2Fcustom-return');
      });
    });

    it('does not render children', () => {
      render(
        <ProtectedRoute>
          <div>Protected Content</div>
        </ProtectedRoute>,
      );

      expect(screen.queryByText('Protected Content')).not.toBeInTheDocument();
    });
  });

  describe('Authenticated', () => {
    it('renders children when authenticated without tier requirement', () => {
      mockUseAuth.mockReturnValue({
        isAuthenticated: true,
        isLoading: false,
        organization: { tier: 'starter' },
      });

      render(
        <ProtectedRoute>
          <div>Protected Content</div>
        </ProtectedRoute>,
      );

      expect(screen.getByText('Protected Content')).toBeInTheDocument();
    });

    it('does not redirect when authenticated', () => {
      mockUseAuth.mockReturnValue({
        isAuthenticated: true,
        isLoading: false,
        organization: { tier: 'professional' },
      });

      render(
        <ProtectedRoute>
          <div>Protected Content</div>
        </ProtectedRoute>,
      );

      expect(mockPush).not.toHaveBeenCalled();
    });
  });

  describe('Tier Requirements', () => {
    describe('when user meets tier requirement', () => {
      it('renders children for same tier', () => {
        mockUseAuth.mockReturnValue({
          isAuthenticated: true,
          isLoading: false,
          organization: { tier: 'professional' },
        });

        render(
          <ProtectedRoute requiredTier="professional">
            <div>Pro Content</div>
          </ProtectedRoute>,
        );

        expect(screen.getByText('Pro Content')).toBeInTheDocument();
      });

      it('renders children for higher tier', () => {
        mockUseAuth.mockReturnValue({
          isAuthenticated: true,
          isLoading: false,
          organization: { tier: 'enterprise' },
        });

        render(
          <ProtectedRoute requiredTier="professional">
            <div>Pro Content</div>
          </ProtectedRoute>,
        );

        expect(screen.getByText('Pro Content')).toBeInTheDocument();
      });
    });

    describe('when user does not meet tier requirement', () => {
      it('shows upgrade required message for lower tier', () => {
        mockUseAuth.mockReturnValue({
          isAuthenticated: true,
          isLoading: false,
          organization: { tier: 'starter' },
        });

        render(
          <ProtectedRoute requiredTier="professional">
            <div>Pro Content</div>
          </ProtectedRoute>,
        );

        expect(screen.getByText('UPGRADE REQUIRED')).toBeInTheDocument();
        expect(
          screen.getByText(/This feature requires the PROFESSIONAL tier or higher/),
        ).toBeInTheDocument();
        expect(screen.getByText(/Your current tier: STARTER/)).toBeInTheDocument();
      });

      it('shows upgrade required for free tier', () => {
        mockUseAuth.mockReturnValue({
          isAuthenticated: true,
          isLoading: false,
          organization: { tier: 'free' },
        });

        render(
          <ProtectedRoute requiredTier="starter">
            <div>Starter Content</div>
          </ProtectedRoute>,
        );

        expect(screen.getByText('UPGRADE REQUIRED')).toBeInTheDocument();
      });

      it('renders view plans button', () => {
        mockUseAuth.mockReturnValue({
          isAuthenticated: true,
          isLoading: false,
          organization: { tier: 'starter' },
        });

        render(
          <ProtectedRoute requiredTier="enterprise">
            <div>Enterprise Content</div>
          </ProtectedRoute>,
        );

        const button = screen.getByText('[VIEW PLANS]');
        expect(button).toBeInTheDocument();
      });

      it('navigates to pricing on button click', async () => {
        mockUseAuth.mockReturnValue({
          isAuthenticated: true,
          isLoading: false,
          organization: { tier: 'starter' },
        });

        render(
          <ProtectedRoute requiredTier="enterprise">
            <div>Enterprise Content</div>
          </ProtectedRoute>,
        );

        const button = screen.getByText('[VIEW PLANS]');
        button.click();

        expect(mockPush).toHaveBeenCalledWith('/pricing');
      });

      it('does not render children when tier requirement not met', () => {
        mockUseAuth.mockReturnValue({
          isAuthenticated: true,
          isLoading: false,
          organization: { tier: 'starter' },
        });

        render(
          <ProtectedRoute requiredTier="enterprise">
            <div>Enterprise Content</div>
          </ProtectedRoute>,
        );

        expect(screen.queryByText('Enterprise Content')).not.toBeInTheDocument();
      });
    });
  });

  describe('Edge Cases', () => {
    it('renders children when no organization but no tier required', () => {
      mockUseAuth.mockReturnValue({ isAuthenticated: true, isLoading: false, organization: null });

      render(
        <ProtectedRoute>
          <div>Content</div>
        </ProtectedRoute>,
      );

      expect(screen.getByText('Content')).toBeInTheDocument();
    });

    it('renders children when tier required but no organization', () => {
      // Edge case: authenticated but no org data yet
      mockUseAuth.mockReturnValue({ isAuthenticated: true, isLoading: false, organization: null });

      render(
        <ProtectedRoute requiredTier="professional">
          <div>Content</div>
        </ProtectedRoute>,
      );

      // Should render since we can't check tier without org
      expect(screen.getByText('Content')).toBeInTheDocument();
    });
  });
});
