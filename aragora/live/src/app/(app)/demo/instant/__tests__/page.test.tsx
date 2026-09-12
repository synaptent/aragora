import { render, screen } from '@testing-library/react';
import InstantDemoPage from '../page';

jest.mock('next/link', () => {
  return function MockLink({ children, href }: { children: React.ReactNode; href: string }) {
    return <a href={href}>{children}</a>;
  };
});

jest.mock('@/components/MatrixRain', () => ({
  Scanlines: () => <div data-testid="scanlines" />,
  CRTVignette: () => <div data-testid="crt-vignette" />,
}));

describe('InstantDemoPage', () => {
  it('labels the replay as synthetic and avoids fake receipt claims', () => {
    render(<InstantDemoPage />);

    expect(
      screen.getByText(
        /Watch a cached synthetic replay of five models debating a sample decision\./i,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText('Synthetic Replay')).toBeInTheDocument();
    expect(
      screen.getByText(
        /This page is a scripted demonstration\. It does not publish a live receipt, proof link, or cryptographic artifact\./i,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Receipt sample/i)).not.toBeInTheDocument();
  });
});
