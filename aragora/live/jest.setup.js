import '@testing-library/jest-dom';

process.env.NEXT_PUBLIC_API_URL = 'http://localhost:8080';
process.env.NEXT_PUBLIC_WS_URL = 'ws://localhost:8765/ws';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
global.IS_REACT_ACT_ENVIRONMENT = true;
if (typeof window !== 'undefined') {
  window.IS_REACT_ACT_ENVIRONMENT = true;
}

jest.mock('next/navigation');
jest.mock('react-markdown', () => {
  const React = require('react');
  return {
    __esModule: true,
    default: ({ children }) => React.createElement(React.Fragment, null, children),
  };
});

// Mock fetch globally
global.fetch = jest.fn();

// Mock window.matchMedia for components that use it (e.g., ThemeToggle)
if (typeof window !== 'undefined') {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: jest.fn().mockImplementation((query) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: jest.fn(), // deprecated
      removeListener: jest.fn(), // deprecated
      addEventListener: jest.fn(),
      removeEventListener: jest.fn(),
      dispatchEvent: jest.fn(),
    })),
  });
}

// Mock ResizeObserver for components that use it
global.ResizeObserver = jest
  .fn()
  .mockImplementation(() => ({ observe: jest.fn(), unobserve: jest.fn(), disconnect: jest.fn() }));

// Mock IntersectionObserver for lazy loading components
global.IntersectionObserver = jest
  .fn()
  .mockImplementation(() => ({ observe: jest.fn(), unobserve: jest.fn(), disconnect: jest.fn() }));

// Mock scrollTo for components that use window scrolling
if (typeof window !== 'undefined') {
  window.scrollTo = jest.fn();
}

// Reset mocks between tests
beforeEach(() => {
  jest.clearAllMocks();
});
