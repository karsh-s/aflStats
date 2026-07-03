import type { ReactNode } from "react";
import { SiteHeader } from "./site-header";
import { TickerFooter } from "./ticker-footer";

export function PageShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-paper text-ink selection:bg-accent selection:text-accent-foreground">
      <SiteHeader />
      <main className="mx-auto max-w-[1440px] px-4 pb-16 pt-6">{children}</main>
      <div className="h-8" />
      <TickerFooter />
    </div>
  );
}

export function SectionHeading({
  title,
  meta,
}: {
  title: string;
  meta?: string;
}) {
  return (
    <div className="flex items-end justify-between border-b-2 border-ink pb-1">
      <h2 className="font-display text-2xl font-extrabold uppercase tracking-tighter text-balance">
        {title}
      </h2>
      {meta ? (
        <span className="mb-1 font-mono text-[10px] text-muted-foreground">
          {meta}
        </span>
      ) : null}
    </div>
  );
}
