/**
 * Tests for DocumentUpload component
 *
 * Tests cover:
 * - Initial render and drop zone display
 * - File type validation
 * - File size validation
 * - MIME type validation
 * - Upload success flow
 * - Upload error handling
 * - Document list management
 * - Drag and drop interactions
 * - Keyboard accessibility
 */

import { renderWithProviders, screen, fireEvent, waitFor, act } from '@/test-utils';
import { DocumentUpload } from '../src/components/DocumentUpload';

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

describe('DocumentUpload', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();
  });

  const createFile = (name: string, type: string, size: number = 1024): File => {
    const content = new Array(size).fill('x').join('');
    return new File([content], name, { type });
  };

  describe('Initial render', () => {
    it('renders drop zone with instructions', () => {
      renderWithProviders(<DocumentUpload />);

      expect(screen.getByText('Drop files here or click to upload')).toBeInTheDocument();
      expect(screen.getByText(/PDF, DOCX, TXT, MD/)).toBeInTheDocument();
    });

    it('shows Documents header', () => {
      renderWithProviders(<DocumentUpload />);
      expect(screen.getByText('Documents')).toBeInTheDocument();
    });

    it('renders accessible drop zone', () => {
      renderWithProviders(<DocumentUpload />);
      const dropZone = screen.getByRole('button', { name: /upload a document/i });
      expect(dropZone).toBeInTheDocument();
    });
  });

  describe('File validation', () => {
    it('rejects unsupported file types', async () => {
      renderWithProviders(<DocumentUpload />);

      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const file = createFile('test.exe', 'application/x-msdownload');

      await waitFor(() => {
        fireEvent.change(input, { target: { files: [file] } });
      });

      expect(screen.getByText(/Unsupported file type: .exe/)).toBeInTheDocument();
    });

    it('rejects files over 10MB', async () => {
      renderWithProviders(<DocumentUpload />);

      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      // Create small file but override size property to simulate large file
      const file = createFile('large.pdf', 'application/pdf', 1024);
      Object.defineProperty(file, 'size', { value: 11 * 1024 * 1024 }); // 11MB

      await waitFor(() => {
        fireEvent.change(input, { target: { files: [file] } });
      });

      expect(screen.getByText(/File too large/)).toBeInTheDocument();
    });

    it('rejects MIME type mismatch (file spoofing detection)', async () => {
      renderWithProviders(<DocumentUpload />);

      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      // PDF extension but wrong MIME type
      const file = createFile('fake.pdf', 'text/html', 1024);

      await waitFor(() => {
        fireEvent.change(input, { target: { files: [file] } });
      });

      expect(screen.getByText(/MIME type.*doesn't match extension/)).toBeInTheDocument();
    });

    it('accepts valid PDF files', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            document: {
              id: 'doc-123',
              filename: 'valid.pdf',
              word_count: 500,
              page_count: 2,
              preview: 'Preview text...',
            },
          }),
      });

      renderWithProviders(<DocumentUpload />);

      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const file = createFile('valid.pdf', 'application/pdf');

      await waitFor(() => {
        fireEvent.change(input, { target: { files: [file] } });
      });

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled();
      });

      await waitFor(() => {
        expect(screen.getByText('Document uploaded successfully')).toBeInTheDocument();
      });
    });

    it('accepts valid DOCX files', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            document: {
              id: 'doc-456',
              filename: 'valid.docx',
              word_count: 1000,
              preview: 'Document content...',
            },
          }),
      });

      renderWithProviders(<DocumentUpload />);

      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const file = createFile(
        'valid.docx',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      );

      await waitFor(() => {
        fireEvent.change(input, { target: { files: [file] } });
      });

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled();
      });

      await waitFor(() => {
        expect(screen.getByText('Document uploaded successfully')).toBeInTheDocument();
      });
    });

    it('accepts TXT files', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            document: {
              id: 'doc-789',
              filename: 'notes.txt',
              word_count: 200,
              preview: 'Text content...',
            },
          }),
      });

      renderWithProviders(<DocumentUpload />);

      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const file = createFile('notes.txt', 'text/plain');

      await waitFor(() => {
        fireEvent.change(input, { target: { files: [file] } });
      });

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled();
      });

      await waitFor(() => {
        expect(screen.getByText('Document uploaded successfully')).toBeInTheDocument();
      });
    });

    it('accepts markdown files', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            document: {
              id: 'doc-md',
              filename: 'readme.md',
              word_count: 300,
              preview: '# Heading...',
            },
          }),
      });

      renderWithProviders(<DocumentUpload />);

      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const file = createFile('readme.md', 'text/markdown');

      await waitFor(() => {
        fireEvent.change(input, { target: { files: [file] } });
      });

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled();
      });

      await waitFor(() => {
        expect(screen.getByText('Document uploaded successfully')).toBeInTheDocument();
      });
    });
  });

  describe('Upload flow', () => {
    it('shows uploading state', async () => {
      // Create a promise we can control
      let resolveUpload: (value: unknown) => void;
      const uploadPromise = new Promise((resolve) => {
        resolveUpload = resolve;
      });

      mockFetch.mockReturnValueOnce(uploadPromise);

      renderWithProviders(<DocumentUpload />);

      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const file = createFile('test.pdf', 'application/pdf');

      fireEvent.change(input, { target: { files: [file] } });

      await waitFor(() => {
        expect(screen.getByText('Uploading...')).toBeInTheDocument();
      });

      await act(async () => {
        resolveUpload!({
          ok: true,
          json: () =>
            Promise.resolve({
              document: { id: '1', filename: 'test.pdf', word_count: 100, preview: '' },
            }),
        });
      });

      await waitFor(() => {
        expect(screen.getByText('Document uploaded successfully')).toBeInTheDocument();
      });
    });

    it('shows success message after upload', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            document: {
              id: 'doc-success',
              filename: 'success.pdf',
              word_count: 100,
              preview: 'Content...',
            },
          }),
      });

      renderWithProviders(<DocumentUpload />);

      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const file = createFile('success.pdf', 'application/pdf');

      fireEvent.change(input, { target: { files: [file] } });

      await waitFor(() => {
        expect(screen.getByText('Document uploaded successfully')).toBeInTheDocument();
      });
    });

    it('shows error message on upload failure', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: () => Promise.resolve({ error: 'Server error occurred' }),
      });

      renderWithProviders(<DocumentUpload />);

      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const file = createFile('fail.pdf', 'application/pdf');

      fireEvent.change(input, { target: { files: [file] } });

      await waitFor(() => {
        expect(screen.getByText('Server error occurred')).toBeInTheDocument();
      });
    });

    it('handles network errors', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Network error'));

      renderWithProviders(<DocumentUpload />);

      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const file = createFile('network.pdf', 'application/pdf');

      fireEvent.change(input, { target: { files: [file] } });

      await waitFor(() => {
        expect(screen.getByText('Network error')).toBeInTheDocument();
      });
    });
  });

  describe('Document list', () => {
    it('displays uploaded document', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            document: {
              id: 'doc-list',
              filename: 'report.pdf',
              word_count: 1500,
              page_count: 5,
              preview: 'This is a preview...',
            },
          }),
      });

      renderWithProviders(<DocumentUpload />);

      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const file = createFile('report.pdf', 'application/pdf');

      fireEvent.change(input, { target: { files: [file] } });

      await waitFor(() => {
        expect(screen.getByText('report.pdf')).toBeInTheDocument();
        expect(screen.getByText(/1,500 words/)).toBeInTheDocument();
        expect(screen.getByText(/5 pages/)).toBeInTheDocument();
      });

      await waitFor(() => {
        expect(screen.getByText('Document uploaded successfully')).toBeInTheDocument();
      });
    });

    it('removes document when remove button clicked', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            document: { id: 'doc-remove', filename: 'removable.pdf', word_count: 100, preview: '' },
          }),
      });

      const onDocumentsChange = jest.fn();
      renderWithProviders(<DocumentUpload onDocumentsChange={onDocumentsChange} />);

      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const file = createFile('removable.pdf', 'application/pdf');

      fireEvent.change(input, { target: { files: [file] } });

      await waitFor(() => {
        expect(screen.getByText('removable.pdf')).toBeInTheDocument();
      });

      await waitFor(() => {
        expect(screen.getByText('Document uploaded successfully')).toBeInTheDocument();
      });

      // Click remove button
      const removeButton = screen.getByTitle('Remove document');
      fireEvent.click(removeButton);

      expect(screen.queryByText('removable.pdf')).not.toBeInTheDocument();
      expect(onDocumentsChange).toHaveBeenLastCalledWith([]);
    });

    it('calls onDocumentsChange with document IDs', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            document: {
              id: 'doc-callback',
              filename: 'callback.pdf',
              word_count: 100,
              preview: '',
            },
          }),
      });

      const onDocumentsChange = jest.fn();
      renderWithProviders(<DocumentUpload onDocumentsChange={onDocumentsChange} />);

      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const file = createFile('callback.pdf', 'application/pdf');

      fireEvent.change(input, { target: { files: [file] } });

      await waitFor(() => {
        expect(onDocumentsChange).toHaveBeenCalledWith(['doc-callback']);
      });

      await waitFor(() => {
        expect(screen.getByText('Document uploaded successfully')).toBeInTheDocument();
      });
    });

    it('shows attached count', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            document: { id: 'doc-1', filename: 'first.pdf', word_count: 100, preview: '' },
          }),
      });

      renderWithProviders(<DocumentUpload />);

      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const file = createFile('first.pdf', 'application/pdf');

      fireEvent.change(input, { target: { files: [file] } });

      await waitFor(() => {
        expect(screen.getByText('Documents (1)')).toBeInTheDocument();
      });

      await waitFor(() => {
        expect(screen.getByText('Document uploaded successfully')).toBeInTheDocument();
      });
    });
  });

  describe('Drag and drop', () => {
    it('shows drag state on dragover', () => {
      renderWithProviders(<DocumentUpload />);

      const dropZone = screen.getByRole('button', { name: /upload a document/i });

      fireEvent.dragOver(dropZone);

      // Check for visual indicator (border class change)
      expect(dropZone).toHaveClass('border-accent');
    });

    it('removes drag state on dragleave', () => {
      renderWithProviders(<DocumentUpload />);

      const dropZone = screen.getByRole('button', { name: /upload a document/i });

      fireEvent.dragOver(dropZone);
      fireEvent.dragLeave(dropZone);

      expect(dropZone).not.toHaveClass('border-accent');
    });

    it('handles file drop', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            document: { id: 'doc-drop', filename: 'dropped.pdf', word_count: 100, preview: '' },
          }),
      });

      renderWithProviders(<DocumentUpload />);

      const dropZone = screen.getByRole('button', { name: /upload a document/i });
      const file = createFile('dropped.pdf', 'application/pdf');

      const dataTransfer = { files: [file] };

      fireEvent.drop(dropZone, { dataTransfer });

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled();
      });

      await waitFor(() => {
        expect(screen.getByText('Document uploaded successfully')).toBeInTheDocument();
      });
    });
  });

  describe('Keyboard accessibility', () => {
    it('opens file picker on Enter key', () => {
      renderWithProviders(<DocumentUpload />);

      const dropZone = screen.getByRole('button', { name: /upload a document/i });
      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const clickSpy = jest.spyOn(input, 'click');

      fireEvent.keyDown(dropZone, { key: 'Enter' });

      expect(clickSpy).toHaveBeenCalled();
    });

    it('opens file picker on Space key', () => {
      renderWithProviders(<DocumentUpload />);

      const dropZone = screen.getByRole('button', { name: /upload a document/i });
      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const clickSpy = jest.spyOn(input, 'click');

      fireEvent.keyDown(dropZone, { key: ' ' });

      expect(clickSpy).toHaveBeenCalled();
    });
  });

  describe('API configuration', () => {
    it('uses custom apiBase for upload', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            document: { id: 'doc-api', filename: 'test.pdf', word_count: 100, preview: '' },
          }),
      });

      renderWithProviders(<DocumentUpload apiBase="https://api.example.com" />);

      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const file = createFile('test.pdf', 'application/pdf');

      fireEvent.change(input, { target: { files: [file] } });

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          'https://api.example.com/api/documents/upload',
          expect.any(Object),
        );
      });
    });
  });
});
