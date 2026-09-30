/**
 * Connector Dashboard Components
 *
 * Enterprise data source connector management UI.
 * Supports configuration, monitoring, and sync management
 * for GitHub, S3, SharePoint, Confluence, Notion, Slack, and more.
 */

export {
  ConnectorDashboard,
  type ConnectorDashboardProps,
  type ConnectorFilter,
  type DashboardTab,
} from './ConnectorDashboard';

export {
  ConnectorCard,
  type ConnectorCardProps,
  type ConnectorInfo,
  type ConnectorType,
  type ConnectorStatus,
} from './ConnectorCard';

export {
  ConnectorConfigModal,
  type ConnectorConfigModalProps,
  type ConnectorConfigField,
} from './ConnectorConfigModal';

export {
  SyncStatusWidget,
  type SyncStatusWidgetProps,
  type SyncHistoryItem,
} from './SyncStatusWidget';

export {
  ConnectorHealthGrid,
  type ConnectorHealthGridProps,
  type ConnectorHealthData,
  connectorToHealthData,
} from './ConnectorHealthGrid';

export { SyncTimeline, type SyncTimelineProps } from './SyncTimeline';
