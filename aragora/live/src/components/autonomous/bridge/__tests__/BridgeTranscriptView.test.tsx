import { render, screen } from '@testing-library/react';

import type { AgentBridgeTurnRecord } from '../types';
import { BridgeTranscriptView } from '../BridgeTranscriptView';

function buildTurn(overrides: Partial<AgentBridgeTurnRecord> = {}): AgentBridgeTurnRecord {
  return {
    turn_index: 1,
    author_role: 'implementer',
    started_at: '2026-04-21T19:23:40Z',
    completed_at: '2026-04-21T19:24:09Z',
    parse_status: 'ok',
    footer: {
      summary: 'Outlined the persistence and transport slices.',
      next_actor: 'reviewer',
      needs_human: false,
      done: false,
      artifacts: [],
      tests_run: [],
    },
    body_markdown: 'First turn',
    ...overrides,
  };
}

describe('BridgeTranscriptView', () => {
  it('renders turns in turn_index order', () => {
    render(
      <BridgeTranscriptView
        turns={[
          buildTurn({ turn_index: 2, author_role: 'reviewer', body_markdown: 'Second turn' }),
          buildTurn({ turn_index: 1, author_role: 'implementer', body_markdown: 'First turn' }),
        ]}
      />,
    );

    const turnOne = screen.getByText('Turn 1');
    const turnTwo = screen.getByText('Turn 2');

    expect(
      turnOne.compareDocumentPosition(turnTwo) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('renders the bridge footer distinctly', () => {
    render(<BridgeTranscriptView turns={[buildTurn()]} />);

    expect(screen.getByText('Bridge Footer')).toBeInTheDocument();
    expect(screen.getByText('Outlined the persistence and transport slices.')).toBeInTheDocument();
    expect(screen.getByText('next_actor: reviewer')).toBeInTheDocument();
  });

  it('renders the parse_status badge', () => {
    render(
      <BridgeTranscriptView turns={[buildTurn({ parse_status: 'malformed', footer: null })]} />,
    );

    expect(screen.getAllByText('malformed').length).toBeGreaterThan(0);
  });
});
