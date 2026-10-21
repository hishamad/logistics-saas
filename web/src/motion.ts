// Small motion helpers. Both settle instantly for people who prefer reduced motion.
import { useEffect, useRef, useState } from "react";

// Reduced motion, or a page nobody can see (animation frames do not run there): settle at once.
const reduced = () =>
  typeof window !== "undefined" &&
  (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches || document.visibilityState === "hidden");

/** A number that counts up to `target` (ease-out), restarting when `target` changes. */
export function useCountUp(target: number, duration = 1300): number {
  const [value, setValue] = useState(reduced() ? target : 0);
  const from = useRef(0);
  useEffect(() => {
    if (reduced()) {
      setValue(target);
      return;
    }
    const start = performance.now();
    const origin = from.current;
    let frame = 0;
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - p, 3);
      setValue(origin + (target - origin) * eased);
      if (p < 1) frame = requestAnimationFrame(tick);
      else from.current = target;
    };
    frame = requestAnimationFrame(tick);
    // Frames can stall in a page that is not painted; the true number still arrives.
    const settle = setTimeout(() => {
      cancelAnimationFrame(frame);
      from.current = target;
      setValue(target);
    }, duration + 150);
    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(settle);
    };
  }, [target, duration]);
  return value;
}

/** Text that streams in a few characters at a time, like a reply being written. */
export function useStream(text: string): { shown: string; done: boolean } {
  const [count, setCount] = useState(0);
  useEffect(() => {
    if (reduced()) {
      setCount(text.length);
      return;
    }
    setCount(0);
    const id = setInterval(() => {
      setCount((n) => {
        if (n >= text.length) {
          clearInterval(id);
          return n;
        }
        return Math.min(text.length, n + 3);
      });
    }, 16);
    return () => clearInterval(id);
  }, [text]);
  return { shown: text.slice(0, count), done: count >= text.length };
}
