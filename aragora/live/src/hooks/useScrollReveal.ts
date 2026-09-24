'use client';

import { useEffect, useRef } from 'react';

/**
 * Lightweight scroll-triggered reveal using IntersectionObserver.
 * Adds 'is-visible' class when element enters viewport.
 * Pair with .animate-on-scroll CSS class.
 */
export function useScrollReveal<T extends HTMLElement>(options?: {
  threshold?: number;
  rootMargin?: string;
}) {
  const ref = useRef<T>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    // Respect reduced motion preference
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      el.classList.add('is-visible');
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          el.classList.add('is-visible');
          observer.unobserve(el);
        }
      },
      {
        threshold: options?.threshold ?? 0.15,
        rootMargin: options?.rootMargin ?? '0px 0px -40px 0px',
      },
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [options?.threshold, options?.rootMargin]);

  return ref;
}
