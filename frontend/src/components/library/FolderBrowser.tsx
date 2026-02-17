"use client";

import { useEffect, useState } from "react";
import { browseFolders } from "@/lib/api";
import type { BrowseEntry } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";

interface FolderBrowserProps {
  onSelect: (path: string) => void;
}

export function FolderBrowser({ onSelect }: FolderBrowserProps) {
  const [currentPath, setCurrentPath] = useState("~");
  const [parentPath, setParentPath] = useState<string | null>(null);
  const [entries, setEntries] = useState<BrowseEntry[]>([]);
  const [supportedFiles, setSupportedFiles] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadPath = async (path: string) => {
    setLoading(true);
    setError("");
    try {
      const result = await browseFolders(path);
      setCurrentPath(result.current_path);
      setParentPath(result.parent_path);
      setEntries(result.entries);
      setSupportedFiles(result.supported_files);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to browse");
    }
    setLoading(false);
  };

  useEffect(() => {
    const timer = setTimeout(() => {
      void loadPath("~");
    }, 0);
    return () => clearTimeout(timer);
  }, []);

  const directories = entries.filter((e) => e.type === "directory");
  const files = entries.filter((e) => e.type === "file");

  // Count total supported files recursively visible
  const totalFilesInSubdirs = directories.reduce((acc, d) => acc + (d.file_count || 0), 0);
  return (
    <div className="space-y-3">
      {/* Current path breadcrumb */}
      <div className="flex items-center gap-2 rounded-md bg-muted/50 px-3 py-2">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="shrink-0 text-muted-foreground">
          <path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
        </svg>
        <span className="truncate text-xs text-foreground">{currentPath}</span>
      </div>

      {error && <p className="text-xs text-red-400">{error}</p>}

      {/* Directory listing */}
      <ScrollArea className="h-64 rounded-md border border-border">
        <div className="p-1">
          {/* Go up */}
          {parentPath && (
            <button
              onClick={() => loadPath(parentPath)}
              className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-xs text-muted-foreground hover:bg-accent"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M15 18l-6-6 6-6" />
              </svg>
              ..
            </button>
          )}

          {loading && (
            <p className="px-3 py-4 text-center text-xs text-muted-foreground">Loading...</p>
          )}

          {!loading && directories.length === 0 && files.length === 0 && (
            <p className="px-3 py-4 text-center text-xs text-muted-foreground">Empty directory</p>
          )}

          {/* Directories */}
          {directories.map((entry) => (
            <button
              key={entry.path}
              onClick={() => loadPath(entry.path)}
              className="flex w-full items-center justify-between rounded-md px-3 py-2 text-left hover:bg-accent"
            >
              <div className="flex items-center gap-2">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-amber-500">
                  <path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                </svg>
                <span className="text-xs text-foreground">{entry.name}</span>
              </div>
              {entry.file_count !== undefined && entry.file_count > 0 && (
                <span className="text-[10px] text-muted-foreground">{entry.file_count} docs</span>
              )}
            </button>
          ))}

          {/* Files (shown for context, not selectable) */}
          {files.map((entry) => (
            <div
              key={entry.path}
              className="flex items-center justify-between px-3 py-1.5"
            >
              <div className="flex items-center gap-2">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-zinc-500">
                  <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
                  <path d="M14 2v6h6" />
                </svg>
                <span className="text-[11px] text-muted-foreground">{entry.name}</span>
              </div>
              {entry.size !== undefined && (
                <span className="text-[10px] text-muted-foreground">
                  {entry.size > 1048576
                    ? `${(entry.size / 1048576).toFixed(1)} MB`
                    : `${Math.round(entry.size / 1024)} KB`}
                </span>
              )}
            </div>
          ))}
        </div>
      </ScrollArea>

      {/* Selection footer */}
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">
          {supportedFiles > 0
            ? `${supportedFiles} supported files in this folder`
            : totalFilesInSubdirs > 0
              ? `${totalFilesInSubdirs} docs in subfolders`
              : "No supported files here"}
        </span>
        <Button size="sm" onClick={() => onSelect(currentPath)}>
          Select This Folder
        </Button>
      </div>
    </div>
  );
}
