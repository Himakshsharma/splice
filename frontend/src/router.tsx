import { useEffect, useState, type AnchorHTMLAttributes, type MouseEvent } from "react";

/** A deliberately tiny history router — three pages don't need a routing library. */

const listeners = new Set<() => void>();

export function navigate(to: string): void {
  if (to === window.location.pathname + window.location.hash) return;
  window.history.pushState({}, "", to);
  listeners.forEach((l) => l());
  const hash = to.split("#")[1];
  if (hash) requestAnimationFrame(() => document.getElementById(hash)?.scrollIntoView({ behavior: "smooth" }));
  else window.scrollTo({ top: 0 });
}

export function usePathname(): string {
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => {
    const update = () => setPath(window.location.pathname);
    listeners.add(update);
    window.addEventListener("popstate", update);
    return () => {
      listeners.delete(update);
      window.removeEventListener("popstate", update);
    };
  }, []);
  return path;
}

export function Link({ href = "/", onClick, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) {
  const handle = (e: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(e);
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (/^https?:/.test(href)) return;
    e.preventDefault();
    navigate(href);
  };
  return <a href={href} onClick={handle} {...rest} />;
}
