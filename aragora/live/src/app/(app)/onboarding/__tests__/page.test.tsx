import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import OnboardingPage from '../page';

const mockPush = jest.fn();
const mockFetch = jest.fn();

const mockUseAuth = jest.fn();
const mockUseBackend = jest.fn();
const mockUseDashboardPreferences = jest.fn();
const mockUseOnboarding = jest.fn();

global.fetch = mockFetch as typeof fetch;

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: mockPush }) }));

jest.mock('@/context/AuthContext', () => ({ useAuth: () => mockUseAuth() }));

jest.mock('@/components/BackendSelector', () => ({
  BACKENDS: { production: { api: 'https://api.aragora.ai' } },
  useBackend: () => mockUseBackend(),
}));

jest.mock('@/hooks/useDashboardPreferences', () => ({
  useDashboardPreferences: () => mockUseDashboardPreferences(),
}));

jest.mock('@/hooks/useOnboarding', () => ({ useOnboarding: () => mockUseOnboarding() }));

describe('OnboardingPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    sessionStorage.clear();

    mockUseAuth.mockReturnValue({ isAuthenticated: true, tokens: { access_token: 'token-123' } });
    mockUseBackend.mockReturnValue({
      config: { api: '', ws: 'ws://localhost:8766/api/control-plane/stream' },
    });
    mockUseDashboardPreferences.mockReturnValue({ markOnboardingComplete: jest.fn() });
    mockUseOnboarding.mockReturnValue({
      setSelectedIndustry: jest.fn(),
      setFirstDebateTopic: jest.fn(),
      setFirstDebateId: jest.fn(),
      setDebateStatus: jest.fn(),
      updateProgress: jest.fn(),
      updateChecklist: jest.fn(),
      completeOnboarding: jest.fn(),
      skipOnboarding: jest.fn(),
      initFlow: jest.fn(),
    });
  });

  it('uses the same-origin API path when the selected backend resolves to an empty local base', async () => {
    sessionStorage.setItem(
      'aragora_onboarding_question',
      'Should we raise our next round now or wait 6 months?',
    );
    sessionStorage.setItem('aragora_onboarding_role', 'ceo');

    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, debate_id: 'debate-123' }),
    });

    render(<OnboardingPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'LAUNCH DEBATE' }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/debate',
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({
            Authorization: 'Bearer token-123',
            'Content-Type': 'application/json',
          }),
        }),
      );
    });

    expect(mockFetch).not.toHaveBeenCalledWith(
      expect.stringContaining('https://api.aragora.ai/api/debate'),
      expect.anything(),
    );
    const [, requestInit] = mockFetch.mock.calls.at(-1) as [string, RequestInit];
    expect(JSON.parse(requestInit.body as string)).toEqual(
      expect.objectContaining({
        question: 'Should we raise our next round now or wait 6 months?',
        agents: ['anthropic-api', 'openai-api', 'mistral'],
      }),
    );
    expect(mockPush).toHaveBeenCalledWith('/debate/debate-123');
  });
});
