'use client';

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useMemo,
  useEffect,
  type ReactNode,
} from 'react';
import type { WebSocketConnectionStatus } from '@/hooks/useWebSocketBase';

/**
 * Context for unified connection status across all WebSocket services.
 *
 * Aggregates connection state from multiple WebSocket streams (debate, control plane,
 * workflow, etc.) into a single status that UI components can display.
 *
 * @example
 * ```tsx
 * // In status bar component
 * const { overallStatus, services } = useConnection();
 *
 * if (overallStatus === 'error') {
 *   return <StatusIndicator color="red" label="Disconnected" />;
 * }
 * ```
 */

export type ServiceName = 'debate' | 'controlPlane' | 'workflow' | 'connector' | 'custom';

export interface ServiceConnection {
  name: ServiceName;
  displayName: string;
  status: WebSocketConnectionStatus;
  error: string | null;
  reconnectAttempt: number;
  lastConnected: Date | null;
}

export type OverallConnectionStatus =
  | 'connected' // All enabled services connected
  | 'partial' // Some services connected
  | 'connecting' // At least one service connecting
  | 'disconnected' // All services disconnected
  | 'error'; // At least one service has error

export interface ConnectionContextValue {
  /** Overall connection status across all services */
  overallStatus: OverallConnectionStatus;
  /** Individual service connection states */
  services: Map<ServiceName, ServiceConnection>;
  /** Number of connected services */
  connectedCount: number;
  /** Total number of registered services */
  totalServices: number;
  /** Whether any service is reconnecting */
  isReconnecting: boolean;
  /** Last time all services were connected */
  lastAllConnected: Date | null;
  /** Register a service connection */
  registerService: (service: ServiceConnection) => void;
  /** Update a service's connection status */
  updateServiceStatus: (
    name: ServiceName,
    update: Partial<Omit<ServiceConnection, 'name'>>,
  ) => void;
  /** Unregister a service */
  unregisterService: (name: ServiceName) => void;
  /** Trigger reconnection for a specific service */
  requestReconnect: (name: ServiceName) => void;
  /** Trigger reconnection for all disconnected services */
  reconnectAll: () => void;
  /** Callbacks for reconnection requests */
  onReconnectRequest: (name: ServiceName, callback: () => void) => () => void;
}

const ConnectionContext = createContext<ConnectionContextValue | null>(null);

export interface ConnectionProviderProps {
  children: ReactNode;
}

export function ConnectionProvider({ children }: ConnectionProviderProps) {
  const [services, setServices] = useState<Map<ServiceName, ServiceConnection>>(new Map());
  const [reconnectCallbacks, setReconnectCallbacks] = useState<Map<ServiceName, Set<() => void>>>(
    new Map(),
  );
  const [lastAllConnected, setLastAllConnected] = useState<Date | null>(null);

  const registerService = useCallback((service: ServiceConnection) => {
    setServices((prev) => {
      const next = new Map(prev);
      next.set(service.name, service);
      return next;
    });
  }, []);

  const updateServiceStatus = useCallback(
    (name: ServiceName, update: Partial<Omit<ServiceConnection, 'name'>>) => {
      setServices((prev) => {
        const existing = prev.get(name);
        if (!existing) return prev;

        const next = new Map(prev);
        next.set(name, {
          ...existing,
          ...update,
          lastConnected: update.status === 'connected' ? new Date() : existing.lastConnected,
        });
        return next;
      });
    },
    [],
  );

  const unregisterService = useCallback((name: ServiceName) => {
    setServices((prev) => {
      const next = new Map(prev);
      next.delete(name);
      return next;
    });
    setReconnectCallbacks((prev) => {
      const next = new Map(prev);
      next.delete(name);
      return next;
    });
  }, []);

  const requestReconnect = useCallback(
    (name: ServiceName) => {
      const callbacks = reconnectCallbacks.get(name);
      if (callbacks) {
        callbacks.forEach((cb) => cb());
      }
    },
    [reconnectCallbacks],
  );

  const reconnectAll = useCallback(() => {
    // Reconnect all services that are not connected
    services.forEach((service) => {
      if (service.status !== 'connected' && service.status !== 'streaming') {
        const callbacks = reconnectCallbacks.get(service.name);
        if (callbacks) {
          callbacks.forEach((cb) => cb());
        }
      }
    });
  }, [services, reconnectCallbacks]);

  const onReconnectRequest = useCallback(
    (name: ServiceName, callback: () => void): (() => void) => {
      setReconnectCallbacks((prev) => {
        const next = new Map(prev);
        const existing = next.get(name) || new Set();
        existing.add(callback);
        next.set(name, existing);
        return next;
      });

      // Return unsubscribe function
      return () => {
        setReconnectCallbacks((prev) => {
          const next = new Map(prev);
          const existing = next.get(name);
          if (existing) {
            existing.delete(callback);
            if (existing.size === 0) {
              next.delete(name);
            } else {
              next.set(name, existing);
            }
          }
          return next;
        });
      };
    },
    [],
  );

  // Calculate derived state
  const { overallStatus, connectedCount, totalServices, isReconnecting } = useMemo(() => {
    const serviceArray = Array.from(services.values());
    const total = serviceArray.length;

    if (total === 0) {
      return {
        overallStatus: 'disconnected' as OverallConnectionStatus,
        connectedCount: 0,
        totalServices: 0,
        isReconnecting: false,
      };
    }

    const connected = serviceArray.filter(
      (s) => s.status === 'connected' || s.status === 'streaming',
    ).length;
    const hasError = serviceArray.some((s) => s.status === 'error');
    const hasConnecting = serviceArray.some((s) => s.status === 'connecting');
    const isReconnecting = serviceArray.some((s) => s.reconnectAttempt > 0);

    let overallStatus: OverallConnectionStatus;
    if (hasError) {
      overallStatus = 'error';
    } else if (connected === total) {
      overallStatus = 'connected';
    } else if (connected > 0) {
      overallStatus = 'partial';
    } else if (hasConnecting) {
      overallStatus = 'connecting';
    } else {
      overallStatus = 'disconnected';
    }

    return { overallStatus, connectedCount: connected, totalServices: total, isReconnecting };
  }, [services]);

  // Track when all services become connected (moved from useMemo to avoid render-phase side effect)
  useEffect(() => {
    if (overallStatus === 'connected' && totalServices > 0) {
      setLastAllConnected(new Date());
    }
  }, [overallStatus, totalServices]);

  const value = useMemo<ConnectionContextValue>(
    () => ({
      overallStatus,
      services,
      connectedCount,
      totalServices,
      isReconnecting,
      lastAllConnected,
      registerService,
      updateServiceStatus,
      unregisterService,
      requestReconnect,
      reconnectAll,
      onReconnectRequest,
    }),
    [
      overallStatus,
      services,
      connectedCount,
      totalServices,
      isReconnecting,
      lastAllConnected,
      registerService,
      updateServiceStatus,
      unregisterService,
      requestReconnect,
      reconnectAll,
      onReconnectRequest,
    ],
  );

  return <ConnectionContext.Provider value={value}>{children}</ConnectionContext.Provider>;
}

export function useConnection(): ConnectionContextValue {
  const context = useContext(ConnectionContext);
  if (!context) {
    throw new Error('useConnection must be used within a ConnectionProvider');
  }
  return context;
}

/**
 * Hook to register a WebSocket service with the connection context.
 * Automatically registers on mount and updates status on change.
 *
 * @example
 * ```tsx
 * useServiceConnection({
 *   name: 'debate',
 *   displayName: 'Debate Stream',
 *   status,
 *   error,
 *   reconnectAttempt,
 * });
 * ```
 */
export function useServiceConnection(service: ServiceConnection): void {
  const context = useContext(ConnectionContext);

  // Register/update via useEffect to avoid state updates during render.
  // Compare by individual properties to prevent loops from new object refs.
  useEffect(() => {
    if (context) {
      context.registerService(service);
    }
    // Intentionally decomposed: service object is unstable (new ref each render),
    // so we depend on individual properties to prevent infinite re-registration.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [context, service.name, service.status, service.error, service.reconnectAttempt]);
}

/**
 * Optional hook that doesn't throw if outside provider.
 */
export function useOptionalConnection(): ConnectionContextValue | null {
  return useContext(ConnectionContext);
}

export default ConnectionContext;
