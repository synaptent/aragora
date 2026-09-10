'use client';

import { useState, useEffect, useCallback } from 'react';
import { logger } from '@/utils/logger';
import { useBackend } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';

interface Finding {
  id: string;
  title: string;
  description: string;
  severity: 'critical' | 'high' | 'medium' | 'low' | 'info';
  status: string;
  audit_type: string;
  category: string;
  confidence: number;
  evidence_text: string;
  evidence_location: string;
  recommendation: string;
  found_by: string;
  document_id: string;
  created_at: string;
}

interface WorkflowData {
  finding_id: string;
  current_state: string;
  assigned_to: string | null;
  priority: number;
  due_date: string | null;
  history: WorkflowEvent[];
}

interface WorkflowEvent {
  id: string;
  event_type: string;
  timestamp: string;
  user_id: string;
  user_name: string;
  comment?: string;
  from_state?: string;
  to_state?: string;
}

interface Props {
  finding: Finding | null;
  isOpen: boolean;
  onClose: () => void;
  onUpdate?: () => void;
}

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'bg-acid-red/20 text-acid-red border-acid-red',
  high: 'bg-acid-orange/20 text-acid-orange border-acid-orange',
  medium: 'bg-acid-yellow/20 text-[var(--acid-yellow)] border-acid-yellow',
  low: 'bg-acid-blue/20 text-acid-blue border-acid-blue',
  info: 'bg-muted/20 text-muted border-muted',
};

const STATUS_COLORS: Record<string, string> = {
  open: 'bg-acid-red/20 text-acid-red',
  triaging: 'bg-acid-yellow/20 text-[var(--acid-yellow)]',
  investigating: 'bg-acid-blue/20 text-acid-blue',
  remediating: 'bg-acid-purple/20 text-acid-purple',
  resolved: 'bg-[var(--accent)]/20 text-[var(--accent)]',
  false_positive: 'bg-muted/20 text-muted',
  accepted_risk: 'bg-acid-orange/20 text-acid-orange',
  duplicate: 'bg-muted/20 text-muted',
};

const VALID_TRANSITIONS: Record<string, string[]> = {
  open: ['triaging', 'investigating', 'false_positive', 'duplicate'],
  triaging: ['investigating', 'false_positive', 'accepted_risk', 'duplicate', 'open'],
  investigating: ['remediating', 'false_positive', 'accepted_risk', 'triaging'],
  remediating: ['resolved', 'investigating', 'accepted_risk'],
  resolved: ['open'],
  false_positive: ['open'],
  accepted_risk: ['open', 'remediating'],
  duplicate: ['open'],
};

const PRIORITY_LABELS: Record<number, string> = {
  1: 'Critical',
  2: 'High',
  3: 'Medium',
  4: 'Low',
  5: 'Lowest',
};

export function FindingDetailDrawer({ finding, isOpen, onClose, onUpdate }: Props) {
  const { config: backendConfig } = useBackend();
  const { tokens, user } = useAuth();
  const [workflow, setWorkflow] = useState<WorkflowData | null>(null);
  const [, _setLoading] = useState(false);
  const [newComment, setNewComment] = useState('');
  const [showAssign, setShowAssign] = useState(false);
  const [assignUserId, setAssignUserId] = useState('');
  const [updating, setUpdating] = useState(false);

  const fetchWorkflow = useCallback(async () => {
    if (!finding) return;
    try {
      const response = await fetch(
        `${backendConfig.api}/api/audit/findings/${finding.id}/history`,
        { headers: { Authorization: `Bearer ${tokens?.access_token || ''}` } },
      );
      if (response.ok) {
        const data = await response.json();
        setWorkflow(data);
      }
    } catch (err) {
      logger.error('Failed to fetch workflow:', err);
    }
  }, [finding, backendConfig.api, tokens?.access_token]);

  useEffect(() => {
    if (isOpen && finding) {
      fetchWorkflow();
    }
  }, [isOpen, finding, fetchWorkflow]);

  const handleStatusChange = async (newStatus: string) => {
    if (!finding) return;
    setUpdating(true);
    try {
      const response = await fetch(`${backendConfig.api}/api/audit/findings/${finding.id}/status`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokens?.access_token || ''}`,
          'X-User-ID': user?.id || 'anonymous',
        },
        body: JSON.stringify({ status: newStatus }),
      });
      if (response.ok) {
        fetchWorkflow();
        onUpdate?.();
      }
    } catch (err) {
      logger.error('Failed to update status:', err);
    } finally {
      setUpdating(false);
    }
  };

  const handleAddComment = async () => {
    if (!finding || !newComment.trim()) return;
    setUpdating(true);
    try {
      const response = await fetch(
        `${backendConfig.api}/api/audit/findings/${finding.id}/comments`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${tokens?.access_token || ''}`,
            'X-User-ID': user?.id || 'anonymous',
          },
          body: JSON.stringify({ comment: newComment }),
        },
      );
      if (response.ok) {
        setNewComment('');
        fetchWorkflow();
      }
    } catch (err) {
      logger.error('Failed to add comment:', err);
    } finally {
      setUpdating(false);
    }
  };

  const handleAssign = async () => {
    if (!finding || !assignUserId.trim()) return;
    setUpdating(true);
    try {
      const response = await fetch(`${backendConfig.api}/api/audit/findings/${finding.id}/assign`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokens?.access_token || ''}`,
          'X-User-ID': user?.id || 'anonymous',
        },
        body: JSON.stringify({ user_id: assignUserId }),
      });
      if (response.ok) {
        setAssignUserId('');
        setShowAssign(false);
        fetchWorkflow();
        onUpdate?.();
      }
    } catch (err) {
      logger.error('Failed to assign:', err);
    } finally {
      setUpdating(false);
    }
  };

  const handleSetPriority = async (priority: number) => {
    if (!finding) return;
    setUpdating(true);
    try {
      const response = await fetch(
        `${backendConfig.api}/api/audit/findings/${finding.id}/priority`,
        {
          method: 'PATCH',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${tokens?.access_token || ''}`,
            'X-User-ID': user?.id || 'anonymous',
          },
          body: JSON.stringify({ priority }),
        },
      );
      if (response.ok) {
        fetchWorkflow();
        onUpdate?.();
      }
    } catch (err) {
      logger.error('Failed to set priority:', err);
    } finally {
      setUpdating(false);
    }
  };

  if (!isOpen) return null;

  const currentState = workflow?.current_state || finding?.status || 'open';
  const validTransitions = VALID_TRANSITIONS[currentState] || [];

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50" onClick={onClose} />

      {/* Drawer */}
      <div className="fixed right-0 top-0 h-full w-full max-w-2xl bg-background border-l border-border z-50 overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-surface border-b border-border p-4 flex items-start justify-between">
          <div className="flex-1 min-w-0 pr-4">
            <div className="flex items-center gap-2 mb-1">
              <span
                className={`px-2 py-0.5 text-xs font-theme-data rounded border ${SEVERITY_COLORS[finding?.severity || 'info']}`}
              >
                {finding?.severity?.toUpperCase()}
              </span>
              <span
                className={`px-2 py-0.5 text-xs font-theme-data rounded ${STATUS_COLORS[currentState]}`}
              >
                {currentState.toUpperCase().replace('_', ' ')}
              </span>
            </div>
            <h2 className="font-theme-data text-lg truncate">
              {finding?.title || 'Finding Details'}
            </h2>
          </div>
          <button onClick={onClose} className="text-muted hover:text-foreground text-xl">
            ✕
          </button>
        </div>

        {finding && (
          <div className="p-4 space-y-6">
            {/* Description */}
            <section>
              <h3 className="text-xs font-theme-data text-muted mb-2">DESCRIPTION</h3>
              <p className="text-sm">{finding.description}</p>
            </section>

            {/* Evidence */}
            {finding.evidence_text && (
              <section>
                <h3 className="text-xs font-theme-data text-muted mb-2">EVIDENCE</h3>
                <div className="bg-surface p-3 rounded border border-border font-theme-data text-sm whitespace-pre-wrap">
                  {finding.evidence_text}
                </div>
                {finding.evidence_location && (
                  <div className="text-xs text-muted mt-1">
                    Location: {finding.evidence_location}
                  </div>
                )}
              </section>
            )}

            {/* Recommendation */}
            {finding.recommendation && (
              <section>
                <h3 className="text-xs font-theme-data text-muted mb-2">RECOMMENDATION</h3>
                <p className="text-sm">{finding.recommendation}</p>
              </section>
            )}

            {/* Metadata */}
            <section>
              <h3 className="text-xs font-theme-data text-muted mb-2">DETAILS</h3>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <span className="text-muted">Type:</span>{' '}
                  <span className="font-theme-data">{finding.audit_type}</span>
                </div>
                <div>
                  <span className="text-muted">Category:</span>{' '}
                  <span className="font-theme-data">{finding.category}</span>
                </div>
                <div>
                  <span className="text-muted">Confidence:</span>{' '}
                  <span className="font-theme-data">{Math.round(finding.confidence * 100)}%</span>
                </div>
                <div>
                  <span className="text-muted">Found by:</span>{' '}
                  <span className="font-theme-data">{finding.found_by}</span>
                </div>
              </div>
            </section>

            {/* Workflow Actions */}
            <section className="border-t border-border pt-4">
              <h3 className="text-xs font-theme-data text-muted mb-3">WORKFLOW</h3>

              {/* Assignment */}
              <div className="mb-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm text-muted">Assigned to:</span>
                  {workflow?.assigned_to ? (
                    <span className="font-theme-data text-sm">{workflow.assigned_to}</span>
                  ) : (
                    <span className="text-muted text-sm">Unassigned</span>
                  )}
                </div>
                {showAssign ? (
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={assignUserId}
                      onChange={(e) => setAssignUserId(e.target.value)}
                      placeholder="User ID"
                      className="input flex-1 text-sm"
                    />
                    <button
                      onClick={handleAssign}
                      disabled={updating || !assignUserId.trim()}
                      className="btn btn-sm btn-primary"
                    >
                      Assign
                    </button>
                    <button onClick={() => setShowAssign(false)} className="btn btn-sm btn-ghost">
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setShowAssign(true)}
                    className="btn btn-sm btn-ghost w-full"
                  >
                    {workflow?.assigned_to ? 'Reassign' : 'Assign'} →
                  </button>
                )}
              </div>

              {/* Priority */}
              <div className="mb-4">
                <span className="text-sm text-muted block mb-2">Priority:</span>
                <div className="flex gap-1">
                  {[1, 2, 3, 4, 5].map((p) => (
                    <button
                      key={p}
                      onClick={() => handleSetPriority(p)}
                      disabled={updating}
                      className={`px-3 py-1 text-xs font-theme-data rounded transition-colors ${
                        workflow?.priority === p
                          ? 'bg-accent text-background'
                          : 'bg-surface hover:bg-accent/20'
                      }`}
                    >
                      {PRIORITY_LABELS[p]}
                    </button>
                  ))}
                </div>
              </div>

              {/* Status Transitions */}
              <div className="mb-4">
                <span className="text-sm text-muted block mb-2">Change status:</span>
                <div className="flex flex-wrap gap-2">
                  {validTransitions.map((status) => (
                    <button
                      key={status}
                      onClick={() => handleStatusChange(status)}
                      disabled={updating}
                      className={`px-3 py-1 text-xs font-theme-data rounded transition-colors ${STATUS_COLORS[status]} hover:opacity-80`}
                    >
                      {status.toUpperCase().replace('_', ' ')}
                    </button>
                  ))}
                </div>
              </div>
            </section>

            {/* Comments */}
            <section className="border-t border-border pt-4">
              <h3 className="text-xs font-theme-data text-muted mb-3">COMMENTS</h3>

              {/* Add Comment */}
              <div className="mb-4">
                <textarea
                  value={newComment}
                  onChange={(e) => setNewComment(e.target.value)}
                  placeholder="Add a comment..."
                  className="input w-full h-20 resize-none text-sm"
                />
                <button
                  onClick={handleAddComment}
                  disabled={updating || !newComment.trim()}
                  className="btn btn-sm btn-primary mt-2"
                >
                  Add Comment
                </button>
              </div>

              {/* History */}
              <div className="space-y-3 max-h-64 overflow-y-auto">
                {workflow?.history?.length === 0 && (
                  <div className="text-sm text-muted text-center py-4">No activity yet</div>
                )}
                {workflow?.history
                  ?.slice()
                  .reverse()
                  .map((event) => (
                    <div key={event.id} className="text-sm border-l-2 border-border pl-3">
                      <div className="flex items-center gap-2 text-muted">
                        <span className="font-theme-data">{event.user_name || event.user_id}</span>
                        <span>•</span>
                        <span>{new Date(event.timestamp).toLocaleString()}</span>
                      </div>
                      {event.event_type === 'state_change' && (
                        <div>
                          Changed status from{' '}
                          <span className="font-theme-data">{event.from_state}</span> to{' '}
                          <span className="font-theme-data">{event.to_state}</span>
                        </div>
                      )}
                      {event.event_type === 'comment' && (
                        <div className="mt-1">{event.comment}</div>
                      )}
                      {event.event_type === 'assignment' && <div>Assigned to {event.user_id}</div>}
                    </div>
                  ))}
              </div>
            </section>
          </div>
        )}
      </div>
    </>
  );
}

export default FindingDetailDrawer;
