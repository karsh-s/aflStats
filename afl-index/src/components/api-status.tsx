/** Small banner shown when the model API is offline — site still works via static data. */
export function ApiOfflineBanner() {
  return (
    <div className="border border-border bg-card px-4 py-3 text-xs text-muted-foreground">
      <span className="mr-2 font-bold uppercase">Model offline</span>
      Live win probabilities, player props and value bets require the API server
      (<code className="font-mono">uvicorn api.main:app --port 8001</code>). Showing
      cached/demo data.
    </div>
  );
}

export function ApiLoading({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-6 text-xs text-muted-foreground">
      <span className="size-2 animate-pulse rounded-full bg-accent" />
      <span>{label ?? "Loading from model…"}</span>
    </div>
  );
}
