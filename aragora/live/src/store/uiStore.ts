'use client';

import { create } from 'zustand';
import { devtools, persist, subscribeWithSelector } from 'zustand/middleware';

// ============================================================================
// Types
// ============================================================================

export type ViewMode = 'default' | 'compact' | 'expanded';
export type MobileViewMode = 'transcript' | 'agents' | 'events';

export interface PanelVisibility {
  sidebar: boolean;
  agentPanel: boolean;
  eventsPanel: boolean;
  participationPanel: boolean;
  citationsPanel: boolean;
  analyticsPanel: boolean;
  historyPanel: boolean;
}

export interface PanelPosition {
  x: number;
  y: number;
  width?: number;
  height?: number;
}

export interface ToastMessage {
  id: string;
  type: 'success' | 'error' | 'warning' | 'info';
  message: string;
  duration?: number;
  timestamp: number;
}

// ============================================================================
// Store State
// ============================================================================

interface UIState {
  // Global view state
  viewMode: ViewMode;
  mobileViewMode: MobileViewMode;
  isMobile: boolean;

  // Panel visibility
  panels: PanelVisibility;

  // Panel positions (for draggable panels)
  panelPositions: Record<string, PanelPosition>;

  // Modal state
  activeModal: string | null;
  modalData: Record<string, unknown>;

  // Toast notifications
  toasts: ToastMessage[];

  // Loading states
  globalLoading: boolean;
  loadingMessage: string;

  // Keyboard shortcuts enabled
  keyboardShortcutsEnabled: boolean;

  // Focus trap active (for modals)
  focusTrapActive: boolean;
}

interface UIActions {
  // View mode
  setViewMode: (mode: ViewMode) => void;
  setMobileViewMode: (mode: MobileViewMode) => void;
  setIsMobile: (isMobile: boolean) => void;

  // Panel visibility
  togglePanel: (panel: keyof PanelVisibility) => void;
  setPanel: (panel: keyof PanelVisibility, visible: boolean) => void;
  setPanels: (panels: Partial<PanelVisibility>) => void;
  resetPanels: () => void;

  // Panel positions
  setPanelPosition: (panel: string, position: PanelPosition) => void;
  resetPanelPositions: () => void;

  // Modal
  openModal: (modal: string, data?: Record<string, unknown>) => void;
  closeModal: () => void;
  setModalData: (data: Record<string, unknown>) => void;

  // Toasts
  addToast: (toast: Omit<ToastMessage, 'id' | 'timestamp'>) => string;
  removeToast: (id: string) => void;
  clearToasts: () => void;

  // Loading
  setGlobalLoading: (loading: boolean, message?: string) => void;

  // Keyboard shortcuts
  setKeyboardShortcutsEnabled: (enabled: boolean) => void;

  // Focus trap
  setFocusTrapActive: (active: boolean) => void;

  // Reset
  resetAll: () => void;
}

type UIStore = UIState & UIActions;

// ============================================================================
// Defaults
// ============================================================================

const defaultPanels: PanelVisibility = {
  sidebar: true,
  agentPanel: true,
  eventsPanel: false,
  participationPanel: false,
  citationsPanel: false,
  analyticsPanel: false,
  historyPanel: false,
};

// ============================================================================
// Store Implementation
// ============================================================================

export const useUIStore = create<UIStore>()(
  devtools(
    persist(
      subscribeWithSelector((set, get) => ({
        // Initial state
        viewMode: 'default',
        mobileViewMode: 'transcript',
        isMobile: false,
        panels: { ...defaultPanels },
        panelPositions: {},
        activeModal: null,
        modalData: {},
        toasts: [],
        globalLoading: false,
        loadingMessage: '',
        keyboardShortcutsEnabled: true,
        focusTrapActive: false,

        // View mode
        setViewMode: (mode) => set({ viewMode: mode }, false, 'setViewMode'),

        setMobileViewMode: (mode) => set({ mobileViewMode: mode }, false, 'setMobileViewMode'),

        setIsMobile: (isMobile) => set({ isMobile }, false, 'setIsMobile'),

        // Panel visibility
        togglePanel: (panel) =>
          set(
            (state) => ({ panels: { ...state.panels, [panel]: !state.panels[panel] } }),
            false,
            'togglePanel',
          ),

        setPanel: (panel, visible) =>
          set((state) => ({ panels: { ...state.panels, [panel]: visible } }), false, 'setPanel'),

        setPanels: (panels) =>
          set((state) => ({ panels: { ...state.panels, ...panels } }), false, 'setPanels'),

        resetPanels: () => set({ panels: { ...defaultPanels } }, false, 'resetPanels'),

        // Panel positions
        setPanelPosition: (panel, position) =>
          set(
            (state) => ({ panelPositions: { ...state.panelPositions, [panel]: position } }),
            false,
            'setPanelPosition',
          ),

        resetPanelPositions: () => set({ panelPositions: {} }, false, 'resetPanelPositions'),

        // Modal
        openModal: (modal, data) =>
          set(
            { activeModal: modal, modalData: data || {}, focusTrapActive: true },
            false,
            'openModal',
          ),

        closeModal: () =>
          set({ activeModal: null, modalData: {}, focusTrapActive: false }, false, 'closeModal'),

        setModalData: (data) =>
          set((state) => ({ modalData: { ...state.modalData, ...data } }), false, 'setModalData'),

        // Toasts
        addToast: (toast) => {
          const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
          const newToast: ToastMessage = { ...toast, id, timestamp: Date.now() };

          set((state) => ({ toasts: [...state.toasts, newToast] }), false, 'addToast');

          // Auto-remove after duration
          const duration = toast.duration ?? 5000;
          if (duration > 0) {
            setTimeout(() => {
              get().removeToast(id);
            }, duration);
          }

          return id;
        },

        removeToast: (id) =>
          set(
            (state) => ({ toasts: state.toasts.filter((t) => t.id !== id) }),
            false,
            'removeToast',
          ),

        clearToasts: () => set({ toasts: [] }, false, 'clearToasts'),

        // Loading
        setGlobalLoading: (loading, message) =>
          set({ globalLoading: loading, loadingMessage: message || '' }, false, 'setGlobalLoading'),

        // Keyboard shortcuts
        setKeyboardShortcutsEnabled: (enabled) =>
          set({ keyboardShortcutsEnabled: enabled }, false, 'setKeyboardShortcutsEnabled'),

        // Focus trap
        setFocusTrapActive: (active) =>
          set({ focusTrapActive: active }, false, 'setFocusTrapActive'),

        // Reset
        resetAll: () =>
          set(
            {
              viewMode: 'default',
              mobileViewMode: 'transcript',
              isMobile: false,
              panels: { ...defaultPanels },
              panelPositions: {},
              activeModal: null,
              modalData: {},
              toasts: [],
              globalLoading: false,
              loadingMessage: '',
              keyboardShortcutsEnabled: true,
              focusTrapActive: false,
            },
            false,
            'resetAll',
          ),
      })),
      {
        name: 'aragora-ui',
        partialize: (state) => ({
          // Only persist user preferences
          viewMode: state.viewMode,
          panels: state.panels,
          panelPositions: state.panelPositions,
          keyboardShortcutsEnabled: state.keyboardShortcutsEnabled,
        }),
      },
    ),
    { name: 'ui-store' },
  ),
);

// ============================================================================
// Selectors
// ============================================================================

export const selectViewMode = (state: UIStore) => state.viewMode;
export const selectMobileViewMode = (state: UIStore) => state.mobileViewMode;
export const selectIsMobile = (state: UIStore) => state.isMobile;
export const selectPanels = (state: UIStore) => state.panels;
export const selectPanelPositions = (state: UIStore) => state.panelPositions;
export const selectActiveModal = (state: UIStore) => state.activeModal;
export const selectModalData = (state: UIStore) => state.modalData;
export const selectToasts = (state: UIStore) => state.toasts;
export const selectGlobalLoading = (state: UIStore) => ({
  loading: state.globalLoading,
  message: state.loadingMessage,
});
export const selectKeyboardShortcutsEnabled = (state: UIStore) => state.keyboardShortcutsEnabled;
