import { useState } from "react";
import Attacks from "./pages/Attacks";
import Live from "./pages/Live";

type Page = "live" | "attacks";

export default function App() {
  const [page, setPage] = useState<Page>("live");
  const tab = (p: Page, label: string) => (
    <button
      onClick={() => setPage(p)}
      className={`px-4 py-2 rounded ${page === p ? "bg-white text-slate-900" : "text-slate-300 hover:text-white"}`}
    >
      {label}
    </button>
  );

  return (
    <div className="min-h-screen bg-slate-100 text-slate-900">
      <header className="flex items-center gap-6 bg-slate-900 px-6 py-3 text-white">
        <h1 className="text-xl font-bold">MandateGate</h1>
        <nav className="flex gap-2">
          {tab("live", "Live")}
          {tab("attacks", "Attacks")}
        </nav>
        <span className="ml-auto text-slate-400">The AI suggests. MandateGate decides.</span>
      </header>
      <main className="p-6">{page === "live" ? <Live /> : <Attacks />}</main>
    </div>
  );
}
