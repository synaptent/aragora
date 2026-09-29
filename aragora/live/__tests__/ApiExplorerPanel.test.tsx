import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ApiExplorerPanel } from '@/components/ApiExplorerPanel';

// ---------------------------------------------------------------------------
// Mock OpenAPI spec (minimal but realistic)
// ---------------------------------------------------------------------------
const MOCK_OPENAPI_SPEC = {
  openapi: '3.1.0',
  info: { title: 'Aragora API', version: '1.0.0', description: 'Decision Integrity Platform' },
  paths: {
    '/api/debates': {
      get: {
        summary: 'List all debates',
        tags: ['Debates'],
        parameters: [
          {
            name: 'limit',
            in: 'query',
            schema: { type: 'integer' },
            description: 'Max results (1-100)',
          },
          {
            name: 'offset',
            in: 'query',
            schema: { type: 'integer' },
            description: 'Pagination offset',
          },
        ],
        responses: { '200': { description: 'Debate list' } },
        security: [{ BearerAuth: [] }],
      },
      post: {
        summary: 'Create new debate',
        tags: ['Debates'],
        requestBody: {
          required: true,
          content: {
            'application/json': {
              schema: {
                type: 'object',
                properties: {
                  topic: { type: 'string' },
                  agents: { type: 'array', items: { type: 'string' } },
                  rounds: { type: 'integer' },
                },
                required: ['topic'],
              },
              example: { topic: 'Should AI be regulated?', agents: ['claude', 'gpt4'], rounds: 3 },
            },
          },
        },
        responses: { '201': { description: 'Debate created' } },
        security: [{ BearerAuth: [] }],
      },
    },
    '/api/debates/{id}': {
      get: {
        summary: 'Get debate by ID',
        tags: ['Debates'],
        parameters: [
          {
            name: 'id',
            in: 'path',
            required: true,
            schema: { type: 'string' },
            description: 'Debate UUID',
          },
        ],
        responses: { '200': { description: 'Debate details' } },
      },
    },
    '/api/debates/slug/{slug}': {
      get: {
        summary: 'Get debate by slug',
        tags: ['Debates'],
        parameters: [{ name: 'slug', in: 'path', required: true, schema: { type: 'string' } }],
        responses: { '200': { description: 'Debate details' } },
      },
    },
    '/api/agents/available': {
      get: {
        summary: 'List available agents',
        tags: ['Agents'],
        responses: { '200': { description: 'Agent list' } },
      },
    },
    '/api/leaderboard': {
      get: {
        summary: 'Get agent rankings',
        tags: ['Agents'],
        parameters: [
          { name: 'limit', in: 'query', schema: { type: 'integer' } },
          { name: 'domain', in: 'query', schema: { type: 'string' } },
        ],
        responses: { '200': { description: 'Leaderboard' } },
      },
    },
    '/api/health': {
      get: {
        summary: 'Health check',
        tags: ['System'],
        responses: { '200': { description: 'Health status' } },
      },
    },
    '/api/memory/query': {
      get: {
        summary: 'Query memory',
        tags: ['Memory'],
        parameters: [
          { name: 'query', in: 'query', required: true, schema: { type: 'string' } },
          {
            name: 'tier',
            in: 'query',
            schema: { type: 'string' },
            description: 'fast, medium, slow, glacial',
          },
        ],
        responses: { '200': { description: 'Memory results' } },
        security: [{ BearerAuth: [] }],
      },
    },
    '/api/v1/workflows': {
      get: {
        summary: 'List workflows',
        tags: ['Workflows'],
        responses: { '200': { description: 'Workflow list' } },
        security: [{ BearerAuth: [] }],
      },
    },
  },
  tags: [
    { name: 'Debates', description: 'Core debate management' },
    { name: 'Agents', description: 'Agent profiles and rankings' },
    { name: 'System', description: 'Health checks' },
    { name: 'Memory', description: 'Memory management' },
    { name: 'Workflows', description: 'Workflow automation' },
  ],
};

// ---------------------------------------------------------------------------
// Mock fetch -- returns OpenAPI spec on first call, then handles API calls
// ---------------------------------------------------------------------------
const mockFetch = jest.fn();
global.fetch = mockFetch;

function setupSpecFetch() {
  // First call loads the OpenAPI spec, subsequent calls are API requests
  mockFetch.mockImplementation((url: string) => {
    if (typeof url === 'string' && url.includes('openapi.json')) {
      return Promise.resolve({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: () => Promise.resolve(MOCK_OPENAPI_SPEC),
        headers: new Map(),
      });
    }
    // Default for API requests
    return Promise.resolve({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve({ data: {} }),
      text: () => Promise.resolve('{}'),
      headers: new Headers({ 'content-type': 'application/json' }),
    });
  });
}

// Mock CollapsibleSection to simplify testing
jest.mock('@/components/CollapsibleSection', () => ({
  CollapsibleSection: ({ children, title }: { children: React.ReactNode; title: string }) => (
    <div data-testid={`collapsible-${title}`}>
      <span>{title}</span>
      {children}
    </div>
  ),
}));

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] || null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  };
})();
Object.defineProperty(window, 'localStorage', { value: localStorageMock });

describe('ApiExplorerPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorageMock.clear();
    setupSpecFetch();
  });

  describe('Spec Loading', () => {
    it('shows loading state initially', () => {
      // Use a mock that never resolves to keep loading state
      mockFetch.mockImplementation(() => new Promise(() => {}));
      render(<ApiExplorerPanel />);
      expect(screen.getByText(/Loading OpenAPI specification/i)).toBeInTheDocument();
    });

    it('shows error state when spec fails to load', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (typeof url === 'string' && url.includes('openapi.json')) {
          return Promise.reject(new Error('Network error'));
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      });

      render(<ApiExplorerPanel />);

      await waitFor(() => {
        expect(screen.getByText(/Could not load live OpenAPI spec/i)).toBeInTheDocument();
      });
    });

    it('shows retry button on error', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (typeof url === 'string' && url.includes('openapi.json')) {
          return Promise.reject(new Error('Network error'));
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      });

      render(<ApiExplorerPanel />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /RETRY/i })).toBeInTheDocument();
      });
    });
  });

  describe('Rendering', () => {
    it('renders endpoint groups from OpenAPI spec', async () => {
      render(<ApiExplorerPanel />);

      await waitFor(() => {
        // Tags appear in both dropdown and collapsible sections, use getAllByText
        expect(screen.getAllByText(/Debates/).length).toBeGreaterThan(0);
        expect(screen.getAllByText(/Agents/).length).toBeGreaterThan(0);
        expect(screen.getAllByText(/System/).length).toBeGreaterThan(0);
      });
    });

    it('displays total endpoint count', async () => {
      render(<ApiExplorerPanel />);

      await waitFor(() => {
        // "9 endpoints" appears in the stats bar and the filter count area
        const matches = screen.getAllByText(/9 endpoints/);
        expect(matches.length).toBeGreaterThan(0);
      });
    });

    it('displays endpoint methods', async () => {
      render(<ApiExplorerPanel />);

      await waitFor(() => {
        const getButtons = screen.getAllByText('GET');
        expect(getButtons.length).toBeGreaterThan(0);
      });
    });

    it('shows POST method labels', async () => {
      render(<ApiExplorerPanel />);

      await waitFor(() => {
        const postButtons = screen.getAllByText('POST');
        expect(postButtons.length).toBeGreaterThan(0);
      });
    });

    it('shows API version info', async () => {
      render(<ApiExplorerPanel />);

      await waitFor(() => {
        expect(screen.getByText(/v1\.0\.0/)).toBeInTheDocument();
        expect(screen.getByText(/OpenAPI 3\.1\.0/)).toBeInTheDocument();
      });
    });
  });

  describe('Endpoint Interaction', () => {
    it('selects endpoint on click and shows details', async () => {
      render(<ApiExplorerPanel />);

      await waitFor(() => {
        expect(screen.getByText('List all debates')).toBeInTheDocument();
      });

      const listDebatesButton = screen.getByText('List all debates').closest('button');
      expect(listDebatesButton).toBeInTheDocument();
      fireEvent.click(listDebatesButton!);

      await waitFor(() => {
        const heading = screen.getByRole('heading', { level: 2, name: 'List all debates' });
        expect(heading).toBeInTheDocument();
      });
    });

    it('shows path parameters input when endpoint has path params', async () => {
      render(<ApiExplorerPanel />);

      await waitFor(() => {
        expect(screen.getByText('Get debate by slug')).toBeInTheDocument();
      });

      const slugButton = screen.getByText('Get debate by slug').closest('button');
      fireEvent.click(slugButton!);

      await waitFor(() => {
        expect(screen.getByText(/Path Parameters/i)).toBeInTheDocument();
      });
    });

    it('shows query parameters input when endpoint has query params', async () => {
      render(<ApiExplorerPanel />);

      await waitFor(() => {
        expect(screen.getByText('List all debates')).toBeInTheDocument();
      });

      const listButton = screen.getByText('List all debates').closest('button');
      fireEvent.click(listButton!);

      await waitFor(() => {
        expect(screen.getByText(/Query Parameters/i)).toBeInTheDocument();
      });
    });
  });

  describe('Try It Feature', () => {
    it('shows Try It button for endpoints', async () => {
      render(<ApiExplorerPanel />);

      await waitFor(() => {
        expect(screen.getByText('Get agent rankings')).toBeInTheDocument();
      });

      const endpoint = screen.getByText('Get agent rankings').closest('button');
      fireEvent.click(endpoint!);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /TRY IT - GET/i })).toBeInTheDocument();
      });
    });

    it('makes API request when Try It is clicked', async () => {
      render(<ApiExplorerPanel />);

      await waitFor(() => {
        expect(screen.getByText('Get agent rankings')).toBeInTheDocument();
      });

      const endpoint = screen.getByText('Get agent rankings').closest('button');
      fireEvent.click(endpoint!);

      await waitFor(() => {
        const sendButton = screen.getByRole('button', { name: /TRY IT - GET/i });
        fireEvent.click(sendButton);
      });

      // fetch was called for the spec + for the API request
      await waitFor(() => {
        expect(mockFetch.mock.calls.length).toBeGreaterThan(1);
      });
    });

    it('displays response after successful request', async () => {
      render(<ApiExplorerPanel />);

      await waitFor(() => {
        expect(screen.getByText('Health check')).toBeInTheDocument();
      });

      const endpoint = screen.getByText('Health check').closest('button');
      fireEvent.click(endpoint!);

      await waitFor(() => {
        const sendButton = screen.getByRole('button', { name: /TRY IT - GET/i });
        fireEvent.click(sendButton);
      });

      await waitFor(() => {
        expect(screen.getByText(/Response Body/i)).toBeInTheDocument();
      });
    });

    it('shows error message on failed request', async () => {
      // Spec loads fine, but subsequent requests fail
      mockFetch.mockImplementation((url: string) => {
        if (typeof url === 'string' && url.includes('openapi.json')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            statusText: 'OK',
            json: () => Promise.resolve(MOCK_OPENAPI_SPEC),
            headers: new Map(),
          });
        }
        return Promise.reject(new Error('Network error'));
      });

      render(<ApiExplorerPanel />);

      await waitFor(() => {
        expect(screen.getByText('Health check')).toBeInTheDocument();
      });

      const endpoint = screen.getByText('Health check').closest('button');
      fireEvent.click(endpoint!);

      await waitFor(() => {
        const sendButton = screen.getByRole('button', { name: /TRY IT - GET/i });
        fireEvent.click(sendButton);
      });

      await waitFor(() => {
        expect(screen.getByText(/Network error/i)).toBeInTheDocument();
      });
    });
  });

  describe('Search/Filter', () => {
    it('has a search input', async () => {
      render(<ApiExplorerPanel />);

      await waitFor(() => {
        const searchInput = screen.getByPlaceholderText(/search endpoints/i);
        expect(searchInput).toBeInTheDocument();
      });
    });

    it('filters endpoints based on search query', async () => {
      render(<ApiExplorerPanel />);

      await waitFor(() => {
        expect(screen.getByText('List all debates')).toBeInTheDocument();
      });

      const searchInput = screen.getByPlaceholderText(/search endpoints/i);
      fireEvent.change(searchInput, { target: { value: 'memory' } });

      await waitFor(() => {
        // "Memory" appears in dropdown option and collapsible section
        expect(screen.getAllByText(/Memory/).length).toBeGreaterThan(0);
        expect(screen.getByText('Query memory')).toBeInTheDocument();
      });
    });

    it('shows filtered count', async () => {
      render(<ApiExplorerPanel />);

      await waitFor(() => {
        expect(screen.getByText('List all debates')).toBeInTheDocument();
      });

      const searchInput = screen.getByPlaceholderText(/search endpoints/i);
      fireEvent.change(searchInput, { target: { value: 'health' } });

      await waitFor(() => {
        expect(screen.getByText(/1 of 9/)).toBeInTheDocument();
      });
    });

    it('has method filter buttons', async () => {
      render(<ApiExplorerPanel />);

      await waitFor(() => {
        // Method filter pills
        expect(screen.getByRole('button', { name: 'ALL' })).toBeInTheDocument();
        // Multiple GET buttons will exist (filter pill + endpoint labels)
        const getButtons = screen.getAllByText('GET');
        expect(getButtons.length).toBeGreaterThan(0);
      });
    });

    it('filters by method when clicking method pill', async () => {
      render(<ApiExplorerPanel />);

      await waitFor(() => {
        expect(screen.getByText('List all debates')).toBeInTheDocument();
      });

      // Click POST filter - the first POST button in the filter bar
      const filterButtons = screen.getAllByText('POST');
      // Find the one that's a direct child of the filter area (small pill)
      const postFilter = filterButtons[0];
      fireEvent.click(postFilter);

      await waitFor(() => {
        // Only POST endpoints should show - "Create new debate" should be there
        expect(screen.getByText('Create new debate')).toBeInTheDocument();
        // The endpoint count should reflect filtering
        expect(screen.getByText(/1 of 9/)).toBeInTheDocument();
      });
    });

    it('has a tag filter dropdown', async () => {
      render(<ApiExplorerPanel />);

      await waitFor(() => {
        const tagSelect = screen.getByRole('combobox');
        expect(tagSelect).toBeInTheDocument();
      });
    });
  });

  describe('Schema Tab', () => {
    it('shows schema tab', async () => {
      render(<ApiExplorerPanel />);

      await waitFor(() => {
        expect(screen.getByText('List all debates')).toBeInTheDocument();
      });

      const endpoint = screen.getByText('List all debates').closest('button');
      fireEvent.click(endpoint!);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /SCHEMA/i })).toBeInTheDocument();
      });
    });

    it('switches to schema tab on click', async () => {
      render(<ApiExplorerPanel />);

      await waitFor(() => {
        expect(screen.getByText('List all debates')).toBeInTheDocument();
      });

      const endpoint = screen.getByText('List all debates').closest('button');
      fireEvent.click(endpoint!);

      await waitFor(() => {
        const schemaTab = screen.getByRole('button', { name: /SCHEMA/i });
        fireEvent.click(schemaTab);
      });

      await waitFor(() => {
        // Schema tab should show parameters table
        expect(screen.getByText(/PARAMETERS/)).toBeInTheDocument();
      });
    });
  });

  describe('Authentication Indicator', () => {
    it('shows auth required badge for protected endpoints', async () => {
      render(<ApiExplorerPanel />);

      await waitFor(() => {
        expect(screen.getByText('List all debates')).toBeInTheDocument();
      });

      const debateList = screen.getByText('List all debates').closest('button');
      fireEvent.click(debateList!);

      await waitFor(() => {
        expect(screen.getByText(/AUTH REQUIRED/i)).toBeInTheDocument();
      });
    });
  });

  describe('Request Body', () => {
    it('shows request body textarea for POST endpoints', async () => {
      render(<ApiExplorerPanel />);

      await waitFor(() => {
        expect(screen.getByText('Create new debate')).toBeInTheDocument();
      });

      const postButton = screen.getByText('Create new debate').closest('button');
      fireEvent.click(postButton!);

      await waitFor(() => {
        expect(screen.getByText(/Request Body/i)).toBeInTheDocument();
        expect(screen.getByPlaceholderText(/JSON request body/i)).toBeInTheDocument();
      });
    });

    it('pre-fills example request body', async () => {
      render(<ApiExplorerPanel />);

      await waitFor(() => {
        expect(screen.getByText('Create new debate')).toBeInTheDocument();
      });

      const postButton = screen.getByText('Create new debate').closest('button');
      fireEvent.click(postButton!);

      await waitFor(() => {
        const textarea = screen.getByPlaceholderText(/JSON request body/i) as HTMLTextAreaElement;
        expect(textarea.value).toContain('Should AI be regulated?');
      });
    });
  });

  describe('Placeholder State', () => {
    it('shows placeholder when no endpoint is selected', async () => {
      render(<ApiExplorerPanel />);

      await waitFor(() => {
        expect(screen.getByText(/Select an endpoint to explore/i)).toBeInTheDocument();
      });
    });

    it('shows endpoint count in placeholder', async () => {
      render(<ApiExplorerPanel />);

      await waitFor(() => {
        expect(screen.getByText(/Browse 9 endpoints across 5 categories/i)).toBeInTheDocument();
      });
    });
  });

  describe('URL Preview', () => {
    it('shows URL preview when endpoint is selected', async () => {
      render(<ApiExplorerPanel />);

      await waitFor(() => {
        expect(screen.getByText('Health check')).toBeInTheDocument();
      });

      const endpoint = screen.getByText('Health check').closest('button');
      fireEvent.click(endpoint!);

      await waitFor(() => {
        // Path appears in sidebar button, endpoint header, and URL preview
        const matches = screen.getAllByText(/\/api\/health/);
        expect(matches.length).toBeGreaterThan(1); // at least in header + URL preview
      });
    });
  });
});
