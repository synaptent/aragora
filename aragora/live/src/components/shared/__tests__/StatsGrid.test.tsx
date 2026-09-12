import { render, screen } from '@testing-library/react';
import { StatsGrid, StatItem } from '../StatsGrid';

const mockStats: StatItem[] = [
  { value: 1500, label: 'Total Users' },
  { value: '85%', label: 'Success Rate' },
  { value: 42, label: 'Active Projects' },
];

describe('StatsGrid', () => {
  describe('rendering', () => {
    it('renders all stat items', () => {
      render(<StatsGrid stats={mockStats} />);

      expect(screen.getByText('1500')).toBeInTheDocument();
      expect(screen.getByText('85%')).toBeInTheDocument();
      expect(screen.getByText('42')).toBeInTheDocument();
    });

    it('renders stat labels', () => {
      render(<StatsGrid stats={mockStats} />);

      expect(screen.getByText('Total Users')).toBeInTheDocument();
      expect(screen.getByText('Success Rate')).toBeInTheDocument();
      expect(screen.getByText('Active Projects')).toBeInTheDocument();
    });

    it('handles numeric values', () => {
      const numericStats: StatItem[] = [
        { value: 0, label: 'Zero' },
        { value: 999999, label: 'Large Number' },
        { value: -10, label: 'Negative' },
      ];

      render(<StatsGrid stats={numericStats} />);

      expect(screen.getByText('0')).toBeInTheDocument();
      expect(screen.getByText('999999')).toBeInTheDocument();
      expect(screen.getByText('-10')).toBeInTheDocument();
    });

    it('handles string values', () => {
      const stringStats: StatItem[] = [
        { value: 'N/A', label: 'Status' },
        { value: '$1.2M', label: 'Revenue' },
      ];

      render(<StatsGrid stats={stringStats} />);

      expect(screen.getByText('N/A')).toBeInTheDocument();
      expect(screen.getByText('$1.2M')).toBeInTheDocument();
    });

    it('handles empty stats array', () => {
      const { container } = render(<StatsGrid stats={[]} />);

      // Grid container exists but empty
      expect(container.querySelector('.grid')).toBeInTheDocument();
      expect(container.querySelectorAll('.p-3')).toHaveLength(0);
    });
  });

  describe('columns', () => {
    it('defaults to 3 columns', () => {
      const { container } = render(<StatsGrid stats={mockStats} />);

      expect(container.querySelector('.grid-cols-3')).toBeInTheDocument();
    });

    it('renders with 2 columns', () => {
      const { container } = render(<StatsGrid stats={mockStats} columns={2} />);

      expect(container.querySelector('.grid-cols-2')).toBeInTheDocument();
    });

    it('renders with 3 columns', () => {
      const { container } = render(<StatsGrid stats={mockStats} columns={3} />);

      expect(container.querySelector('.grid-cols-3')).toBeInTheDocument();
    });

    it('renders with 4 columns', () => {
      const { container } = render(<StatsGrid stats={mockStats} columns={4} />);

      expect(container.querySelector('.grid-cols-4')).toBeInTheDocument();
    });
  });

  describe('colors', () => {
    it('uses default accent color when color not specified', () => {
      render(<StatsGrid stats={[{ value: 100, label: 'Test' }]} />);

      const valueElement = screen.getByText('100');
      expect(valueElement).toHaveClass('text-accent');
    });

    it('uses custom color when specified', () => {
      const statsWithColor: StatItem[] = [
        { value: 100, label: 'Green Stat', color: 'text-green-500' },
      ];

      render(<StatsGrid stats={statsWithColor} />);

      const valueElement = screen.getByText('100');
      expect(valueElement).toHaveClass('text-green-500');
    });

    it('applies different colors to different stats', () => {
      const coloredStats: StatItem[] = [
        { value: 10, label: 'Red', color: 'text-red-500' },
        { value: 20, label: 'Blue', color: 'text-blue-500' },
        { value: 30, label: 'Default' },
      ];

      render(<StatsGrid stats={coloredStats} />);

      expect(screen.getByText('10')).toHaveClass('text-red-500');
      expect(screen.getByText('20')).toHaveClass('text-blue-500');
      expect(screen.getByText('30')).toHaveClass('text-accent');
    });
  });

  describe('styling', () => {
    it('applies base grid styles', () => {
      const { container } = render(<StatsGrid stats={mockStats} />);

      expect(container.querySelector('.grid')).toBeInTheDocument();
      expect(container.querySelector('.gap-3')).toBeInTheDocument();
    });

    it('applies stat item container styles', () => {
      const { container } = render(<StatsGrid stats={mockStats} />);

      const statItems = container.querySelectorAll(
        '.p-3.bg-bg.border.border-border.rounded-lg.text-center',
      );
      expect(statItems).toHaveLength(3);
    });

    it('applies value text styles', () => {
      render(<StatsGrid stats={mockStats} />);

      const valueElement = screen.getByText('1500');
      expect(valueElement).toHaveClass('text-2xl', 'font-theme-data');
    });

    it('applies label text styles', () => {
      render(<StatsGrid stats={mockStats} />);

      const labelElement = screen.getByText('Total Users');
      expect(labelElement).toHaveClass('text-xs', 'text-text-muted');
    });
  });

  describe('custom className', () => {
    it('applies custom className to container', () => {
      const { container } = render(<StatsGrid stats={mockStats} className="my-custom-class" />);

      expect(container.querySelector('.my-custom-class')).toBeInTheDocument();
    });

    it('preserves grid classes with custom className', () => {
      const { container } = render(
        <StatsGrid stats={mockStats} className="my-custom-class" columns={2} />,
      );

      const grid = container.querySelector('.grid');
      expect(grid).toHaveClass('grid-cols-2', 'gap-3', 'my-custom-class');
    });
  });
});
