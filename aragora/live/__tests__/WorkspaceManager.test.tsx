/**
 * Tests for WorkspaceManager component
 *
 * Tests cover:
 * - Workspace list display
 * - Workspace selection
 * - View mode switching (list, settings, team)
 * - Create workspace modal
 * - Usage indicators and stats
 * - Compliance framework display
 */

import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import {
  WorkspaceManager,
  type Workspace,
} from '../src/components/control-plane/WorkspaceManager/WorkspaceManager';
import type { Workspace as HookWorkspace } from '../src/hooks/useWorkspaces';

// Mock the useWorkspaces hook
const mockSelectWorkspace = jest.fn();
const mockCreateWorkspace = jest.fn();
const mockUpdateWorkspace = jest.fn();
const mockDeleteWorkspace = jest.fn();
const mockAddMember = jest.fn();
const mockRemoveMember = jest.fn();

jest.mock('../src/hooks/useWorkspaces', () => ({
  useWorkspaces: () => ({
    workspaces: mockHookWorkspaces,
    selectedWorkspace: mockSelectedWorkspace,
    loading: mockLoading,
    error: mockError,
    selectWorkspace: mockSelectWorkspace,
    createWorkspace: mockCreateWorkspace,
    updateWorkspace: mockUpdateWorkspace,
    deleteWorkspace: mockDeleteWorkspace,
    addMember: mockAddMember,
    removeMember: mockRemoveMember,
    loadWorkspaces: jest.fn(),
    loadWorkspace: jest.fn(),
    refetch: jest.fn(),
  }),
}));

// Default mock state
let mockHookWorkspaces: HookWorkspace[] = [];
let mockSelectedWorkspace: HookWorkspace | null = null;
let mockLoading = false;
let mockError: string | null = null;

const mockWorkspaces: Workspace[] = [
  {
    id: 'ws_001',
    name: 'Engineering',
    description: 'Software development team workspace',
    owner: 'admin@company.com',
    createdAt: '2024-01-01T00:00:00Z',
    updatedAt: '2024-01-16T10:00:00Z',
    members: [
      {
        id: 'u1',
        name: 'Alice Chen',
        email: 'alice@company.com',
        role: 'owner',
        joinedAt: '2024-01-01T00:00:00Z',
        lastActive: '2024-01-16T12:00:00Z',
      },
      {
        id: 'u2',
        name: 'Bob Smith',
        email: 'bob@company.com',
        role: 'admin',
        joinedAt: '2024-01-02T00:00:00Z',
        lastActive: '2024-01-16T10:00:00Z',
      },
      {
        id: 'u3',
        name: 'Carol Jones',
        email: 'carol@company.com',
        role: 'member',
        joinedAt: '2024-01-05T00:00:00Z',
      },
    ],
    settings: {
      defaultVertical: 'software',
      complianceFrameworks: ['OWASP', 'CWE'],
      agentLimit: 10,
      documentsQuota: 10000,
      documentsUsed: 2340,
    },
  },
  {
    id: 'ws_002',
    name: 'Legal',
    description: 'Legal and compliance workspace',
    owner: 'legal@company.com',
    createdAt: '2024-01-05T00:00:00Z',
    updatedAt: '2024-01-15T14:00:00Z',
    members: [
      {
        id: 'u4',
        name: 'David Lee',
        email: 'david@company.com',
        role: 'owner',
        joinedAt: '2024-01-05T00:00:00Z',
      },
    ],
    settings: {
      defaultVertical: 'legal',
      complianceFrameworks: ['GDPR', 'CCPA'],
      agentLimit: 5,
      documentsQuota: 5000,
      documentsUsed: 4500, // 90% usage
    },
  },
];

// Convert mockWorkspaces to hook format for use in tests
const toHookWorkspace = (ws: Workspace): HookWorkspace => ({
  id: ws.id,
  name: ws.name,
  description: ws.description,
  owner: ws.owner,
  organization_id: 'org_default',
  members: ws.members.map((m) => ({
    ...m,
    permissions:
      m.role === 'owner'
        ? ['read', 'write', 'admin', 'manage']
        : m.role === 'admin'
          ? ['read', 'write', 'admin']
          : m.role === 'member'
            ? ['read', 'write']
            : ['read'],
  })),
  createdAt: ws.createdAt,
  updatedAt: ws.updatedAt,
  settings: ws.settings,
});

describe('WorkspaceManager', () => {
  beforeEach(() => {
    // Reset mock state
    mockHookWorkspaces = mockWorkspaces.map(toHookWorkspace);
    mockSelectedWorkspace = mockHookWorkspaces[0];
    mockLoading = false;
    mockError = null;
    jest.clearAllMocks();
    // Make createWorkspace return a resolved promise
    mockCreateWorkspace.mockResolvedValue({ id: 'ws_new', name: 'New Workspace' });
  });

  describe('Header', () => {
    it('renders the workspace manager header', () => {
      render(<WorkspaceManager />);

      expect(screen.getByText('WORKSPACE MANAGER')).toBeInTheDocument();
      expect(screen.getByText('Manage workspaces and team access')).toBeInTheDocument();
    });

    it('shows new workspace button', () => {
      render(<WorkspaceManager />);

      expect(screen.getByText('+ NEW WORKSPACE')).toBeInTheDocument();
    });
  });

  describe('View Mode Tabs', () => {
    it('shows all view mode tabs', () => {
      render(<WorkspaceManager />);

      expect(screen.getByText('Workspaces')).toBeInTheDocument();
      expect(screen.getByText('Settings')).toBeInTheDocument();
      expect(screen.getByText('Team')).toBeInTheDocument();
    });

    it('starts with Workspaces tab active', () => {
      render(<WorkspaceManager />);

      const workspacesTab = screen.getByText('Workspaces');
      expect(workspacesTab).toHaveClass('text-[var(--accent)]');
    });

    it('switches to Settings tab when clicked', async () => {
      render(<WorkspaceManager />);

      await act(async () => {
        fireEvent.click(screen.getByText('Settings'));
      });

      const settingsTab = screen.getByText('Settings');
      expect(settingsTab).toHaveClass('text-[var(--accent)]');
    });

    it('switches to Team tab when clicked', async () => {
      render(<WorkspaceManager />);

      await act(async () => {
        fireEvent.click(screen.getByText('Team'));
      });

      const teamTab = screen.getByText('Team');
      expect(teamTab).toHaveClass('text-[var(--accent)]');
    });

    it('disables Settings and Team tabs when no workspace is selected', () => {
      mockHookWorkspaces = [];
      mockSelectedWorkspace = null;
      render(<WorkspaceManager />);

      const settingsTab = screen.getByText('Settings');
      const teamTab = screen.getByText('Team');

      expect(settingsTab).toHaveClass('cursor-not-allowed');
      expect(teamTab).toHaveClass('cursor-not-allowed');
    });
  });

  describe('Workspace List', () => {
    it('displays all workspaces', () => {
      render(<WorkspaceManager />);

      expect(screen.getByText('Engineering')).toBeInTheDocument();
      expect(screen.getByText('Legal')).toBeInTheDocument();
    });

    it('shows workspace descriptions', () => {
      render(<WorkspaceManager />);

      expect(screen.getByText('Software development team workspace')).toBeInTheDocument();
      expect(screen.getByText('Legal and compliance workspace')).toBeInTheDocument();
    });

    it('shows member count for each workspace', () => {
      render(<WorkspaceManager />);

      // Engineering has 3 members, Legal has 1
      expect(screen.getAllByText('3').length).toBeGreaterThan(0);
      expect(screen.getAllByText('1').length).toBeGreaterThan(0);
    });

    it('shows agent limit for each workspace', () => {
      render(<WorkspaceManager />);

      expect(screen.getByText('10')).toBeInTheDocument();
      expect(screen.getByText('5')).toBeInTheDocument();
    });

    it('shows document usage', () => {
      render(<WorkspaceManager />);

      expect(screen.getByText('2,340 / 10,000')).toBeInTheDocument();
      expect(screen.getByText('4,500 / 5,000')).toBeInTheDocument();
    });

    it('shows compliance frameworks', () => {
      render(<WorkspaceManager />);

      expect(screen.getByText('OWASP')).toBeInTheDocument();
      expect(screen.getByText('CWE')).toBeInTheDocument();
      expect(screen.getByText('GDPR')).toBeInTheDocument();
      expect(screen.getByText('CCPA')).toBeInTheDocument();
    });
  });

  describe('Workspace Selection', () => {
    it('selects first workspace by default', () => {
      render(<WorkspaceManager />);

      // Engineering should be marked as active
      expect(screen.getByText('ACTIVE')).toBeInTheDocument();
    });

    it('respects currentWorkspaceId prop', () => {
      // Set selected workspace to Legal (ws_002)
      mockSelectedWorkspace = mockHookWorkspaces.find((ws) => ws.id === 'ws_002') || null;
      render(<WorkspaceManager currentWorkspaceId="ws_002" />);

      // Legal workspace should be marked active
      const legalCard = screen.getByText('Legal').closest('div[class*="border"]');
      expect(legalCard).toHaveClass('border-[var(--accent)]');
    });

    it('calls onWorkspaceSelect when workspace is clicked', async () => {
      const mockOnSelect = jest.fn();
      render(<WorkspaceManager onWorkspaceSelect={mockOnSelect} />);

      await act(async () => {
        fireEvent.click(screen.getByText('Legal'));
      });

      expect(mockOnSelect).toHaveBeenCalledWith(
        expect.objectContaining({ id: 'ws_002', name: 'Legal' }),
      );
    });

    it('shows ACTIVE badge on selected workspace', async () => {
      render(<WorkspaceManager />);

      // Initially Engineering is selected
      let activeLabels = screen.getAllByText('ACTIVE');
      expect(activeLabels).toHaveLength(1);

      // Click on Legal
      await act(async () => {
        fireEvent.click(screen.getByText('Legal'));
      });

      // ACTIVE badge should still exist (just moved to Legal)
      activeLabels = screen.getAllByText('ACTIVE');
      expect(activeLabels).toHaveLength(1);
    });
  });

  describe('Usage Indicators', () => {
    it('shows usage progress bar', () => {
      const { container } = render(<WorkspaceManager />);

      // Look for progress bars
      const progressBars = container.querySelectorAll('.h-full.transition-all');
      expect(progressBars.length).toBeGreaterThan(0);
    });

    it('uses red color for high usage (90%+)', () => {
      const { container } = render(<WorkspaceManager />);

      // Legal workspace has 90% usage, should show red
      const redBars = container.querySelectorAll('[class*="bg-red-500"]');
      expect(redBars.length).toBeGreaterThan(0);
    });
  });

  describe('Create Workspace Modal', () => {
    it('opens modal when New Workspace button is clicked', async () => {
      render(<WorkspaceManager />);

      await act(async () => {
        fireEvent.click(screen.getByText('+ NEW WORKSPACE'));
      });

      expect(screen.getByText('CREATE WORKSPACE')).toBeInTheDocument();
      expect(screen.getByPlaceholderText('Workspace name')).toBeInTheDocument();
      expect(screen.getByPlaceholderText('Workspace description')).toBeInTheDocument();
    });

    it('has name and description fields', async () => {
      render(<WorkspaceManager />);

      await act(async () => {
        fireEvent.click(screen.getByText('+ NEW WORKSPACE'));
      });

      expect(screen.getByText('NAME')).toBeInTheDocument();
      expect(screen.getByText('DESCRIPTION')).toBeInTheDocument();
    });

    it('closes modal when Cancel is clicked', async () => {
      render(<WorkspaceManager />);

      await act(async () => {
        fireEvent.click(screen.getByText('+ NEW WORKSPACE'));
      });

      expect(screen.getByText('CREATE WORKSPACE')).toBeInTheDocument();

      await act(async () => {
        fireEvent.click(screen.getByText('CANCEL'));
      });

      expect(screen.queryByText('CREATE WORKSPACE')).not.toBeInTheDocument();
    });

    it('has Create button', async () => {
      render(<WorkspaceManager />);

      await act(async () => {
        fireEvent.click(screen.getByText('+ NEW WORKSPACE'));
      });

      expect(screen.getByRole('button', { name: 'CREATE' })).toBeInTheDocument();
    });

    it('closes modal on form submission', async () => {
      render(<WorkspaceManager />);

      await act(async () => {
        fireEvent.click(screen.getByText('+ NEW WORKSPACE'));
      });

      // Fill form
      await act(async () => {
        fireEvent.change(screen.getByPlaceholderText('Workspace name'), {
          target: { value: 'New Workspace' },
        });
      });

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'CREATE' }));
      });

      await waitFor(() => {
        expect(screen.queryByText('CREATE WORKSPACE')).not.toBeInTheDocument();
      });
    });
  });

  describe('Settings View', () => {
    it('shows WorkspaceSettings component in settings view', async () => {
      render(<WorkspaceManager />);

      await act(async () => {
        fireEvent.click(screen.getByText('Settings'));
      });

      // WorkspaceSettings should render - look for workspace name field
      expect(screen.getByText('WORKSPACE NAME')).toBeInTheDocument();
    });
  });

  describe('Team View', () => {
    it('shows TeamAccessPanel component in team view', async () => {
      render(<WorkspaceManager />);

      await act(async () => {
        fireEvent.click(screen.getByText('Team'));
      });

      // TeamAccessPanel should render with workspace members
      expect(screen.getByText('Team Members')).toBeInTheDocument();
    });
  });

  describe('Empty State', () => {
    it('handles empty workspaces array', () => {
      mockHookWorkspaces = [];
      mockSelectedWorkspace = null;
      render(<WorkspaceManager />);

      // Should still render the header
      expect(screen.getByText('WORKSPACE MANAGER')).toBeInTheDocument();
      // But no workspace cards
      expect(screen.queryByText('ACTIVE')).not.toBeInTheDocument();
    });
  });

  describe('CSS Classes', () => {
    it('applies custom className', () => {
      const { container } = render(<WorkspaceManager className="custom-class" />);

      expect(container.firstChild).toHaveClass('custom-class');
    });
  });
});
