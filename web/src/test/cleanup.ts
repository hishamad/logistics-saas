// Unmount every rendered component after each test, so tests never see each other.
// The test browser prefers reduced motion, so counts and streamed answers settle at once.
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

window.matchMedia = (query: string) =>
  ({ matches: query.includes("reduce"), media: query, addEventListener() {}, removeEventListener() {} }) as unknown as MediaQueryList;

afterEach(() => {
  cleanup();
  localStorage.clear();
});
