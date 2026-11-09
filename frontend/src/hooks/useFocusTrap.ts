/**
 * Reusable focus trap hook for accessible modal dialogs and overlays (WCAG 2.1 AA).
 * Handles focus trapping (Tab / Shift-Tab), Escape key dismissal, scroll locking,
 * initial auto-focus and restoration of focus on unmount.
 */

import { useEffect, useRef, useCallback } from 'react';

export const FOCUSABLE_ELEMENTS_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

export function getFocusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_ELEMENTS_SELECTOR))
    .filter((el) => !el.hasAttribute('hidden') && el.getAttribute('aria-hidden') !== 'true');
}

export interface UseFocusTrapOptions {
  isOpen: boolean;
  onClose?: () => void;
  autoFocus?: boolean;
  returnFocus?: boolean;
  lockScroll?: boolean;
  initialFocusRef?: React.RefObject<HTMLElement | null>;
}

export function useFocusTrap<T extends HTMLElement = HTMLDivElement>({
  isOpen,
  onClose,
  autoFocus = true,
  returnFocus = true,
  lockScroll = true,
  initialFocusRef,
}: UseFocusTrapOptions) {
  const containerRef = useRef<T | null>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!isOpen) return;

    if (returnFocus && document.activeElement instanceof HTMLElement) {
      previouslyFocusedRef.current = document.activeElement;
    }

    const prevOverflow = document.body.style.overflow;
    if (lockScroll) {
      document.body.style.overflow = 'hidden';
    }

    if (autoFocus) {
      const timer = requestAnimationFrame(() => {
        if (!containerRef.current) return;
        if (initialFocusRef?.current) {
          initialFocusRef.current.focus();
        } else {
          const focusable = getFocusableElements(containerRef.current);
          if (focusable.length > 0) {
            focusable[0].focus();
          } else {
            containerRef.current.focus();
          }
        }
      });
      return () => {
        cancelAnimationFrame(timer);
        if (lockScroll) {
          document.body.style.overflow = prevOverflow;
        }
        if (returnFocus && previouslyFocusedRef.current?.isConnected) {
          previouslyFocusedRef.current.focus();
        }
      };
    }

    return () => {
      if (lockScroll) {
        document.body.style.overflow = prevOverflow;
      }
      if (returnFocus && previouslyFocusedRef.current?.isConnected) {
        previouslyFocusedRef.current.focus();
      }
    };
  }, [isOpen, autoFocus, returnFocus, lockScroll, initialFocusRef]);

  // Global window keydown listener to catch Tab and Escape
  useEffect(() => {
    if (!isOpen) return;

    const onKeyDown = (e: KeyboardEvent) => {
      if (!containerRef.current) return;

      if (e.key === 'Escape') {
        // Ein offenes Menü im Dialog (z. B. die Slicer-Auswahl) bekommt Escape zuerst und schließt sich selbst
        if (containerRef.current.querySelector('[role="menu"]')) return;
        if (onClose) {
          e.preventDefault();
          e.stopPropagation();
          onClose();
        }
        return;
      }

      if (e.key === 'Tab') {
        const focusable = getFocusableElements(containerRef.current);
        if (focusable.length === 0) {
          e.preventDefault();
          containerRef.current.focus();
          return;
        }

        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        const active = document.activeElement;

        if (e.shiftKey) {
          if (active === first || !containerRef.current.contains(active)) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (active === last || !containerRef.current.contains(active)) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    };

    window.addEventListener('keydown', onKeyDown, true);
    return () => window.removeEventListener('keydown', onKeyDown, true);
  }, [isOpen, onClose]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      // In-component handler fallback
      if (e.key === 'Escape' && onClose) {
        if (containerRef.current?.querySelector('[role="menu"]')) return; // siehe oben: erst das Menü
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }
    },
    [onClose]
  );

  return { containerRef, handleKeyDown };
}
