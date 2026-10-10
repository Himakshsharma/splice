import { Link } from "../router";
import { API_BASE } from "../services/api";
import { Logo } from "./Navbar";

export const REPO_URL = (import.meta.env.VITE_SOURCE_REPO_URL as string | undefined) || "";

export function Footer() {
  return (
    <footer className="border-t border-line">
      <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-10 sm:px-6 md:flex-row md:items-center md:justify-between">
        <div className="space-y-2">
          <Logo />
          <p className="max-w-sm text-sm text-muted">
            Open-source AI jump-cut editor. Whisper, NumPy, MoviePy and FFmpeg under the hood.
          </p>
        </div>
        <nav aria-label="Footer" className="flex flex-wrap gap-x-6 gap-y-2 text-sm text-muted">
          <Link href="/editor" className="hover:text-text">
            Editor
          </Link>
          <Link href="/about" className="hover:text-text">
            How SPLICE works
          </Link>
          <a href={`${API_BASE}/api/docs`} className="hover:text-text">
            API docs
          </a>
          {REPO_URL ? (
            <a href={REPO_URL} target="_blank" rel="noreferrer" className="hover:text-text">
              Source on GitHub
            </a>
          ) : null}
        </nav>
      </div>
    </footer>
  );
}
