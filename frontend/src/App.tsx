import { Footer } from "./components/Footer";
import { Navbar } from "./components/Navbar";
import { AboutPage } from "./pages/AboutPage";
import { EditorPage } from "./pages/EditorPage";
import { LandingPage } from "./pages/LandingPage";
import { Link, usePathname } from "./router";

function NotFound() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-24 text-center">
      <h1 className="display text-5xl">Nothing here</h1>
      <p className="mt-4 text-muted">This page doesn't exist. The editor is a click away.</p>
      <Link href="/editor" className="btn btn-primary mt-8">
        Open the editor
      </Link>
    </div>
  );
}

export default function App() {
  const path = usePathname();
  const page = path === "/" ? <LandingPage /> : path === "/editor" ? <EditorPage /> : path === "/about" ? <AboutPage /> : <NotFound />;
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#content" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-keep focus:px-4 focus:py-2 focus:text-[#120f22]">
        Skip to content
      </a>
      <Navbar />
      <div id="content" className="flex-1">
        {page}
      </div>
      <Footer />
    </div>
  );
}
