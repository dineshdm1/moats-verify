"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAppStore } from "@/lib/stores";
import { getHealth, getLibraries, getHistory, cancelBuild } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";

export function Header() {
  const router = useRouter();
  const { toggleSidebar, activeLibrary, setActiveLibrary, setLibraries, setHistory, build, resetBuild } = useAppStore();

  useEffect(() => {
    const load = async () => {
      try {
        const [health, libs, hist] = await Promise.all([
          getHealth().catch(() => null),
          getLibraries().catch(() => []),
          getHistory().catch(() => []),
        ]);
        setLibraries(libs);
        setHistory(hist);
        if (health?.active_library) {
          const active = libs.find((l) => l.id === health.active_library?.id);
          if (active) setActiveLibrary(active);
        } else if (libs.length > 0) {
          setActiveLibrary(libs[0]);
        }
      } catch {
        // Backend not available yet
      }
    };
    load();
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, [setActiveLibrary, setLibraries, setHistory]);

  const isBuilding = build.building && build.buildLibraryId === activeLibrary?.id;

  const handleCancelBuild = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!activeLibrary) return;
    try {
      await cancelBuild(activeLibrary.id);
      resetBuild();
    } catch {}
  };

  const statusColor =
    activeLibrary?.status === "ready"
      ? "bg-emerald-500"
      : activeLibrary?.status === "building"
        ? "bg-amber-500"
        : activeLibrary?.status === "error"
          ? "bg-red-500"
          : "bg-zinc-500";

  return (
    <header className="flex h-14 items-center justify-between border-b border-border px-4">
      <div className="flex items-center gap-3">
        <button onClick={toggleSidebar} className="text-muted-foreground hover:text-foreground">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 12h18M3 6h18M3 18h18" />
          </svg>
        </button>
        <span className="text-sm font-semibold tracking-wider text-foreground">MOATS VERIFY</span>
      </div>

      {activeLibrary && (
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          {/* Build progress indicator — visible from any page */}
          {isBuilding && (
            <div
              className="flex cursor-pointer items-center gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 transition-colors hover:bg-amber-500/20"
              onClick={() => router.push("/library")}
            >
              <div className="w-24">
                <Progress value={build.buildProgress} className="h-1.5" />
              </div>
              <span className="text-[11px] text-amber-400">
                {Math.round(build.buildProgress)}%
              </span>
              <button
                onClick={handleCancelBuild}
                className="ml-1 text-[10px] text-zinc-500 hover:text-red-400 transition-colors"
                title="Cancel build"
              >
                &times;
              </button>
            </div>
          )}

          <span>{activeLibrary.doc_count} docs</span>
          <span className="text-zinc-600">&bull;</span>
          <span>{activeLibrary.chunk_count.toLocaleString()} chunks</span>
          <span className="text-zinc-600">&bull;</span>
          <Badge variant="outline" className="gap-1.5 text-xs">
            <span className={`h-1.5 w-1.5 rounded-full ${isBuilding ? "bg-amber-500 animate-pulse" : statusColor}`} />
            {isBuilding
              ? "Syncing..."
              : activeLibrary.status === "ready"
                ? "Ready"
                : activeLibrary.status}
          </Badge>
        </div>
      )}
    </header>
  );
}
