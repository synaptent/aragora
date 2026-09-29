import { useEffect, useState } from 'react';
import { useVSCodeAPI } from './hooks/useVSCodeAPI';
import { DebateView } from './components/DebateView';
import { ReviewView } from './components/ReviewView';
import type { ExtensionMessage, WebviewState } from './types';

declare global {
  interface Window {
    initialView?: 'debate' | 'review';
  }
}

function App() {
  const vscode = useVSCodeAPI();
  const [state, setState] = useState<WebviewState>({
    debates: [],
    reviews: [],
    findings: [],
    settings: {
      apiUrl: 'https://api.aragora.ai',
      defaultAgents: ['claude', 'gpt-4'],
      defaultRounds: 3,
      autoAnalyze: true,
      showInlineHints: true,
      theme: 'auto',
    },
    connectionStatus: 'disconnected',
  });

  const [currentView] = useState<'debate' | 'review'>(window.initialView || 'debate');

  // Handle messages from extension
  useEffect(() => {
    const handleMessage = (event: MessageEvent<ExtensionMessage>) => {
      const message = event.data;

      switch (message.type) {
        case 'state_sync':
          setState(message.state);
          break;

        case 'debate_started':
        case 'debate_updated':
          setState((prev) => ({
            ...prev,
            debates: prev.debates.some((d) => d.id === message.debate.id)
              ? prev.debates.map((d) => (d.id === message.debate.id ? message.debate : d))
              : [...prev.debates, message.debate],
          }));
          break;

        case 'agent_message':
          setState((prev) => ({
            ...prev,
            debates: prev.debates.map((d) => ({
              ...d,
              messages:
                d.id === message.message.id.split('-')[0]
                  ? [...d.messages, message.message]
                  : d.messages,
            })),
          }));
          break;

        case 'consensus_reached':
          setState((prev) => ({
            ...prev,
            debates: prev.debates.map((d) => ({
              ...d,
              consensus: d.status === 'running' ? message.consensus : d.consensus,
              status: d.status === 'running' ? 'completed' : d.status,
            })),
          }));
          break;

        case 'review_started':
        case 'review_completed':
          setState((prev) => ({
            ...prev,
            reviews: prev.reviews.some((r) => r.id === message.review.id)
              ? prev.reviews.map((r) => (r.id === message.review.id ? message.review : r))
              : [...prev.reviews, message.review],
          }));
          break;

        case 'review_comment':
          setState((prev) => ({
            ...prev,
            reviews: prev.reviews.map((r) => ({
              ...r,
              comments: r.comments.some((c) => c.id === message.comment.id)
                ? r.comments.map((c) => (c.id === message.comment.id ? message.comment : c))
                : [...r.comments, message.comment],
            })),
          }));
          break;

        case 'settings_updated':
          setState((prev) => ({ ...prev, settings: message.settings }));
          break;
      }
    };

    window.addEventListener('message', handleMessage);

    // Request initial state
    vscode.postMessage({ type: 'ready' });

    return () => window.removeEventListener('message', handleMessage);
  }, [vscode]);

  const activeDebate =
    state.debates.find((d) => d.status === 'running' || d.status === 'completed') ||
    state.debates[state.debates.length - 1];

  const activeReview =
    state.reviews.find((r) => r.status === 'in_progress' || r.status === 'completed') ||
    state.reviews[state.reviews.length - 1];

  return (
    <div className="app">
      {currentView === 'debate' ? (
        <DebateView
          debate={activeDebate}
          connectionStatus={state.connectionStatus}
          onStartDebate={(question, agents, rounds) => {
            vscode.postMessage({ type: 'start_debate', question, agents, rounds });
          }}
          onStopDebate={(debateId) => {
            vscode.postMessage({ type: 'stop_debate', debateId });
          }}
          onCopyResult={(debateId) => {
            vscode.postMessage({ type: 'copy_result', debateId });
          }}
          onExportDebate={(debateId, format) => {
            vscode.postMessage({ type: 'export_debate', debateId, format });
          }}
          onSendFeedback={(debateId, vote) => {
            vscode.postMessage({ type: 'send_feedback', debateId, vote });
          }}
        />
      ) : (
        <ReviewView
          review={activeReview}
          onApplyFix={(reviewId, commentId) => {
            vscode.postMessage({ type: 'apply_fix', reviewId, commentId });
          }}
          onApplyAllFixes={(reviewId) => {
            vscode.postMessage({ type: 'apply_all_fixes', reviewId });
          }}
          onDismissComment={(reviewId, commentId) => {
            vscode.postMessage({ type: 'dismiss_comment', reviewId, commentId });
          }}
          onNavigateToComment={(reviewId, commentId) => {
            vscode.postMessage({ type: 'navigate_to_comment', reviewId, commentId });
          }}
        />
      )}
    </div>
  );
}

export default App;
