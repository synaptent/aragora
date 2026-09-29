/**
 * Tests for TrainingConfig component
 *
 * Tests cover:
 * - Form field rendering
 * - Default values
 * - Form submission
 * - Advanced settings toggle
 * - VRAM estimation
 * - Parameter validation
 */

import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { TrainingConfig } from '../src/components/control-plane/FineTuning/TrainingConfig';
import type { AvailableModel } from '../src/components/control-plane/FineTuning/ModelSelector';

const mockModel: AvailableModel = {
  id: 'codellama-34b',
  name: 'CodeLlama 34B Instruct',
  provider: 'Meta',
  vertical: 'software',
  type: 'primary',
  size: '34B',
  description: 'Large code-focused LLM',
  huggingFaceId: 'codellama/CodeLlama-34b-Instruct-hf',
};

const mockSmallModel: AvailableModel = {
  id: 'codellama-7b',
  name: 'CodeLlama 7B Instruct',
  provider: 'Meta',
  vertical: 'software',
  type: 'small',
  size: '7B',
  description: 'Efficient code model',
  huggingFaceId: 'codellama/CodeLlama-7b-Instruct-hf',
};

describe('TrainingConfig', () => {
  const mockOnStartTraining = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Form Rendering', () => {
    it('renders the configuration form', () => {
      render(<TrainingConfig model={mockModel} onStartTraining={mockOnStartTraining} />);

      expect(screen.getByText('Training Configuration')).toBeInTheDocument();
      expect(screen.getByText('JOB NAME')).toBeInTheDocument();
      expect(screen.getByText('DATASET PATH / ID')).toBeInTheDocument();
      expect(screen.getByText('EPOCHS')).toBeInTheDocument();
      expect(screen.getByText('BATCH SIZE')).toBeInTheDocument();
      expect(screen.getByText('QUANTIZATION')).toBeInTheDocument();
    });

    it('shows default job name based on vertical', () => {
      render(<TrainingConfig model={mockModel} onStartTraining={mockOnStartTraining} />);

      const jobNameInput = screen.getByPlaceholderText('my_specialist_model');
      expect(jobNameInput).toHaveValue('software_specialist_v1');
    });

    it('shows submit button', () => {
      render(<TrainingConfig model={mockModel} onStartTraining={mockOnStartTraining} />);

      expect(screen.getByText('START TRAINING')).toBeInTheDocument();
    });
  });

  describe('Default Values', () => {
    it('has correct default epochs', () => {
      render(<TrainingConfig model={mockModel} onStartTraining={mockOnStartTraining} />);

      const epochsSelect = screen.getAllByDisplayValue('3')[0];
      expect(epochsSelect).toBeInTheDocument();
    });

    it('has correct default batch size', () => {
      render(<TrainingConfig model={mockModel} onStartTraining={mockOnStartTraining} />);

      const batchSelect = screen.getByDisplayValue('4');
      expect(batchSelect).toBeInTheDocument();
    });

    it('has correct default quantization', () => {
      render(<TrainingConfig model={mockModel} onStartTraining={mockOnStartTraining} />);

      const quantSelect = screen.getByDisplayValue('4-bit (QLoRA)');
      expect(quantSelect).toBeInTheDocument();
    });
  });

  describe('VRAM Estimation', () => {
    it('shows VRAM estimate for 34B model with 4bit quantization', () => {
      render(<TrainingConfig model={mockModel} onStartTraining={mockOnStartTraining} />);

      // 34B base (~40GB) * 0.25 (4bit) = ~10GB
      expect(screen.getByText('~10 GB')).toBeInTheDocument();
    });

    it('shows VRAM estimate for 7B model with 4bit quantization', () => {
      render(<TrainingConfig model={mockSmallModel} onStartTraining={mockOnStartTraining} />);

      // 7B base (~8GB) * 0.25 (4bit) = ~2GB
      expect(screen.getByText('~2 GB')).toBeInTheDocument();
    });

    it('updates VRAM estimate when quantization changes', async () => {
      render(<TrainingConfig model={mockModel} onStartTraining={mockOnStartTraining} />);

      // Initial 4-bit estimate
      expect(screen.getByText('~10 GB')).toBeInTheDocument();

      // Change to 8-bit
      const quantSelect = screen.getByDisplayValue('4-bit (QLoRA)');
      await act(async () => {
        fireEvent.change(quantSelect, { target: { value: '8bit' } });
      });

      // 34B base (~40GB) * 0.5 (8bit) = ~20GB
      await waitFor(() => {
        expect(screen.getByText('~20 GB')).toBeInTheDocument();
      });
    });
  });

  describe('Form Submission', () => {
    it('calls onStartTraining with form values', async () => {
      render(<TrainingConfig model={mockModel} onStartTraining={mockOnStartTraining} />);

      // Fill in dataset path
      const datasetInput = screen.getByPlaceholderText('/data/training.jsonl or HF dataset');
      await act(async () => {
        fireEvent.change(datasetInput, { target: { value: '/data/my_dataset.jsonl' } });
      });

      // Submit form
      await act(async () => {
        fireEvent.click(screen.getByText('START TRAINING'));
      });

      expect(mockOnStartTraining).toHaveBeenCalledWith(
        expect.objectContaining({
          jobName: 'software_specialist_v1',
          datasetPath: '/data/my_dataset.jsonl',
          numEpochs: 3,
          batchSize: 4,
          quantization: '4bit',
        }),
      );
    });

    it('includes all default parameters', async () => {
      render(<TrainingConfig model={mockModel} onStartTraining={mockOnStartTraining} />);

      await act(async () => {
        fireEvent.click(screen.getByText('START TRAINING'));
      });

      expect(mockOnStartTraining).toHaveBeenCalledWith(
        expect.objectContaining({
          loraR: 16,
          loraAlpha: 32,
          loraDropout: 0.1,
          learningRate: 0.0002,
          maxSeqLength: 2048,
          gradientCheckpointing: true,
        }),
      );
    });
  });

  describe('Advanced Settings', () => {
    it('hides advanced settings by default', () => {
      render(<TrainingConfig model={mockModel} onStartTraining={mockOnStartTraining} />);

      expect(screen.queryByText('LoRA CONFIGURATION')).not.toBeInTheDocument();
      expect(screen.queryByText('TRAINING PARAMETERS')).not.toBeInTheDocument();
    });

    it('shows advanced settings toggle', () => {
      render(<TrainingConfig model={mockModel} onStartTraining={mockOnStartTraining} />);

      expect(screen.getByText('Advanced Settings')).toBeInTheDocument();
    });

    it('expands advanced settings when clicked', async () => {
      render(<TrainingConfig model={mockModel} onStartTraining={mockOnStartTraining} />);

      await act(async () => {
        fireEvent.click(screen.getByText('Advanced Settings'));
      });

      expect(screen.getByText('LoRA CONFIGURATION')).toBeInTheDocument();
      expect(screen.getByText('TRAINING PARAMETERS')).toBeInTheDocument();
    });

    it('shows LoRA parameters in advanced settings', async () => {
      render(<TrainingConfig model={mockModel} onStartTraining={mockOnStartTraining} />);

      await act(async () => {
        fireEvent.click(screen.getByText('Advanced Settings'));
      });

      expect(screen.getByText('LoRA R')).toBeInTheDocument();
      expect(screen.getByText('LoRA Alpha')).toBeInTheDocument();
      expect(screen.getByText('LoRA Dropout')).toBeInTheDocument();
    });

    it('shows training parameters in advanced settings', async () => {
      render(<TrainingConfig model={mockModel} onStartTraining={mockOnStartTraining} />);

      await act(async () => {
        fireEvent.click(screen.getByText('Advanced Settings'));
      });

      expect(screen.getByText('Learning Rate')).toBeInTheDocument();
      expect(screen.getByText('Max Sequence Length')).toBeInTheDocument();
      expect(screen.getByText('Gradient Checkpointing (saves memory)')).toBeInTheDocument();
    });

    it('allows changing LoRA R value', async () => {
      render(<TrainingConfig model={mockModel} onStartTraining={mockOnStartTraining} />);

      // Expand advanced settings
      await act(async () => {
        fireEvent.click(screen.getByText('Advanced Settings'));
      });

      // Change LoRA R - look for the select within LoRA R label context
      const loraRLabel = screen.getByText('LoRA R');
      const loraRContainer = loraRLabel.closest('div');
      const loraRSelect = loraRContainer?.querySelector('select');

      expect(loraRSelect).toBeInTheDocument();
      expect(loraRSelect).toHaveValue('16');

      await act(async () => {
        fireEvent.change(loraRSelect!, { target: { value: '32' } });
      });

      expect(loraRSelect).toHaveValue('32');
    });

    it('allows toggling gradient checkpointing', async () => {
      render(<TrainingConfig model={mockModel} onStartTraining={mockOnStartTraining} />);

      // Expand advanced settings
      await act(async () => {
        fireEvent.click(screen.getByText('Advanced Settings'));
      });

      // Toggle gradient checkpointing (default is true)
      const checkbox = screen.getByRole('checkbox');
      expect(checkbox).toBeChecked();

      await act(async () => {
        fireEvent.click(checkbox);
      });

      // Verify checkbox is now unchecked
      expect(checkbox).not.toBeChecked();
    });

    it('collapses advanced settings when clicked again', async () => {
      render(<TrainingConfig model={mockModel} onStartTraining={mockOnStartTraining} />);

      // Expand
      await act(async () => {
        fireEvent.click(screen.getByText('Advanced Settings'));
      });
      expect(screen.getByText('LoRA CONFIGURATION')).toBeInTheDocument();

      // Collapse
      await act(async () => {
        fireEvent.click(screen.getByText('Advanced Settings'));
      });
      expect(screen.queryByText('LoRA CONFIGURATION')).not.toBeInTheDocument();
    });
  });

  describe('Parameter Updates', () => {
    it('updates job name when typed', async () => {
      render(<TrainingConfig model={mockModel} onStartTraining={mockOnStartTraining} />);

      const jobNameInput = screen.getByPlaceholderText('my_specialist_model');
      await act(async () => {
        fireEvent.change(jobNameInput, { target: { value: 'custom_job_name' } });
      });

      await act(async () => {
        fireEvent.click(screen.getByText('START TRAINING'));
      });

      expect(mockOnStartTraining).toHaveBeenCalledWith(
        expect.objectContaining({ jobName: 'custom_job_name' }),
      );
    });

    it('updates epochs when changed', async () => {
      render(<TrainingConfig model={mockModel} onStartTraining={mockOnStartTraining} />);

      const epochsSelects = screen.getAllByDisplayValue('3');
      const epochsSelect = epochsSelects[0];
      await act(async () => {
        fireEvent.change(epochsSelect, { target: { value: '5' } });
      });

      await act(async () => {
        fireEvent.click(screen.getByText('START TRAINING'));
      });

      expect(mockOnStartTraining).toHaveBeenCalledWith(expect.objectContaining({ numEpochs: 5 }));
    });
  });
});
