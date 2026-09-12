'use client';

import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useMemo,
  ReactNode,
  useEffect,
} from 'react';

// Breakpoints matching Tailwind config
const BREAKPOINTS = {
  mobile: 640, // sm
  tablet: 1024, // lg
  desktop: 1280, // xl
};

interface LayoutContextType {
  // Left sidebar state
  leftSidebarOpen: boolean;
  leftSidebarCollapsed: boolean;
  openLeftSidebar: () => void;
  closeLeftSidebar: () => void;
  toggleLeftSidebar: () => void;
  setLeftSidebarCollapsed: (collapsed: boolean) => void;

  // Right sidebar state
  rightSidebarOpen: boolean;
  openRightSidebar: () => void;
  closeRightSidebar: () => void;
  toggleRightSidebar: () => void;

  // Responsive state
  isMobile: boolean;
  isTablet: boolean;
  isDesktop: boolean;

  // Layout dimensions
  leftSidebarWidth: number;
  rightSidebarWidth: number;
}

const LayoutContext = createContext<LayoutContextType | undefined>(undefined);

// Local storage keys
const LEFT_COLLAPSED_KEY = 'aragora-left-sidebar-collapsed';
const RIGHT_OPEN_KEY = 'aragora-right-sidebar-open';

export function LayoutProvider({ children }: { children: ReactNode }) {
  // Responsive state
  const [isMobile, setIsMobile] = useState(false);
  const [isTablet, setIsTablet] = useState(false);
  const [isDesktop, setIsDesktop] = useState(true);

  // Left sidebar: open on desktop, hidden (drawer) on mobile
  const [leftSidebarOpen, setLeftSidebarOpen] = useState(false);
  const [leftSidebarCollapsed, setLeftSidebarCollapsedState] = useState(false);

  // Right sidebar: open on wide screens
  const [rightSidebarOpen, setRightSidebarOpen] = useState(false);

  // Calculate sidebar widths based on state
  const leftSidebarWidth = leftSidebarCollapsed ? 64 : 256;
  const rightSidebarWidth = 280;

  // Initialize from localStorage and window size
  useEffect(() => {
    // Check window size
    const checkWindowSize = () => {
      const width = window.innerWidth;
      const mobile = width < BREAKPOINTS.mobile;
      const tablet = width >= BREAKPOINTS.mobile && width < BREAKPOINTS.tablet;
      const desktop = width >= BREAKPOINTS.tablet;

      setIsMobile(mobile);
      setIsTablet(tablet);
      setIsDesktop(desktop);

      // Auto-manage sidebar visibility based on breakpoints
      if (mobile) {
        setLeftSidebarOpen(false);
        setRightSidebarOpen(false);
      } else if (tablet) {
        setLeftSidebarOpen(true);
        setLeftSidebarCollapsedState(true); // Collapsed on tablet
        setRightSidebarOpen(false);
      } else {
        setLeftSidebarOpen(true);
        // Restore collapsed state from localStorage on desktop
        const savedCollapsed = localStorage.getItem(LEFT_COLLAPSED_KEY);
        setLeftSidebarCollapsedState(savedCollapsed === 'true');
        // Restore right sidebar state
        const savedRightOpen = localStorage.getItem(RIGHT_OPEN_KEY);
        setRightSidebarOpen(savedRightOpen !== 'false'); // Default to open on desktop
      }
    };

    // Initial check
    checkWindowSize();

    // Listen for resize
    window.addEventListener('resize', checkWindowSize);
    return () => window.removeEventListener('resize', checkWindowSize);
  }, []);

  // Left sidebar actions
  const openLeftSidebar = useCallback(() => setLeftSidebarOpen(true), []);
  const closeLeftSidebar = useCallback(() => setLeftSidebarOpen(false), []);
  const toggleLeftSidebar = useCallback(() => setLeftSidebarOpen((prev) => !prev), []);

  const setLeftSidebarCollapsed = useCallback((collapsed: boolean) => {
    setLeftSidebarCollapsedState(collapsed);
    localStorage.setItem(LEFT_COLLAPSED_KEY, String(collapsed));
  }, []);

  // Right sidebar actions
  const openRightSidebar = useCallback(() => {
    setRightSidebarOpen(true);
    localStorage.setItem(RIGHT_OPEN_KEY, 'true');
  }, []);

  const closeRightSidebar = useCallback(() => {
    setRightSidebarOpen(false);
    localStorage.setItem(RIGHT_OPEN_KEY, 'false');
  }, []);

  const toggleRightSidebar = useCallback(() => {
    setRightSidebarOpen((prev) => {
      const newValue = !prev;
      localStorage.setItem(RIGHT_OPEN_KEY, String(newValue));
      return newValue;
    });
  }, []);

  // Close left sidebar on escape (mobile only)
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isMobile && leftSidebarOpen) {
        closeLeftSidebar();
      }
    };

    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isMobile, leftSidebarOpen, closeLeftSidebar]);

  // Prevent body scroll when mobile sidebar is open
  useEffect(() => {
    if (isMobile && leftSidebarOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [isMobile, leftSidebarOpen]);

  const value = useMemo<LayoutContextType>(
    () => ({
      // Left sidebar
      leftSidebarOpen,
      leftSidebarCollapsed,
      openLeftSidebar,
      closeLeftSidebar,
      toggleLeftSidebar,
      setLeftSidebarCollapsed,
      // Right sidebar
      rightSidebarOpen,
      openRightSidebar,
      closeRightSidebar,
      toggleRightSidebar,
      // Responsive
      isMobile,
      isTablet,
      isDesktop,
      // Dimensions
      leftSidebarWidth,
      rightSidebarWidth,
    }),
    [
      leftSidebarOpen,
      leftSidebarCollapsed,
      openLeftSidebar,
      closeLeftSidebar,
      toggleLeftSidebar,
      setLeftSidebarCollapsed,
      rightSidebarOpen,
      openRightSidebar,
      closeRightSidebar,
      toggleRightSidebar,
      isMobile,
      isTablet,
      isDesktop,
      leftSidebarWidth,
      rightSidebarWidth,
    ],
  );

  return <LayoutContext.Provider value={value}>{children}</LayoutContext.Provider>;
}

export function useLayout() {
  const context = useContext(LayoutContext);
  if (context === undefined) {
    throw new Error('useLayout must be used within a LayoutProvider');
  }
  return context;
}
