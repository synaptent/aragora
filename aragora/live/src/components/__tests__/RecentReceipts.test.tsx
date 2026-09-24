import { render, screen, waitFor } from '@testing-library/react';
import { RecentReceipts } from '../RecentReceipts';
import { apiFetch } from '@/lib/api';

jest.mock('next/link', () => {
  return function MockLink({
    children,
    href,
    className,
  }: {
    children: React.ReactNode;
    href: string;
    className?: string;
  }) {
    return (
      <a href={href} className={className}>
        {children}
      </a>
    );
  };
});

jest.mock('@/lib/api', () => ({ apiFetch: jest.fn() }));

jest.mock('../DebateThisButton', () => ({
  DebateThisButton: ({ question }: { question: string }) => <button>{question}</button>,
}));

const mockApiFetch = apiFetch as jest.MockedFunction<typeof apiFetch>;

describe('RecentReceipts', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('loads recent receipts from the canonical v2 endpoint', async () => {
    mockApiFetch.mockResolvedValue({
      receipts: [
        {
          receipt_id: 'rcpt_12345678',
          gauntlet_id: 'gauntlet-123',
          timestamp: '2026-03-25T12:00:00Z',
          input_summary: 'Assess production founder loop readiness',
          verdict: 'APPROVED',
          findings_count: 2,
          confidence: 0.94,
        },
      ],
    } as never);

    render(<RecentReceipts limit={3} />);

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v2/receipts?limit=3');
    });

    expect(await screen.findByText('DECISION RECEIPTS')).toBeInTheDocument();
    expect(screen.getByText('PASS')).toBeInTheDocument();

    const link = screen.getByRole('link', { name: /Assess production founder loop readiness/i });
    expect(link).toHaveAttribute('href', '/receipts?id=rcpt_12345678');
    expect(screen.getByText('2 findings')).toBeInTheDocument();
  });

  it('falls back to a receipt id label when input_summary is absent', async () => {
    mockApiFetch.mockResolvedValue({
      receipts: [
        {
          receipt_id: 'rcpt_fallback99',
          verdict: 'REJECTED',
          findings_count: 0,
          confidence: 0.41,
          timestamp: '2026-03-25T12:00:00Z',
        },
      ],
    } as never);

    render(<RecentReceipts />);

    expect(await screen.findByText('FAIL')).toBeInTheDocument();
    expect(screen.getByText('Receipt rcpt_fal')).toBeInTheDocument();
  });
});
