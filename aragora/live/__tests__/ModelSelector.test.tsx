/**
 * Tests for ModelSelector component
 *
 * Tests cover:
 * - Model listing and display
 * - Search functionality
 * - Vertical filtering
 * - Type filtering
 * - Model selection
 * - Recommended model highlighting
 * - Empty state handling
 */

import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import {
  ModelSelector,
  type AvailableModel,
} from '../src/components/control-plane/FineTuning/ModelSelector';

describe('ModelSelector', () => {
  const mockOnSelectModel = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Model Display', () => {
    it('renders available models', () => {
      render(<ModelSelector onSelectModel={mockOnSelectModel} />);

      expect(screen.getByText('CodeLlama 34B Instruct')).toBeInTheDocument();
      expect(screen.getByText('Legal BERT')).toBeInTheDocument();
      expect(screen.getByText('ClinicalBERT')).toBeInTheDocument();
      expect(screen.getByText('FinBERT')).toBeInTheDocument();
      expect(screen.getByText('SciBERT')).toBeInTheDocument();
    });

    it('shows model size information', () => {
      render(<ModelSelector onSelectModel={mockOnSelectModel} />);

      expect(screen.getByText('34B')).toBeInTheDocument();
      expect(screen.getByText('7B')).toBeInTheDocument();
      expect(screen.getAllByText('110M').length).toBeGreaterThan(0);
    });

    it('shows model type badges', () => {
      render(<ModelSelector onSelectModel={mockOnSelectModel} />);

      expect(screen.getAllByText('primary').length).toBeGreaterThan(0);
      expect(screen.getAllByText('embedding').length).toBeGreaterThan(0);
      expect(screen.getAllByText('small').length).toBeGreaterThan(0);
    });

    it('highlights recommended models', () => {
      render(<ModelSelector onSelectModel={mockOnSelectModel} />);

      // Recommended badge
      expect(screen.getAllByText('REC').length).toBeGreaterThan(0);
    });

    it('shows download counts', () => {
      render(<ModelSelector onSelectModel={mockOnSelectModel} />);

      // Formatted download counts - look for the download icon pattern
      const downloadIndicators = screen.getAllByText(/\d+K/);
      expect(downloadIndicators.length).toBeGreaterThan(0);
    });
  });

  describe('Search Functionality', () => {
    it('filters models by search query', async () => {
      render(<ModelSelector onSelectModel={mockOnSelectModel} />);

      const searchInput = screen.getByPlaceholderText('Search models...');
      await act(async () => {
        fireEvent.change(searchInput, { target: { value: 'legal' } });
      });

      await waitFor(() => {
        expect(screen.getByText('Legal BERT')).toBeInTheDocument();
        expect(screen.queryByText('CodeLlama 34B Instruct')).not.toBeInTheDocument();
      });
    });

    it('filters by HuggingFace ID', async () => {
      render(<ModelSelector onSelectModel={mockOnSelectModel} />);

      const searchInput = screen.getByPlaceholderText('Search models...');
      await act(async () => {
        fireEvent.change(searchInput, { target: { value: 'codellama' } });
      });

      await waitFor(() => {
        expect(screen.getByText('CodeLlama 34B Instruct')).toBeInTheDocument();
        expect(screen.getByText('CodeLlama 7B Instruct')).toBeInTheDocument();
        expect(screen.queryByText('Legal BERT')).not.toBeInTheDocument();
      });
    });

    it('shows empty state when no models match search', async () => {
      render(<ModelSelector onSelectModel={mockOnSelectModel} />);

      const searchInput = screen.getByPlaceholderText('Search models...');
      await act(async () => {
        fireEvent.change(searchInput, { target: { value: 'nonexistent model xyz' } });
      });

      await waitFor(() => {
        expect(screen.getByText('No models found matching your criteria')).toBeInTheDocument();
      });
    });
  });

  describe('Vertical Filtering', () => {
    it('filters models by vertical', async () => {
      render(<ModelSelector onSelectModel={mockOnSelectModel} />);

      const verticalSelect = screen.getByDisplayValue('All Verticals');
      await act(async () => {
        fireEvent.change(verticalSelect, { target: { value: 'legal' } });
      });

      await waitFor(() => {
        expect(screen.getByText('Legal BERT')).toBeInTheDocument();
        expect(screen.queryByText('CodeLlama 34B Instruct')).not.toBeInTheDocument();
        expect(screen.queryByText('ClinicalBERT')).not.toBeInTheDocument();
      });
    });

    it('shows all verticals in dropdown', () => {
      render(<ModelSelector onSelectModel={mockOnSelectModel} />);

      const verticalSelect = screen.getByDisplayValue('All Verticals');
      expect(verticalSelect).toBeInTheDocument();

      // Check that vertical options exist
      expect(screen.getByRole('option', { name: 'Software' })).toBeInTheDocument();
      expect(screen.getByRole('option', { name: 'Legal' })).toBeInTheDocument();
      expect(screen.getByRole('option', { name: 'Healthcare' })).toBeInTheDocument();
      expect(screen.getByRole('option', { name: 'Accounting' })).toBeInTheDocument();
      expect(screen.getByRole('option', { name: 'Research' })).toBeInTheDocument();
    });

    it('respects filterVertical prop', () => {
      render(<ModelSelector onSelectModel={mockOnSelectModel} filterVertical="healthcare" />);

      expect(screen.getByText('ClinicalBERT')).toBeInTheDocument();
      expect(screen.getByText('PubMedBERT')).toBeInTheDocument();
      expect(screen.queryByText('CodeLlama 34B Instruct')).not.toBeInTheDocument();
    });
  });

  describe('Type Filtering', () => {
    it('filters models by type', async () => {
      render(<ModelSelector onSelectModel={mockOnSelectModel} />);

      const typeSelect = screen.getByDisplayValue('All Types');
      await act(async () => {
        fireEvent.change(typeSelect, { target: { value: 'embedding' } });
      });

      await waitFor(() => {
        expect(screen.getByText('CodeBERT')).toBeInTheDocument();
        expect(screen.queryByText('CodeLlama 34B Instruct')).not.toBeInTheDocument();
      });
    });
  });

  describe('Model Selection', () => {
    it('calls onSelectModel when a model is clicked', async () => {
      render(<ModelSelector onSelectModel={mockOnSelectModel} />);

      await act(async () => {
        fireEvent.click(screen.getByText('Legal BERT'));
      });

      expect(mockOnSelectModel).toHaveBeenCalledWith(
        expect.objectContaining({ id: 'legal-bert', name: 'Legal BERT', vertical: 'legal' }),
      );
    });

    it('highlights selected model', async () => {
      const selectedModel: AvailableModel = {
        id: 'legal-bert',
        name: 'Legal BERT',
        provider: 'NLP@AUEB',
        vertical: 'legal',
        type: 'primary',
        size: '110M',
        description: 'BERT fine-tuned on legal documents',
        huggingFaceId: 'nlpaueb/legal-bert-base-uncased',
      };

      render(<ModelSelector selectedModel={selectedModel} onSelectModel={mockOnSelectModel} />);

      // The selected model should have different styling (accent border)
      const legalBertCard = screen.getByText('Legal BERT').closest('div[class*="border"]');
      expect(legalBertCard).toHaveClass('border-[var(--accent)]');
    });

    it('shows HuggingFace ID when model is selected', async () => {
      const selectedModel: AvailableModel = {
        id: 'legal-bert',
        name: 'Legal BERT',
        provider: 'NLP@AUEB',
        vertical: 'legal',
        type: 'primary',
        size: '110M',
        description: 'BERT fine-tuned on legal documents',
        huggingFaceId: 'nlpaueb/legal-bert-base-uncased',
      };

      render(<ModelSelector selectedModel={selectedModel} onSelectModel={mockOnSelectModel} />);

      expect(screen.getByText('nlpaueb/legal-bert-base-uncased')).toBeInTheDocument();
    });
  });

  describe('Show All Models Mode', () => {
    it('shows HuggingFace IDs for all models when showAllModels is true', () => {
      render(<ModelSelector showAllModels onSelectModel={mockOnSelectModel} />);

      // Should show HF IDs for all displayed models
      expect(screen.getByText('codellama/CodeLlama-34b-Instruct-hf')).toBeInTheDocument();
      expect(screen.getByText('nlpaueb/legal-bert-base-uncased')).toBeInTheDocument();
    });
  });

  describe('Combined Filters', () => {
    it('applies multiple filters together', async () => {
      render(<ModelSelector onSelectModel={mockOnSelectModel} />);

      // Filter by software vertical
      const verticalSelect = screen.getByDisplayValue('All Verticals');
      await act(async () => {
        fireEvent.change(verticalSelect, { target: { value: 'software' } });
      });

      // Then filter by embedding type
      const typeSelect = screen.getByDisplayValue('All Types');
      await act(async () => {
        fireEvent.change(typeSelect, { target: { value: 'embedding' } });
      });

      await waitFor(() => {
        // Should only show CodeBERT (software + embedding)
        expect(screen.getByText('CodeBERT')).toBeInTheDocument();
        expect(screen.queryByText('CodeLlama 34B Instruct')).not.toBeInTheDocument();
        expect(screen.queryByText('Legal BERT')).not.toBeInTheDocument();
      });
    });
  });
});
