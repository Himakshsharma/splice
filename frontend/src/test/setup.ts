import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Vitest runs without globals here, so Testing Library's automatic cleanup
// never registers. Unmount after each test so renders don't leak into the next.
afterEach(() => {
  cleanup();
});
