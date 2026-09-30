import { render, screen } from '@testing-library/react';

import { NextStepsPanel } from '../NextStepsPanel';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({
    href,
    children,
    className,
  }: {
    href: string;
    children: React.ReactNode;
    className?: string;
  }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

jest.mock('@/lib/api', () => ({ apiFetch: jest.fn() }));

describe('NextStepsPanel', () => {
  it('routes receipt navigation through the debate detail receipt tab', () => {
    render(<NextStepsPanel debateId="debate-123" />);

    const link = screen.getByRole('link', { name: /view receipt/i });
    expect(link).toHaveAttribute('href', '/debates/debate-123?tab=receipt');
  });
});
