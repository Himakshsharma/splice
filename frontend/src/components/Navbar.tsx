import { Menu, X } from "lucide-react";
import { useState } from "react";
import { Link, usePathname } from "../router";

export function Logo({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden="true">
        <rect width="32" height="32" rx="8" fill="var(--color-raised)" />
        <rect x="5" y="12" width="3" height="8" rx="1.5" fill="var(--color-keep)" />
        <rect x="10" y="8" width="3" height="16" rx="1.5" fill="var(--color-keep)" />
        <rect x="19" y="10" width="3" height="12" rx="1.5" fill="var(--color-cut)" />
        <rect x="24" y="13" width="3" height="6" rx="1.5" fill="var(--color-cut)" />
        <path d="M16 5v22" stroke="var(--color-text)" strokeWidth="1.6" strokeDasharray="2.5 2.5" strokeLinecap="round" />
      </svg>
      <span className="display text-[1.35rem] tracking-[0.02em]">SPLICE</span>
    </span>
  );
}

const LINKS = [
  { href: "/", label: "Home" },
  { href: "/#how-it-works", label: "How it works" },
  { href: "/#features", label: "Features" },
  { href: "/about", label: "About" },
];

export function Navbar() {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const isActive = (href: string) => (href === "/" ? path === "/" : href.startsWith("/about") && path === "/about");

  return (
    <header className="sticky top-0 z-40 border-b border-line/70 bg-ink/80 backdrop-blur-md">
      <nav className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6" aria-label="Main">
        <Link href="/" aria-label="SPLICE home" className="rounded-md">
          <Logo />
        </Link>

        <div className="hidden items-center gap-1 md:flex">
          {LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className={`rounded-lg px-3 py-2 text-sm transition-colors hover:text-text ${isActive(l.href) ? "text-text" : "text-muted"}`}
              aria-current={isActive(l.href) ? "page" : undefined}
            >
              {l.label}
            </Link>
          ))}
          <Link href="/editor" className="btn btn-primary ml-3 !py-2 text-sm">
            Start editing
          </Link>
        </div>

        <button
          type="button"
          className="btn btn-ghost !p-2 md:hidden"
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
        >
          {open ? <X size={20} /> : <Menu size={20} />}
        </button>
      </nav>
      {open && (
        <div className="border-t border-line px-4 pb-4 md:hidden">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} onClick={() => setOpen(false)} className="block py-3 text-muted hover:text-text">
              {l.label}
            </Link>
          ))}
          <Link href="/editor" onClick={() => setOpen(false)} className="btn btn-primary mt-2 w-full">
            Start editing
          </Link>
        </div>
      )}
    </header>
  );
}
