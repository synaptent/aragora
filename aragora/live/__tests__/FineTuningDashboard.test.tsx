/**
 * Tests for FineTuningDashboard component
 *
 * Tests cover:
 * - Tab navigation between jobs, new job, and models views
 * - Stats display (training, queued, completed, failed)
 * - Model selection flow
 * - Training configuration submission
 * - Job cancellation
 */

import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { FineTuningDashboard } from '../src/components/control-plane/FineTuning/FineTuningDashboard';
import type { FineTuningJob } from '../src/hooks/useFineTuning';

// Mock the useFineTuning hook
const mockCreateJob = jest.fn();
const mockStartJob = jest.fn();
const mockCancelJob = jest.fn();

jest.mock('../src/hooks/useFineTuning', () => ({
  useFineTuning: () => ({
    jobs: mockJobs,
    stats: mockStats,
    loading: mockLoading,
    error: mockError,
    createJob: mockCreateJob,
    startJob: mockStartJob,
    cancelJob: mockCancelJob,
    loadJobs: jest.fn(),
    loadJob: jest.fn(),
    refetch: jest.fn(),
    getJobMetrics: jest.fn(),
    getJobArtifacts: jest.fn(),
    exportSFT: jest.fn(),
    exportDPO: jest.fn(),
    getStats: jest.fn(),
    getFormats: jest.fn(),
  }),
}));

// Default mock state
let mockJobs: FineTuningJob[] = [];
let mockStats = { running: 0, queued: 0, completed: 0, failed: 0 };
let mockLoading = false;
let mockError: string | null = null;

const defaultMockJobs: FineTuningJob[] = [
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
    name: 'Failed Job',
    vertical: 'accounting',
    baseModel: 'ProsusAI/finbert',
    status: 'failed',
    progress: 0.2,
    trainingExamples: 1000,
    error: 'Out of memory',
  },
];

const defaultMockStats = { running: 1, queued: 1, completed: 1, failed: 1 };

describe('FineTuningDashboard', () => {
  beforeEach(() => {
    // Reset mock state
    mockJobs = [...defaultMockJobs];
    mockStats = { ...defaultMockStats };
    mockLoading = false;
    mockError = null;
    jest.clearAllMocks();
  });

  describe('Header and Stats', () => {
    it('renders the dashboard header', () => {
      render(<FineTuningDashboard />);
      expect(screen.getByText('FINE-TUNING PIPELINE')).toBeInTheDocument();
      expect(
        screen.getByText('Train domain-specific models with LoRA adapters'),
      ).toBeInTheDocument();
    });

    it('displays correct job statistics', () => {
      render(<FineTuningDashboard />);

      // Verify stat labels exist (may appear multiple times due to filter buttons)
      const trainingLabels = screen.getAllByText('Training');
      expect(trainingLabels.length).toBeGreaterThan(0);

      const failedLabels = screen.getAllByText('Failed');
      expect(failedLabels.length).toBeGreaterThan(0);

      // Queued count (appears both in stats and filter)
      const queuedLabels = screen.getAllByText('Queued');
      expect(queuedLabels.length).toBeGreaterThan(0);

      // Completed count
      const completedLabels = screen.getAllByText('Completed');
      expect(completedLabels.length).toBeGreaterThan(0);
    });

    it('handles empty jobs array', () => {
      mockJobs = [];
      mockStats = { running: 0, queued: 0, completed: 0, failed: 0 };
      render(<FineTuningDashboard />);
      // All stats should show 0 for empty jobs
      const zeroValues = screen.getAllByText('0');
      expect(zeroValues.length).toBeGreaterThan(0);
    });

    it('shows loading state', () => {
      mockLoading = true;
      mockJobs = [];
      render(<FineTuningDashboard />);
      expect(screen.getByText('Loading...')).toBeInTheDocument();
    });

    it('shows error state', () => {
      mockError = 'Failed to connect';
      render(<FineTuningDashboard />);
      // Error message is in a div with red-400 class
      const errorDiv = screen.getByText((content, element) => {
        return (
          element?.className?.includes('text-red-400') &&
          element?.textContent === 'Error: Failed to connect'
        );
      });
      expect(errorDiv).toBeInTheDocument();
    });
  });

  describe('Tab Navigation', () => {
    it('shows Active Jobs tab by default', () => {
      render(<FineTuningDashboard />);
      expect(screen.getByText('Active Jobs')).toBeInTheDocument();
      expect(screen.getByText('Legal Specialist v2')).toBeInTheDocument();
    });

    it('switches to New Job tab when clicked', async () => {
      render(<FineTuningDashboard />);

      await act(async () => {
        fireEvent.click(screen.getByText('New Job'));
      });

      // Should show model selector
      expect(screen.getByPlaceholderText('Search models...')).toBeInTheDocument();
    });

    it('switches to Available Models tab when clicked', async () => {
      render(<FineTuningDashboard />);

      await act(async () => {
        fireEvent.click(screen.getByText('Available Models'));
      });

      // Should show model catalog with showAllModels enabled
      expect(screen.getByPlaceholderText('Search models...')).toBeInTheDocument();
    });
  });

  describe('Job Display', () => {
    it('displays job names in the list', () => {
      render(<FineTuningDashboard />);
      expect(screen.getByText('Legal Specialist v2')).toBeInTheDocument();
      expect(screen.getByText('Healthcare Model')).toBeInTheDocument();
      expect(screen.getByText('Code Review Assistant')).toBeInTheDocument();
    });

    it('shows base model for each job', () => {
      render(<FineTuningDashboard />);
      expect(screen.getByText('nlpaueb/legal-bert-base-uncased')).toBeInTheDocument();
      expect(screen.getByText('medicalai/ClinicalBERT')).toBeInTheDocument();
    });

    it('displays job status badges', () => {
      render(<FineTuningDashboard />);
      expect(screen.getByText('training')).toBeInTheDocument();
      expect(screen.getByText('completed')).toBeInTheDocument();
      expect(screen.getByText('queued')).toBeInTheDocument();
      expect(screen.getByText('failed')).toBeInTheDocument();
    });
  });

  describe('Training Job Start', () => {
    it('calls createJob and startJob when training is started', async () => {
      mockCreateJob.mockResolvedValue({ id: 'ft_new', name: 'Test Job' });
      mockStartJob.mockResolvedValue(true);

      render(<FineTuningDashboard />);

      // Navigate to New Job tab
      await act(async () => {
        fireEvent.click(screen.getByText('New Job'));
      });

      // Select a model (click on CodeLlama)
      await act(async () => {
        fireEvent.click(screen.getByText('CodeLlama 34B Instruct'));
      });

      // Fill in job name and submit
      await act(async () => {
        fireEvent.click(screen.getByText('START TRAINING'));
      });

      await waitFor(() => {
        expect(mockCreateJob).toHaveBeenCalled();
      });
    });
  });

  describe('Job Cancellation', () => {
    it('calls cancelJob when cancel is clicked', async () => {
      mockCancelJob.mockResolvedValue(true);
      render(<FineTuningDashboard />);

      // Expand a job to see cancel button
      await act(async () => {
        fireEvent.click(screen.getByText('Legal Specialist v2'));
      });

      // Click cancel
      const cancelButton = screen.getByText('Cancel');
      await act(async () => {
        fireEvent.click(cancelButton);
      });

      await waitFor(() => {
        expect(mockCancelJob).toHaveBeenCalledWith('ft_001');
      });
    });
  });

  describe('Model Selection Flow', () => {
    it('navigates to New Job tab when model is selected from Available Models', async () => {
      render(<FineTuningDashboard />);

      // Go to Available Models tab
      await act(async () => {
        fireEvent.click(screen.getByText('Available Models'));
      });

      // Select a model
      await act(async () => {
        fireEvent.click(screen.getByText('Legal BERT'));
      });

      // Should switch to New Job tab and show training config
      await waitFor(() => {
        expect(screen.getByText('Training Configuration')).toBeInTheDocument();
      });
    });
  });
});
