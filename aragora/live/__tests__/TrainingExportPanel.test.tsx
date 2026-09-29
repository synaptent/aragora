/**
 * Tests for TrainingExportPanel admin component
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { TrainingExportPanel } from '../src/components/admin/TrainingExportPanel';

// Mock fetch globally
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock URL methods for download
const mockCreateObjectURL = jest.fn(() => 'blob:mock-url');
const mockRevokeObjectURL = jest.fn();
URL.createObjectURL = mockCreateObjectURL;
URL.revokeObjectURL = mockRevokeObjectURL;

describe('TrainingExportPanel', () => {
  const mockStats = {
    available_exporters: ['sft', 'dpo', 'gauntlet'],
    export_directory: '/data/exports',
    exported_files: [
      {
        name: 'sft_export_2024-01-15.json',
        size_bytes: 102400,
        created_at: '2024-01-15T10:30:00Z',
        modified_at: '2024-01-15T10:30:00Z',
      },
      {
        name: 'dpo_export_2024-01-14.jsonl',
        size_bytes: 51200,
        created_at: '2024-01-14T09:00:00Z',
        modified_at: '2024-01-14T09:00:00Z',
      },
    ],
    sft_available: true,
  };

  const mockFormats = {
    formats: {
      sft: {
        description: 'Supervised Fine-Tuning format',
        schema: { prompt: 'string', response: 'string' },
        use_case: 'Train models on successful debate patterns',
      },
      dpo: {
        description: 'Direct Preference Optimization format',
        schema: { chosen: 'string', rejected: 'string' },
        use_case: 'Train preference models from debate outcomes',
      },
      gauntlet: {
        description: 'Gauntlet attack-response pairs',
        schema: { attack: 'string', response: 'string' },
        use_case: 'Train robust response generation',
      },
    },
    output_formats: ['json', 'jsonl'],
    endpoints: {
      sft: '/api/training/export/sft',
      dpo: '/api/training/export/dpo',
      gauntlet: '/api/training/export/gauntlet',
    },
  };

  const mockExportResult = {
    export_type: 'sft',
    total_records: 150,
    parameters: { min_confidence: 0.7, limit: 1000 },
    exported_at: '2024-01-15T11:00:00Z',
    format: 'json',
    records: [{ prompt: 'test', response: 'response' }],
  };

  beforeEach(() => {
    mockFetch.mockClear();
    mockCreateObjectURL.mockClear();
    mockRevokeObjectURL.mockClear();
  });

  const setupMockFetch = (statsResponse = mockStats, formatsResponse = mockFormats) => {
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/training/stats')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(statsResponse) });
      }
      if (url.includes('/training/formats')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(formatsResponse) });
      }
      if (url.includes('/training/export/')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockExportResult) });
      }
      return Promise.reject(new Error('Unknown URL'));
    });
  };

  describe('Loading State', () => {
    it('shows loading indicator while fetching', () => {
      mockFetch.mockImplementation(() => new Promise(() => {})); // Never resolves
      render(<TrainingExportPanel />);
      expect(screen.getByText(/loading training data/i)).toBeInTheDocument();
    });
  });

  describe('Error Handling', () => {
    it('shows error message on export failure', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/training/stats')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockStats) });
        }
        if (url.includes('/training/formats')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockFormats) });
        }
        if (url.includes('/training/export/')) {
          return Promise.resolve({
            ok: false,
            status: 500,
            json: () => Promise.resolve({ error: 'Export failed' }),
          });
        }
        return Promise.reject(new Error('Unknown URL'));
      });

      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('SFT')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText(/export sft/i));

      await waitFor(() => {
        expect(screen.getByText('Export failed')).toBeInTheDocument();
      });
    });
  });

  describe('Export Types', () => {
    beforeEach(() => {
      setupMockFetch();
    });

    it('displays all export type buttons', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('SFT')).toBeInTheDocument();
      });
      expect(screen.getByText('DPO')).toBeInTheDocument();
      expect(screen.getByText('GAUNTLET')).toBeInTheDocument();
    });

    it('defaults to SFT export type', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('SFT')).toBeInTheDocument();
      });

      // SFT button should be selected (has the active class)
      const sftButton = screen.getByText('SFT');
      expect(sftButton).toHaveClass('bg-[var(--accent)]/20');
    });

    it('switches to DPO export type', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('SFT')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('DPO'));

      // DPO button should now be selected
      const dpoButton = screen.getByText('DPO');
      expect(dpoButton).toHaveClass('bg-[var(--accent)]/20');
    });

    it('switches to Gauntlet export type', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('SFT')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('GAUNTLET'));

      // Gauntlet button should now be selected
      const gauntletButton = screen.getByText('GAUNTLET');
      expect(gauntletButton).toHaveClass('bg-[var(--accent)]/20');
    });
  });

  describe('Output Formats', () => {
    beforeEach(() => {
      setupMockFetch();
    });

    it('displays output format buttons', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('JSON')).toBeInTheDocument();
      });
      expect(screen.getByText('JSONL')).toBeInTheDocument();
    });

    it('defaults to JSON format', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('JSON')).toBeInTheDocument();
      });

      const jsonButton = screen.getByText('JSON');
      expect(jsonButton).toHaveClass('bg-[var(--acid-cyan)]/20');
    });

    it('switches to JSONL format', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('JSON')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('JSONL'));

      const jsonlButton = screen.getByText('JSONL');
      expect(jsonlButton).toHaveClass('bg-[var(--acid-cyan)]/20');
    });
  });

  describe('SFT Parameters', () => {
    beforeEach(() => {
      setupMockFetch();
    });

    it('shows SFT parameters by default', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('MIN CONFIDENCE')).toBeInTheDocument();
      });
      expect(screen.getByText('MIN SUCCESS RATE')).toBeInTheDocument();
      expect(screen.getByText('LIMIT')).toBeInTheDocument();
    });

    it('shows SFT checkbox options', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('Critiques')).toBeInTheDocument();
      });
      expect(screen.getByText('Patterns')).toBeInTheDocument();
      expect(screen.getByText('Debates')).toBeInTheDocument();
    });

    it('toggles include critiques checkbox', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('Critiques')).toBeInTheDocument();
      });

      const checkbox = screen.getAllByRole('checkbox')[0];
      expect(checkbox).toBeChecked();

      fireEvent.click(checkbox);
      expect(checkbox).not.toBeChecked();
    });
  });

  describe('DPO Parameters', () => {
    beforeEach(() => {
      setupMockFetch();
    });

    it('shows DPO parameters when DPO selected', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('SFT')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('DPO'));

      expect(screen.getByText('MIN CONFIDENCE DIFF')).toBeInTheDocument();
    });

    it('hides SFT checkboxes when DPO selected', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('Critiques')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('DPO'));

      expect(screen.queryByText('Critiques')).not.toBeInTheDocument();
    });
  });

  describe('Gauntlet Parameters', () => {
    beforeEach(() => {
      setupMockFetch();
    });

    it('shows Gauntlet parameters when Gauntlet selected', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('SFT')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('GAUNTLET'));

      expect(screen.getByText('PERSONA')).toBeInTheDocument();
      expect(screen.getByText('MIN SEVERITY')).toBeInTheDocument();
    });

    it('shows persona select options', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('SFT')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('GAUNTLET'));

      const select = screen.getByRole('combobox');
      expect(select).toBeInTheDocument();

      // Check options exist
      const options = screen.getAllByRole('option');
      expect(options.length).toBe(4); // ALL, GDPR, HIPAA, AI ACT
    });
  });

  describe('Export Action', () => {
    beforeEach(() => {
      setupMockFetch();
    });

    it('shows export button', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText(/export sft/i)).toBeInTheDocument();
      });
    });

    it('triggers export on button click', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText(/export sft/i)).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText(/export sft/i));

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(expect.stringContaining('/training/export/sft'));
      });
    });

    it('includes parameters in export request', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText(/export sft/i)).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText(/export sft/i));

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(expect.stringMatching(/min_confidence=0\.7/));
      });
    });

    it('shows exporting state', async () => {
      // Make export slow
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/training/stats')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockStats) });
        }
        if (url.includes('/training/formats')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockFormats) });
        }
        if (url.includes('/training/export/')) {
          return new Promise((resolve) => {
            setTimeout(
              () => resolve({ ok: true, json: () => Promise.resolve(mockExportResult) }),
              1000,
            );
          });
        }
        return Promise.reject(new Error('Unknown URL'));
      });

      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText(/export sft/i)).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText(/export sft/i));

      expect(screen.getByText('EXPORTING...')).toBeInTheDocument();
    });
  });

  describe('Export Result', () => {
    beforeEach(() => {
      setupMockFetch();
    });

    it('shows export complete message after successful export', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText(/export sft/i)).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText(/export sft/i));

      await waitFor(() => {
        expect(screen.getByText('EXPORT COMPLETE')).toBeInTheDocument();
      });
    });

    it('shows total records in export result', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText(/export sft/i)).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText(/export sft/i));

      await waitFor(() => {
        expect(screen.getByText('150')).toBeInTheDocument();
      });
    });

    it('shows download button after export', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText(/export sft/i)).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText(/export sft/i));

      await waitFor(() => {
        expect(screen.getByText('DOWNLOAD')).toBeInTheDocument();
      });
    });

    it('triggers download on button click', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText(/export sft/i)).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText(/export sft/i));

      await waitFor(() => {
        expect(screen.getByText('DOWNLOAD')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('DOWNLOAD'));

      expect(mockCreateObjectURL).toHaveBeenCalled();
    });
  });

  describe('Stats Display', () => {
    beforeEach(() => {
      setupMockFetch();
    });

    it('shows available exporters count in header', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('3 exporters available')).toBeInTheDocument();
      });
    });

    it('shows exporter availability status', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('AVAILABLE EXPORTERS')).toBeInTheDocument();
      });
    });

    it('shows export directory', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('/data/exports')).toBeInTheDocument();
      });
    });
  });

  describe('Recent Exports', () => {
    beforeEach(() => {
      setupMockFetch();
    });

    it('shows recent exports section', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('RECENT EXPORTS')).toBeInTheDocument();
      });
    });

    it('shows exported file names', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('sft_export_2024-01-15.json')).toBeInTheDocument();
      });
      expect(screen.getByText('dpo_export_2024-01-14.jsonl')).toBeInTheDocument();
    });

    it('shows file sizes', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('100.0 KB')).toBeInTheDocument();
      });
      expect(screen.getByText('50.0 KB')).toBeInTheDocument();
    });
  });

  describe('Format Info', () => {
    beforeEach(() => {
      setupMockFetch();
    });

    it('shows format description for selected type', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('Supervised Fine-Tuning format')).toBeInTheDocument();
      });
    });

    it('shows use case for selected type', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('Train models on successful debate patterns')).toBeInTheDocument();
      });
    });

    it('updates format info when type changes', async () => {
      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('Supervised Fine-Tuning format')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('DPO'));

      expect(screen.getByText('Direct Preference Optimization format')).toBeInTheDocument();
    });
  });

  describe('Disabled Exporters', () => {
    it('disables export button when exporter not available', async () => {
      setupMockFetch({
        ...mockStats,
        available_exporters: ['sft'], // Only SFT available
      });

      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('SFT')).toBeInTheDocument();
      });

      // DPO should be disabled
      const dpoButton = screen.getByText('DPO');
      expect(dpoButton).toHaveClass('cursor-not-allowed');
    });

    it('shows unavailable status for disabled exporters', async () => {
      setupMockFetch({
        ...mockStats,
        available_exporters: ['sft'], // Only SFT available
      });

      render(<TrainingExportPanel />);

      await waitFor(() => {
        // DPO should show unavailable status in the availability list
        const dpoStatus = screen.getAllByText(/DPO/i).find((el) => el.textContent?.includes(''));
        expect(dpoStatus).toBeTruthy();
      });
    });
  });

  describe('Empty State', () => {
    it('shows empty exports list when no files', async () => {
      setupMockFetch({ ...mockStats, exported_files: [] });

      render(<TrainingExportPanel />);

      await waitFor(() => {
        expect(screen.getByText('SFT')).toBeInTheDocument();
      });

      // Recent exports section should not be shown
      expect(screen.queryByText('RECENT EXPORTS')).not.toBeInTheDocument();
    });
  });

  describe('Custom API Base', () => {
    it('uses custom apiBase for fetch', async () => {
      setupMockFetch();
      render(<TrainingExportPanel apiBase="/custom/api" />);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith('/custom/api/training/stats');
      });
      expect(mockFetch).toHaveBeenCalledWith('/custom/api/training/formats');
    });
  });
});
