import type { ReactNode } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { DebateResultPreview, type DebateResponse } from '../DebateResultPreview';

jest.mock('next/link', () => {
  const MockLink = ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  );
  MockLink.displayName = 'MockLink';
  return MockLink;
});

const baseResult: DebateResponse = {
  id: 'debate-preview-1',
  topic: 'Should we keep the launch date?',
  status: 'completed',
  rounds_used: 2,
  consensus_reached: true,
  confidence: 0.82,
  verdict: 'approve',
  duration_seconds: 4.2,
  participants: ['analyst', 'critic'],
  proposals: {
    analyst: 'Keep the launch date with the current mitigation plan.',
    critic: 'The schedule risk is manageable if the team freezes scope.',
  },
  critiques: [],
  votes: [],
  dissenting_views: [],
  final_answer: 'Keep the launch date with the current mitigation plan.',
  receipt: {
    receipt_id: 'receipt-1',
    question: 'Should we keep the launch date?',
    verdict: 'approve',
    confidence: 0.82,
    consensus: {
      reached: true,
      method: 'majority',
      confidence: 0.82,
      supporting_agents: ['analyst'],
      dissenting_agents: ['critic'],
    },
    agents: ['analyst', 'critic'],
    rounds_used: 2,
    timestamp: '2026-04-03T12:00:00Z',
    signature: null,
    signature_algorithm: null,
  },
  receipt_hash: 'hash-1',
};

describe('DebateResultPreview', () => {
  afterEach(() => {
    delete (navigator as Navigator & { share?: Navigator['share'] }).share;
    delete (navigator as Navigator & { clipboard?: Navigator['clipboard'] }).clipboard;
    jest.restoreAllMocks();
  });

  it('calls onShare once when native share succeeds', async () => {
    const onShare = jest.fn();
    const share = jest.fn().mockResolvedValue(undefined);
    const writeText = jest.fn().mockResolvedValue(undefined);

    Object.defineProperty(navigator, 'share', { configurable: true, value: share });
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });

    render(<DebateResultPreview result={baseResult} onShare={onShare} />);

    fireEvent.click(screen.getByRole('button', { name: 'SHARE THIS DEBATE' }));

    await waitFor(() => {
      expect(share).toHaveBeenCalledTimes(1);
      expect(onShare).toHaveBeenCalledTimes(1);
    });
    expect(writeText).not.toHaveBeenCalled();
  });
});
