/**
 * Types for the Routing Rules Builder
 */

export type ConditionOperator =
  | 'eq'
  | 'neq'
  | 'gt'
  | 'gte'
  | 'lt'
  | 'lte'
  | 'contains'
  | 'not_contains'
  | 'starts_with'
  | 'ends_with'
  | 'matches'
  | 'in'
  | 'not_in'
  | 'exists'
  | 'not_exists';

export type ActionType =
  | 'route_to_channel'
  | 'escalate_to'
  | 'notify'
  | 'tag'
  | 'set_priority'
  | 'delay'
  | 'block'
  | 'require_approval'
  | 'webhook'
  | 'log';

export interface Condition {
  field: string;
  operator: ConditionOperator;
  value: unknown;
  case_sensitive?: boolean;
}

export interface Action {
  type: ActionType;
  target?: string;
  params?: Record<string, unknown>;
}

export interface RoutingRule {
  id: string;
  name: string;
  description?: string;
  conditions: Condition[];
  actions: Action[];
  priority: number;
  enabled: boolean;
  created_at?: string;
  updated_at?: string;
  created_by?: string;
  match_mode: 'all' | 'any';
  stop_processing?: boolean;
  tags?: string[];
}

export interface RuleEvaluationResult {
  rule_id: string;
  rule_name: string;
  matched: boolean;
  actions: Action[];
  execution_time_ms: number;
}

export interface EvaluateResponse {
  status: string;
  context: Record<string, unknown>;
  results: RuleEvaluationResult[];
  matching_actions: Action[];
  rules_evaluated: number;
  rules_matched: number;
}

// Available fields for conditions
export const CONDITION_FIELDS = [
  { value: 'confidence', label: 'Confidence Score', type: 'number' },
  { value: 'topic', label: 'Topic', type: 'string' },
  { value: 'status', label: 'Status', type: 'string' },
  { value: 'agent_count', label: 'Agent Count', type: 'number' },
  { value: 'round_count', label: 'Round Count', type: 'number' },
  { value: 'dissent_ratio', label: 'Dissent Ratio', type: 'number' },
  { value: 'priority', label: 'Priority', type: 'string' },
  { value: 'vertical', label: 'Vertical', type: 'string' },
  { value: 'consensus.conclusion', label: 'Conclusion', type: 'string' },
  { value: 'consensus.confidence', label: 'Consensus Confidence', type: 'number' },
  { value: 'metadata.source', label: 'Source', type: 'string' },
  { value: 'metadata.department', label: 'Department', type: 'string' },
] as const;

// Operators grouped by type
export const OPERATORS_BY_TYPE: Record<string, { value: ConditionOperator; label: string }[]> = {
  number: [
    { value: 'eq', label: 'equals' },
    { value: 'neq', label: 'not equals' },
    { value: 'gt', label: 'greater than' },
    { value: 'gte', label: 'greater than or equal' },
    { value: 'lt', label: 'less than' },
    { value: 'lte', label: 'less than or equal' },
    { value: 'exists', label: 'exists' },
    { value: 'not_exists', label: 'does not exist' },
  ],
  string: [
    { value: 'eq', label: 'equals' },
    { value: 'neq', label: 'not equals' },
    { value: 'contains', label: 'contains' },
    { value: 'not_contains', label: 'does not contain' },
    { value: 'starts_with', label: 'starts with' },
    { value: 'ends_with', label: 'ends with' },
    { value: 'matches', label: 'matches regex' },
    { value: 'in', label: 'is one of' },
    { value: 'not_in', label: 'is not one of' },
    { value: 'exists', label: 'exists' },
    { value: 'not_exists', label: 'does not exist' },
  ],
};

// Action configurations
export const ACTION_CONFIGS: Record<
  ActionType,
  {
    label: string;
    icon: string;
    description: string;
    requiresTarget: boolean;
    targetLabel?: string;
    targetPlaceholder?: string;
    paramFields?: {
      key: string;
      label: string;
      type: 'text' | 'number' | 'select';
      options?: { value: string; label: string }[];
    }[];
  }
> = {
  route_to_channel: {
    label: 'Route to Channel',
    icon: '📢',
    description: 'Send the decision to a specific channel',
    requiresTarget: true,
    targetLabel: 'Channel',
    targetPlaceholder: 'e.g., slack, teams, #security',
  },
  escalate_to: {
    label: 'Escalate To',
    icon: '⬆️',
    description: 'Escalate decision for review',
    requiresTarget: true,
    targetLabel: 'Person/Team',
    targetPlaceholder: 'e.g., team-lead, security-team',
  },
  notify: {
    label: 'Send Notification',
    icon: '🔔',
    description: 'Send a notification',
    requiresTarget: true,
    targetLabel: 'Recipient',
    targetPlaceholder: 'e.g., admin, all, user@example.com',
    paramFields: [{ key: 'message', label: 'Message', type: 'text' }],
  },
  tag: {
    label: 'Add Tag',
    icon: '🏷️',
    description: 'Tag the decision for categorization',
    requiresTarget: true,
    targetLabel: 'Tag',
    targetPlaceholder: 'e.g., security, urgent, review',
  },
  set_priority: {
    label: 'Set Priority',
    icon: '🎯',
    description: 'Change the decision priority',
    requiresTarget: true,
    targetLabel: 'Priority',
    targetPlaceholder: 'e.g., urgent, high, normal, low',
  },
  delay: {
    label: 'Delay Delivery',
    icon: '⏰',
    description: 'Delay before delivery',
    requiresTarget: false,
    paramFields: [{ key: 'seconds', label: 'Delay (seconds)', type: 'number' }],
  },
  block: {
    label: 'Block Delivery',
    icon: '🚫',
    description: 'Prevent decision delivery',
    requiresTarget: false,
    paramFields: [{ key: 'reason', label: 'Reason', type: 'text' }],
  },
  require_approval: {
    label: 'Require Approval',
    icon: '✋',
    description: 'Require human approval before delivery',
    requiresTarget: true,
    targetLabel: 'Approver',
    targetPlaceholder: 'e.g., default, manager, admin',
  },
  webhook: {
    label: 'Call Webhook',
    icon: '🔗',
    description: 'Send to a webhook URL',
    requiresTarget: true,
    targetLabel: 'Webhook URL',
    targetPlaceholder: 'https://api.example.com/webhook',
  },
  log: {
    label: 'Log Event',
    icon: '📝',
    description: 'Log for auditing',
    requiresTarget: false,
    paramFields: [
      {
        key: 'level',
        label: 'Log Level',
        type: 'select',
        options: [
          { value: 'info', label: 'Info' },
          { value: 'warning', label: 'Warning' },
          { value: 'error', label: 'Error' },
        ],
      },
      { key: 'message', label: 'Message', type: 'text' },
    ],
  },
};
