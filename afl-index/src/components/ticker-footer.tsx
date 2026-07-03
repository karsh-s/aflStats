import { TICKER_ITEMS } from "@/lib/afl-data";

export function TickerFooter() {
  const items = [...TICKER_ITEMS, ...TICKER_ITEMS];
  return (
    <footer className="fixed bottom-0 z-40 flex h-8 w-full items-center overflow-hidden bg-ink text-paper">
      <div className="animate-ticker flex shrink-0 items-center gap-10 whitespace-nowrap px-4">
        {items.map((it, i) => (
          <div key={i} className="flex items-center gap-2 font-mono text-[10px]">
            <span className="uppercase text-paper/40">{it.tag}</span>
            <span className="font-bold">{it.text}</span>
          </div>
        ))}
      </div>
    </footer>
  );
}
