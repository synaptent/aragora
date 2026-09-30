/**
 * Mobile-First Accessibility Components.
 *
 * This module provides touch-optimized, accessible components for mobile users:
 *
 * - TouchButton: Accessible touch button with haptic feedback and ripple effect
 * - TouchIconButton: Icon-only variant with proper ARIA labels
 * - BottomNavigation: Fixed bottom tab navigation with safe area support
 * - PullToRefresh: Native-feel pull-to-refresh with rubber-band effect
 * - MobileMenu: Slide-in navigation with focus trap and edge swipes
 * - SkipLinks: Keyboard navigation skip links
 * - MainContent: Landmark wrapper for main content
 *
 * Usage:
 * ```tsx
 * import {
 *   TouchButton,
 *   BottomNavigation,
 *   MobileMenuProvider,
 *   MobileMenu,
 *   HamburgerButton,
 *   SkipLinks,
 *   MainContent,
 * } from '@/components/mobile';
 *
 * function App() {
 *   return (
 *     <MobileMenuProvider>
 *       <SkipLinks />
 *       <header>
 *         <HamburgerButton />
 *       </header>
 *       <MobileMenu items={menuItems} />
 *       <MainContent>
 *         <TouchButton onClick={handleClick}>
 *           Click me
 *         </TouchButton>
 *       </MainContent>
 *       <BottomNavigation items={navItems} activeId={currentTab} onSelect={setCurrentTab} />
 *     </MobileMenuProvider>
 *   );
 * }
 * ```
 */

// Touch-optimized buttons
export { TouchButton, TouchIconButton } from './TouchButton';

// Bottom navigation
export { BottomNavigation, BottomNavigationSpacer, type NavItem } from './BottomNavigation';

// Pull-to-refresh
export { PullToRefresh } from './PullToRefresh';

// Mobile menu
export {
  MobileMenu,
  MobileMenuProvider,
  HamburgerButton,
  useMobileMenu,
  type MenuItem,
} from './MobileMenu';

// Skip links
export { SkipLinks, MainContent, LANDMARK_IDS, type SkipLinkItem } from './SkipLinks';
