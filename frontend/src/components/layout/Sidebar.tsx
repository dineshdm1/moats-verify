"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAppStore } from "@/lib/stores";
import { activateLibrary } from "@/lib/api";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";

const navItems = [
  { href: "/", label: "Verify", icon: "M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" },
  { href: "/library", label: "Library", icon: "M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" },
  { href: "/settings", label: "Settings", icon: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z" },
];

function timeAgo(dateStr: string) {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function Sidebar() {
  const pathname = usePathname();
  const { sidebarOpen, libraries, history, activeLibrary, setActiveLibrary } = useAppStore();

  const handleLibraryClick = async (lib: typeof libraries[0]) => {
    try {
      await activateLibrary(lib.id);
      setActiveLibrary(lib);
    } catch {}
  };

  if (!sidebarOpen) return null;

  return (
    <aside className="flex w-56 flex-col border-r border-border bg-card">
      <div className="p-4">
        <span className="text-xs font-semibold tracking-widest text-muted-foreground">MOATS VERIFY</span>
      </div>

      <nav className="space-y-0.5 px-2">
        {navItems.map((item) => {
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors ${
                active
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              }`}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d={item.icon} strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              {item.label}
            </Link>
          );
        })}
      </nav>

      <Separator className="my-3" />

      <div className="px-4 pb-1">
        <span className="text-[10px] font-semibold tracking-widest text-muted-foreground">HISTORY</span>
      </div>
      <ScrollArea className="flex-1 px-2">
        {history.length === 0 ? (
          <p className="px-3 py-2 text-xs text-muted-foreground">No verifications yet</p>
        ) : (
          history.slice(0, 10).map((item) => (
            <Link
              key={item.id}
              href={`/results/${item.id}`}
              className="block rounded-md px-3 py-2 hover:bg-accent"
            >
              <p className="truncate text-xs text-foreground">{item.input_text}</p>
              <p className="text-[10px] text-muted-foreground">
                {Math.round(item.trust_score * 100)}% trust &bull; {timeAgo(item.created_at)}
              </p>
            </Link>
          ))
        )}
      </ScrollArea>

      <Separator className="my-3" />

      <div className="px-4 pb-1">
        <span className="text-[10px] font-semibold tracking-widest text-muted-foreground">LIBRARIES</span>
      </div>
      <div className="space-y-0.5 px-2 pb-4">
        {libraries.map((lib) => (
          <button
            key={lib.id}
            onClick={() => handleLibraryClick(lib)}
            className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-xs transition-colors ${
              activeLibrary?.id === lib.id
                ? "bg-accent text-accent-foreground"
                : "text-muted-foreground hover:bg-accent"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                activeLibrary?.id === lib.id ? "bg-emerald-500" : "bg-zinc-600"
              }`}
            />
            {lib.name}
          </button>
        ))}
        <Link
          href="/library"
          className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground hover:text-foreground"
        >
          <span>+</span> New Library
        </Link>
      </div>
    </aside>
  );
}
