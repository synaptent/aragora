import type { ReviewResult, ReviewComment, Severity } from '../types';
import { getAgentColor } from '../types';

interface ReviewViewProps {
  review: ReviewResult | undefined;
  onApplyFix: (reviewId: string, commentId: string) => void;
  onApplyAllFixes: (reviewId: string) => void;
  onDismissComment: (reviewId: string, commentId: string) => void;
  onNavigateToComment: (reviewId: string, commentId: string) => void;
}

export function ReviewView({
  review,
  onApplyFix,
  onApplyAllFixes,
  onDismissComment,
  onNavigateToComment,
}: ReviewViewProps) {
  if (!review) {
    return (
      <div className="empty-state">
        <div className="empty-icon">🔍</div>
        <h2>No Active Review</h2>
        <p>Select code and run "Aragora: Review Selection" to see results here.</p>
      </div>
    );
  }

  const unresolvedComments = review.comments.filter((c) => !c.isResolved);
  const fixableComments = unresolvedComments.filter((c) => c.suggestedFix);

  const commentsByCategory = review.comments.reduce<Record<string, ReviewComment[]>>(
    (acc, comment) => {
      if (!acc[comment.category]) {
        acc[comment.category] = [];
      }
      acc[comment.category].push(comment);
      return acc;
    },
    {},
  );

  return (
    <div className="review-view">
      {/* Header */}
      <div className="review-header">
        <div className="review-title">
          <h1>Code Review</h1>
          <span className="file-name">{review.file.split('/').pop()}</span>
        </div>
        <div className="review-status">
          <span className={`status-badge ${review.status}`}>
            {review.status === 'in_progress' ? 'Reviewing...' : review.status}
          </span>
          {review.overallScore !== undefined && <ScoreIndicator score={review.overallScore} />}
        </div>
      </div>

      {/* Summary */}
      {review.summary && (
        <div className="review-summary">
          <p>{review.summary}</p>
        </div>
      )}

      {/* Quick Actions */}
      {fixableComments.length > 0 && review.status === 'completed' && (
        <div className="quick-actions">
          <button className="primary-button" onClick={() => onApplyAllFixes(review.id)}>
            ✓ Apply All Fixes ({fixableComments.length})
          </button>
        </div>
      )}

      {/* Comments List */}
      <div className="comments-list">
        {Object.entries(commentsByCategory).map(([category, comments]) => (
          <div key={category} className="comment-category">
            <h3 className="category-header">
              {getCategoryIcon(category)} {formatCategory(category)}
              <span className="count">{comments.length}</span>
            </h3>
            {comments.map((comment) => (
              <CommentCard
                key={comment.id}
                comment={comment}
                reviewId={review.id}
                onApplyFix={onApplyFix}
                onDismiss={onDismissComment}
                onNavigate={onNavigateToComment}
              />
            ))}
          </div>
        ))}
      </div>

      {/* Agents */}
      <div className="review-agents">
        <h3>Reviewed by</h3>
        <div className="agents-list">
          {review.agents.map((agent) => (
            <div
              key={agent.id}
              className="agent-chip"
              style={{ backgroundColor: getAgentColor(agent.name) }}
            >
              {agent.name}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

interface CommentCardProps {
  comment: ReviewComment;
  reviewId: string;
  onApplyFix: (reviewId: string, commentId: string) => void;
  onDismiss: (reviewId: string, commentId: string) => void;
  onNavigate: (reviewId: string, commentId: string) => void;
}

function CommentCard({ comment, reviewId, onApplyFix, onDismiss, onNavigate }: CommentCardProps) {
  const severityColor = getSeverityColor(comment.severity);

  return (
    <div className={`comment-card ${comment.isResolved ? 'resolved' : ''}`}>
      <div className="comment-header">
        <div className="comment-location" onClick={() => onNavigate(reviewId, comment.id)}>
          <span className="severity-dot" style={{ backgroundColor: severityColor }}></span>
          <span className="line-number">Line {comment.location.line}</span>
        </div>
        <div className="comment-agent" style={{ color: getAgentColor(comment.agent.name) }}>
          {comment.agent.name}
        </div>
      </div>

      <div className="comment-content">{comment.content}</div>

      {comment.suggestedFix && (
        <div className="suggested-fix">
          <div className="fix-header">Suggested fix:</div>
          <div className="fix-diff">
            <div className="diff-old">- {comment.suggestedFix.oldCode}</div>
            <div className="diff-new">+ {comment.suggestedFix.newCode}</div>
          </div>
        </div>
      )}

      <div className="comment-actions">
        {comment.suggestedFix && !comment.isResolved && (
          <button className="apply-button" onClick={() => onApplyFix(reviewId, comment.id)}>
            Apply Fix
          </button>
        )}
        {!comment.isResolved && (
          <button className="dismiss-button" onClick={() => onDismiss(reviewId, comment.id)}>
            Dismiss
          </button>
        )}
        <button className="navigate-button" onClick={() => onNavigate(reviewId, comment.id)}>
          Go to Code
        </button>
      </div>

      {comment.isResolved && <div className="resolved-badge">✓ Resolved</div>}
    </div>
  );
}

function ScoreIndicator({ score }: { score: number }) {
  const getScoreColor = (s: number) => {
    if (s >= 80) return '#4caf50';
    if (s >= 60) return '#ff9800';
    return '#f44336';
  };

  return (
    <div className="score-indicator" style={{ borderColor: getScoreColor(score) }}>
      <span className="score-value" style={{ color: getScoreColor(score) }}>
        {score}
      </span>
      <span className="score-label">/100</span>
    </div>
  );
}

function getSeverityColor(severity: Severity): string {
  const colors: Record<Severity, string> = {
    critical: '#f44336',
    high: '#ff9800',
    medium: '#ffeb3b',
    low: '#2196f3',
    info: '#9e9e9e',
  };
  return colors[severity];
}

function getCategoryIcon(category: string): string {
  const icons: Record<string, string> = {
    bug: '🐛',
    security: '🔒',
    performance: '⚡',
    style: '✨',
    suggestion: '💡',
    praise: '👏',
  };
  return icons[category] || '📝';
}

function formatCategory(category: string): string {
  return category.charAt(0).toUpperCase() + category.slice(1);
}
