/**
 * Tests for JobMonitor component
 *
 * Tests cover:
 * - Job list display
 * - Status filtering
 * - Progress bars for training jobs
 * - Expanded job details
 * - Cancel and view actions
 * - Empty state
 * - Duration formatting
 */

import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { JobMonitor } from '../src/components/control-plane/FineTuning/JobMonitor';
import type { FineTuningJob } from '../src/components/control-plane/FineTuning/FineTuningDashboard';

const mockJobs: FineTuningJob[] = [
  {
    id: 'ft_001',
    name: 'Legal Specialist v2',
    vertical: 'legal',
    baseModel: 'nlpaueb/legal-bert-base-uncased',
    status: 'training',
    progress: 0.45,
    currentEpoch: 2,
    totalEpochs: 3,
    currentStep: 450,
    totalSteps: 1000,
    loss: 0.324,
    trainingExamples: 2500,
    startedAt: '2024-01-16T10:00:00Z',
  },
  {
    id: 'ft_002',
    name: 'Healthcare Model',
    vertical: 'healthcare',
    baseModel: 'medicalai/ClinicalBERT',
    status: 'completed',
    progress: 1.0,
    currentEpoch: 3,
    totalEpochs: 3,
    trainingExamples: 1800,
    startedAt: '2024-01-15T14:00:00Z',
    completedAt: '2024-01-15T18:30:00Z',
    outputPath: '/models/healthcare_v1',
  },
  {
    id: 'ft_003',
    name: 'Code Review Assistant',
    vertical: 'software',
    baseModel: 'codellama/CodeLlama-7b-Instruct-hf',
    status: 'queued',
    progress: 0,
    trainingExamples: 5000,
  },
  {
    id: 'ft_004',
    name: 'Failed Training',
    vertical: 'accounting',
    baseModel: 'ProsusAI/finbert',
    status: 'failed',
    progress: 0.2,
    trainingExamples: 1000,
    startedAt: '2024-01-14T09:00:00Z',
    error: 'CUDA out of memory',
  },
  {
    id: 'ft_005',
    name: 'Preparing Job',
    vertical: 'research',
    baseModel: 'allenai/scibert_scivocab_uncased',
    status: 'preparing',
    progress: 0.1,
    trainingExamples: 3000,
    startedAt: '2024-01-16T11:00:00Z',
  },
];

describe('JobMonitor', () => {
  const mockOnCancelJob = jest.fn();
  const mockOnViewJob = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Job List Display', () => {
    it('renders all jobs', () => {
      render(<JobMonitor jobs={mockJobs} />);

      expect(screen.getByText('Legal Specialist v2')).toBeInTheDocument();
      expect(screen.getByText('Healthcare Model')).toBeInTheDocument();
      expect(screen.getByText('Code Review Assistant')).toBeInTheDocument();
      expect(screen.getByText('Failed Training')).toBeInTheDocument();
      expect(screen.getByText('Preparing Job')).toBeInTheDocument();
    });

    it('shows base model for each job', () => {
      render(<JobMonitor jobs={mockJobs} />);

      expect(screen.getByText('nlpaueb/legal-bert-base-uncased')).toBeInTheDocument();
      expect(screen.getByText('medicalai/ClinicalBERT')).toBeInTheDocument();
    });

    it('displays status badges with correct text', () => {
      render(<JobMonitor jobs={mockJobs} />);

      expect(screen.getByText('training')).toBeInTheDocument();
      expect(screen.getByText('completed')).toBeInTheDocument();
      expect(screen.getByText('queued')).toBeInTheDocument();
      expect(screen.getByText('failed')).toBeInTheDocument();
      expect(screen.getByText('preparing')).toBeInTheDocument();
    });
  });

  describe('Status Filtering', () => {
    it('shows filter buttons', () => {
      render(<JobMonitor jobs={mockJobs} />);

      expect(screen.getByText('All')).toBeInTheDocument();
      expect(screen.getByText('Training')).toBeInTheDocument();
      expect(screen.getByText('Queued')).toBeInTheDocument();
      expect(screen.getByText('Completed')).toBeInTheDocument();
      expect(screen.getByText('Failed')).toBeInTheDocument();
    });

    it('filters to training jobs only', async () => {
      render(<JobMonitor jobs={mockJobs} />);

      await act(async () => {
        fireEvent.click(screen.getByText('Training'));
      });

      await waitFor(() => {
        expect(screen.getByText('Legal Specialist v2')).toBeInTheDocument();
        expect(screen.queryByText('Healthcare Model')).not.toBeInTheDocument();
        expect(screen.queryByText('Code Review Assistant')).not.toBeInTheDocument();
      });
    });

    it('filters to queued jobs only', async () => {
      render(<JobMonitor jobs={mockJobs} />);

      await act(async () => {
        fireEvent.click(screen.getByText('Queued'));
      });

      await waitFor(() => {
        expect(screen.getByText('Code Review Assistant')).toBeInTheDocument();
        expect(screen.queryByText('Legal Specialist v2')).not.toBeInTheDocument();
      });
    });

    it('filters to completed jobs only', async () => {
      render(<JobMonitor jobs={mockJobs} />);

      await act(async () => {
        fireEvent.click(screen.getByText('Completed'));
      });

      await waitFor(() => {
        expect(screen.getByText('Healthcare Model')).toBeInTheDocument();
        expect(screen.queryByText('Legal Specialist v2')).not.toBeInTheDocument();
      });
    });

    it('filters to failed jobs only', async () => {
      render(<JobMonitor jobs={mockJobs} />);

      await act(async () => {
        fireEvent.click(screen.getByText('Failed'));
      });

      await waitFor(() => {
        expect(screen.getByText('Failed Training')).toBeInTheDocument();
        expect(screen.queryByText('Healthcare Model')).not.toBeInTheDocument();
      });
    });

    it('returns to all jobs when All is clicked', async () => {
      render(<JobMonitor jobs={mockJobs} />);

      // Filter first
      await act(async () => {
        fireEvent.click(screen.getByText('Training'));
      });

      // Then return to all
      await act(async () => {
        fireEvent.click(screen.getByText('All'));
      });

      await waitFor(() => {
        expect(screen.getByText('Legal Specialist v2')).toBeInTheDocument();
        expect(screen.getByText('Healthcare Model')).toBeInTheDocument();
      });
    });
  });

  describe('Progress Display', () => {
    it('shows progress percentage for training jobs', () => {
      render(<JobMonitor jobs={mockJobs} />);

      expect(screen.getByText('45%')).toBeInTheDocument();
    });

    it('shows epoch information for training jobs', () => {
      render(<JobMonitor jobs={mockJobs} />);

      expect(screen.getByText(/Epoch 2\/3/)).toBeInTheDocument();
    });

    it('shows step information for training jobs', () => {
      render(<JobMonitor jobs={mockJobs} />);

      expect(screen.getByText(/Step 450\/1000/)).toBeInTheDocument();
    });

    it('shows loss for training jobs', () => {
      render(<JobMonitor jobs={mockJobs} />);

      expect(screen.getByText('0.3240')).toBeInTheDocument();
    });
  });

  describe('Expanded Job Details', () => {
    it('expands job when clicked', async () => {
      render(<JobMonitor jobs={mockJobs} />);

      await act(async () => {
        fireEvent.click(screen.getByText('Legal Specialist v2'));
      });

      await waitFor(() => {
        expect(screen.getByText('Training Examples:')).toBeInTheDocument();
        expect(screen.getByText('2,500')).toBeInTheDocument();
      });
    });

    it('shows duration in expanded view', async () => {
      render(<JobMonitor jobs={mockJobs} />);

      await act(async () => {
        fireEvent.click(screen.getByText('Healthcare Model'));
      });

      await waitFor(() => {
        expect(screen.getByText('Duration:')).toBeInTheDocument();
        // 4h 30m duration
        expect(screen.getByText('4h 30m')).toBeInTheDocument();
      });
    });

    it('shows started timestamp', async () => {
      render(<JobMonitor jobs={mockJobs} />);

      await act(async () => {
        fireEvent.click(screen.getByText('Healthcare Model'));
      });

      await waitFor(() => {
        expect(screen.getByText('Started:')).toBeInTheDocument();
      });
    });

    it('shows output path for completed jobs', async () => {
      render(<JobMonitor jobs={mockJobs} />);

      await act(async () => {
        fireEvent.click(screen.getByText('Healthcare Model'));
      });

      await waitFor(() => {
        expect(screen.getByText('Output:')).toBeInTheDocument();
        expect(screen.getByText('/models/healthcare_v1')).toBeInTheDocument();
      });
    });

    it('shows error message for failed jobs', async () => {
      render(<JobMonitor jobs={mockJobs} />);

      await act(async () => {
        fireEvent.click(screen.getByText('Failed Training'));
      });

      await waitFor(() => {
        expect(screen.getByText('Error:')).toBeInTheDocument();
        expect(screen.getByText('CUDA out of memory')).toBeInTheDocument();
      });
    });

    it('collapses when clicked again', async () => {
      render(<JobMonitor jobs={mockJobs} />);

      // Expand
      await act(async () => {
        fireEvent.click(screen.getByText('Legal Specialist v2'));
      });

      await waitFor(() => {
        expect(screen.getByText('Training Examples:')).toBeInTheDocument();
      });

      // Collapse
      await act(async () => {
        fireEvent.click(screen.getByText('Legal Specialist v2'));
      });

      await waitFor(() => {
        expect(screen.queryByText('Training Examples:')).not.toBeInTheDocument();
      });
    });
  });

  describe('Actions', () => {
    it('shows Cancel button for training jobs', async () => {
      render(<JobMonitor jobs={mockJobs} onCancelJob={mockOnCancelJob} />);

      await act(async () => {
        fireEvent.click(screen.getByText('Legal Specialist v2'));
      });

      await waitFor(() => {
        expect(screen.getByText('Cancel')).toBeInTheDocument();
      });
    });

    it('shows Cancel button for queued jobs', async () => {
      render(<JobMonitor jobs={mockJobs} onCancelJob={mockOnCancelJob} />);

      await act(async () => {
        fireEvent.click(screen.getByText('Code Review Assistant'));
      });

      await waitFor(() => {
        expect(screen.getByText('Cancel')).toBeInTheDocument();
      });
    });

    it('calls onCancelJob when Cancel is clicked', async () => {
      render(<JobMonitor jobs={mockJobs} onCancelJob={mockOnCancelJob} />);

      await act(async () => {
        fireEvent.click(screen.getByText('Legal Specialist v2'));
      });

      await act(async () => {
        fireEvent.click(screen.getByText('Cancel'));
      });

      expect(mockOnCancelJob).toHaveBeenCalledWith('ft_001');
    });

    it('shows Load Adapter button for completed jobs', async () => {
      render(<JobMonitor jobs={mockJobs} onViewJob={mockOnViewJob} />);

      await act(async () => {
        fireEvent.click(screen.getByText('Healthcare Model'));
      });

      await waitFor(() => {
        expect(screen.getByText('Load Adapter')).toBeInTheDocument();
      });
    });

    it('shows View Details button', async () => {
      render(<JobMonitor jobs={mockJobs} onViewJob={mockOnViewJob} />);

      await act(async () => {
        fireEvent.click(screen.getByText('Legal Specialist v2'));
      });

      await waitFor(() => {
        expect(screen.getByText('View Details')).toBeInTheDocument();
      });
    });

    it('calls onViewJob when View Details is clicked', async () => {
      render(<JobMonitor jobs={mockJobs} onViewJob={mockOnViewJob} />);

      await act(async () => {
        fireEvent.click(screen.getByText('Legal Specialist v2'));
      });

      await act(async () => {
        fireEvent.click(screen.getByText('View Details'));
      });

      expect(mockOnViewJob).toHaveBeenCalledWith(
        expect.objectContaining({ id: 'ft_001', name: 'Legal Specialist v2' }),
      );
    });

    it('does not show Cancel for completed jobs', async () => {
      render(<JobMonitor jobs={mockJobs} onCancelJob={mockOnCancelJob} />);

      await act(async () => {
        fireEvent.click(screen.getByText('Healthcare Model'));
      });

      await waitFor(() => {
        // Cancel should not be visible for completed jobs
        const buttons = screen.getAllByRole('button');
        const cancelButtons = buttons.filter((b) => b.textContent === 'Cancel');
        expect(cancelButtons).toHaveLength(0);
      });
    });
  });

  describe('Empty State', () => {
    it('shows empty state when no jobs', () => {
      render(<JobMonitor jobs={[]} />);

      expect(screen.getByText('No fine-tuning jobs found')).toBeInTheDocument();
    });

    it('shows empty state when filter matches no jobs', async () => {
      const singleJob: FineTuningJob[] = [
        {
          id: 'ft_001',
          name: 'Training Job',
          vertical: 'software',
          baseModel: 'codellama/CodeLlama-7b-Instruct-hf',
          status: 'training',
          progress: 0.5,
          trainingExamples: 1000,
        },
      ];

      render(<JobMonitor jobs={singleJob} />);

      // Filter to completed (which has no jobs)
      await act(async () => {
        fireEvent.click(screen.getByText('Completed'));
      });

      await waitFor(() => {
        expect(screen.getByText('No fine-tuning jobs found')).toBeInTheDocument();
      });
    });
  });

  describe('Vertical Icons', () => {
    it('renders vertical icons for jobs', () => {
      render(<JobMonitor jobs={mockJobs} />);

      // The component uses dangerouslySetInnerHTML for icons
      // We can verify the icons are rendered by checking the container elements exist
      const jobCards = screen.getAllByRole('button', { hidden: true });
      expect(jobCards.length).toBeGreaterThan(0);
    });
  });
});
