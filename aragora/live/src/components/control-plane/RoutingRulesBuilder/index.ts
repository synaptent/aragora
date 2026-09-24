/**
 * Routing Rules Builder
 *
 * Visual IF/THEN builder for decision routing rules.
 * Allows creating, editing, and testing rules that control
 * how debate decisions are routed to various channels.
 */

export {
  RoutingRulesBuilder,
  type RoutingRulesBuilderProps,
  type RulesTab,
} from './RoutingRulesBuilder';

export {
  ConditionBuilder,
  ConditionListBuilder,
  type ConditionBuilderProps,
  type ConditionListBuilderProps,
} from './ConditionBuilder';

export {
  ActionBuilder,
  ActionListBuilder,
  type ActionBuilderProps,
  type ActionListBuilderProps,
} from './ActionBuilder';

export type {
  RoutingRule,
  Condition,
  ConditionOperator,
  Action,
  ActionType,
  RuleEvaluationResult,
  EvaluateResponse,
} from './types';

export { CONDITION_FIELDS, OPERATORS_BY_TYPE, ACTION_CONFIGS } from './types';
