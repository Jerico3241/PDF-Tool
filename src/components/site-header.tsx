import { Link } from "@tanstack/react-router";

export function SiteHeader() {
  return (
    <header className="border-b border-border bg-card">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center px-4 sm:px-6">
        <Link to="/" className="text-sm font-semibold tracking-tight">
          PDF Tool
        </Link>
      </div>
    </header>
  );
}
