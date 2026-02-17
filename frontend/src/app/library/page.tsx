"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useAppStore } from "@/lib/stores";
import {
  getLibraries, createLibrary, deleteLibrary, activateLibrary,
  getSources, deleteSource, syncSource, uploadFiles,
  startBuild, getBuildStatus, cancelBuild,
  probeChromaDB, connectChromaDB,
} from "@/lib/api";
import type { Library, Source } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";

function timeAgo(dateStr: string) {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function sourceName(src: Source): string {
  const path = (src.config as Record<string, string>).path;
  if (!path) return "Uploaded files";
  const parts = path.replace(/\/+$/, "").split("/");
  return parts[parts.length - 1] || path;
}

export default function LibraryPage() {
  const { libraries, setLibraries, activeLibrary, setActiveLibrary, build, setBuild, resetBuild } = useAppStore();
  const [sources, setSources] = useState<Source[]>([]);
  const [newName, setNewName] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [showAddSource, setShowAddSource] = useState(false);
  const [showChromaConnect, setShowChromaConnect] = useState(false);
  const [chromaPath, setChromaPath] = useState("");
  const [chromaProbe, setChromaProbe] = useState<{ valid: boolean; collections?: { name: string; count: number }[]; total_chunks?: number; error?: string } | null>(null);
  const [chromaProbing, setChromaProbing] = useState(false);
  const [error, setError] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const folderInputRef = useRef<HTMLInputElement | null>(null);

  const loadSources = useCallback(async () => {
    if (activeLibrary) {
      try {
        const s = await getSources(activeLibrary.id);
        setSources(s);
      } catch (e) {
        console.error("Failed to load sources:", e);
      }
    }
  }, [activeLibrary]);

  // Start or resume polling for build status
  const startPolling = useCallback((libraryId: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const status = await getBuildStatus(libraryId);
        setBuild({
          buildProgress: status.progress * 100,
          buildStep: status.current_step,
          buildSteps: status.steps_completed,
          buildError: status.error,
        });

        if (status.status === "completed" || status.status === "failed" || status.status === "cancelled") {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setBuild({ building: false });
          if (status.status === "failed") {
            setBuild({ buildError: status.error || "Build failed" });
          }
          const libs = await getLibraries();
          setLibraries(libs);
          const updated = libs.find((l) => l.id === libraryId);
          if (updated) setActiveLibrary(updated);
        }
      } catch {
        // Status endpoint may 404 if no builds exist — stop polling
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = null;
        resetBuild();
      }
    }, 2000);
  }, [setBuild, resetBuild, setLibraries, setActiveLibrary]);

  // On mount / activeLibrary change: check if a build is running
  useEffect(() => {
    if (!activeLibrary) return;

    // If store says we're building for this library, resume polling
    if (build.building && build.buildLibraryId === activeLibrary.id) {
      startPolling(activeLibrary.id);
      return;
    }

    // Also check backend in case we navigated away and back
    let cancelled = false;
    (async () => {
      try {
        const status = await getBuildStatus(activeLibrary.id);
        if (cancelled) return;
        if (status.status === "running" || status.status === "pending") {
          setBuild({
            building: true,
            buildLibraryId: activeLibrary.id,
            buildProgress: status.progress * 100,
            buildStep: status.current_step,
            buildSteps: status.steps_completed,
            buildError: null,
          });
          startPolling(activeLibrary.id);
        }
      } catch {
        // No build jobs — that's fine
      }
    })();

    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeLibrary?.id]);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  useEffect(() => { loadSources(); }, [loadSources]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setError("");
    try {
      const lib = await createLibrary(newName);
      const libs = await getLibraries();
      setLibraries(libs);
      setActiveLibrary(lib);
      setNewName("");
      setShowCreate(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create library");
    }
  };

  const handleDelete = async (id: string) => {
    setError("");
    try {
      await deleteLibrary(id);
      const libs = await getLibraries();
      setLibraries(libs);
      if (activeLibrary?.id === id) {
        setActiveLibrary(libs[0] || null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete library");
    }
  };

  const handleActivate = async (lib: Library) => {
    try {
      await activateLibrary(lib.id);
      setActiveLibrary(lib);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to activate library");
    }
  };

  const handleUploadFiles = async (files: File[]) => {
    if (!activeLibrary) return false;
    if (files.length === 0) {
      setError("No supported documents found in the selected folder.");
      return false;
    }
    setError("");
    try {
      const result = await uploadFiles(activeLibrary.id, files);
      const successful = result.results.filter((r) => r.status === "success");
      if (successful.length === 0) {
        const firstError = result.results.find((r) => r.status === "error");
        setError(firstError?.error || "No documents were ingested.");
        return false;
      }
      loadSources();
      const libs = await getLibraries();
      setLibraries(libs);
      const updated = libs.find((l) => l.id === activeLibrary.id);
      if (updated) setActiveLibrary(updated);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
      return false;
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files) return;
    await handleUploadFiles(Array.from(e.target.files));
    e.target.value = "";
  };

  const handleFolderPick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files) return;
    const files = Array.from(e.target.files).filter((f) =>
      /\.(pdf|epub|docx|doc|txt|md)$/i.test(f.name)
    );
    const ok = await handleUploadFiles(files);
    if (ok) setShowAddSource(false);
    e.target.value = "";
  };

  const handleBuild = async () => {
    if (!activeLibrary) return;
    setError("");
    setBuild({
      building: true,
      buildLibraryId: activeLibrary.id,
      buildProgress: 0,
      buildStep: "Starting...",
      buildSteps: [],
      buildError: null,
    });

    try {
      await startBuild(activeLibrary.id);
      startPolling(activeLibrary.id);
    } catch (e) {
      resetBuild();
      setError(e instanceof Error ? e.message : "Failed to start build");
    }
  };

  const handleCancelBuild = async () => {
    if (!activeLibrary) return;
    try {
      await cancelBuild(activeLibrary.id);
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
      resetBuild();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to cancel build");
    }
  };

  const handleProbeChroma = async () => {
    if (!chromaPath.trim()) return;
    setChromaProbing(true);
    setChromaProbe(null);
    try {
      const result = await probeChromaDB(chromaPath);
      setChromaProbe(result);
    } catch (e) {
      setChromaProbe({ valid: false, error: e instanceof Error ? e.message : "Probe failed" });
    }
    setChromaProbing(false);
  };

  const handleConnectChroma = async () => {
    if (!chromaPath.trim() || !activeLibrary || !chromaProbe?.valid) return;
    setError("");
    try {
      await connectChromaDB(activeLibrary.id, chromaPath);
      setShowChromaConnect(false);
      setShowAddSource(false);
      setChromaPath("");
      setChromaProbe(null);
      loadSources();
      const libs = await getLibraries();
      setLibraries(libs);
      const updated = libs.find((l) => l.id === activeLibrary.id);
      if (updated) setActiveLibrary(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to connect ChromaDB");
    }
  };

  const building = build.building && build.buildLibraryId === activeLibrary?.id;

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <h1 className="text-lg font-semibold text-foreground">LIBRARY</h1>

      {error && (
        <div className="flex items-center justify-between rounded-md bg-red-500/10 px-4 py-2">
          <p className="text-sm text-red-400">{error}</p>
          <button onClick={() => setError("")} className="text-xs text-red-400 hover:text-red-300">dismiss</button>
        </div>
      )}

      {/* Library selector */}
      <Card className="p-4">
        <div className="space-y-2">
          {libraries.map((lib) => (
            <div
              key={lib.id}
              className={`flex items-center justify-between rounded-md p-3 ${
                activeLibrary?.id === lib.id ? "bg-accent" : "hover:bg-accent/50"
              }`}
            >
              <button
                className="flex items-center gap-2 text-left"
                onClick={() => handleActivate(lib)}
              >
                <span
                  className={`h-2 w-2 rounded-full ${
                    activeLibrary?.id === lib.id ? "bg-emerald-500" : "bg-zinc-600"
                  }`}
                />
                <div>
                  <p className="text-sm font-medium text-foreground">{lib.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {lib.doc_count} docs &bull; {lib.chunk_count.toLocaleString()} chunks &bull; {lib.status}
                  </p>
                </div>
              </button>
              <Button variant="ghost" size="sm" onClick={() => handleDelete(lib.id)}>
                Delete
              </Button>
            </div>
          ))}
        </div>

        <Dialog open={showCreate} onOpenChange={setShowCreate}>
          <DialogTrigger asChild>
            <Button variant="outline" className="mt-3 w-full">
              + Create New Library
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Create Library</DialogTitle>
            </DialogHeader>
            <div className="space-y-4">
              <div>
                <Label>Name</Label>
                <Input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="e.g., Research Docs"
                  onKeyDown={(e) => e.key === "Enter" && handleCreate()}
                />
              </div>
              <Button onClick={handleCreate} disabled={!newName.trim()}>
                Create
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </Card>

      {activeLibrary && (
        <>
          <Separator />

          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-foreground">Sources</h2>
            {building ? (
              <Button size="sm" variant="outline" onClick={handleCancelBuild}>
                Cancel Sync
              </Button>
            ) : (
              <Button size="sm" onClick={handleBuild} disabled={activeLibrary.chunk_count === 0}>
                Sync Now
              </Button>
            )}
          </div>

          {/* Build progress */}
          {building && (
            <Card className="p-4">
              <p className="text-sm font-medium text-foreground">Syncing...</p>
              <div className="mt-3 space-y-2">
                {["ingestion", "chunking", "embedding"].map(
                  (step) => {
                    const done = build.buildSteps.includes(step);
                    const current = build.buildStep === step || build.buildStep.startsWith("Processing:");
                    return (
                      <div key={step} className="flex items-center gap-2 text-xs">
                        <span>
                          {done ? "\u2713" : current ? "\u25B6" : "\u25CB"}
                        </span>
                        <span className={done ? "text-emerald-400" : current ? "text-foreground" : "text-muted-foreground"}>
                          {step.replace("_", " ")}
                        </span>
                      </div>
                    );
                  }
                )}
              </div>
              <Progress value={build.buildProgress} className="mt-3 h-2" />
            </Card>
          )}

          {/* Build error */}
          {build.buildError && !building && (
            <Card className="border-red-500/30 p-4">
              <p className="text-sm text-red-400">Sync failed: {build.buildError}</p>
              <Button size="sm" variant="ghost" className="mt-2" onClick={resetBuild}>
                Dismiss
              </Button>
            </Card>
          )}

          {/* Sources */}
          <div className="space-y-3">
            {sources.map((src) => (
              <Card key={src.id} className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-foreground">{sourceName(src)}</p>
                    <p className="text-xs text-muted-foreground">
                      {src.doc_count} files
                      {src.last_synced ? ` \u2022 Synced ${timeAgo(src.last_synced)}` : ""}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    {src.source_type === "local_folder" && (
                      <Button variant="outline" size="sm" onClick={() => syncSource(src.id)}>
                        Sync
                      </Button>
                    )}
                    <Button variant="ghost" size="sm" onClick={async () => { await deleteSource(src.id); loadSources(); }}>
                      Remove
                    </Button>
                  </div>
                </div>
              </Card>
            ))}
          </div>

          {/* Add source */}
          <Dialog open={showAddSource} onOpenChange={(open) => {
            setShowAddSource(open);
            if (!open) { setShowChromaConnect(false); setChromaPath(""); setChromaProbe(null); }
          }}>
            <DialogTrigger asChild>
              <Button variant="outline">+ Add Source</Button>
            </DialogTrigger>
            <DialogContent className="max-w-lg">
              <DialogHeader>
                <DialogTitle>
                  {showChromaConnect ? "Connect ChromaDB" : "Add Source"}
                </DialogTitle>
              </DialogHeader>

              {showChromaConnect ? (
                <div className="space-y-4">
                  <div>
                    <Label>ChromaDB Directory Path</Label>
                    <div className="flex gap-2 mt-1">
                      <Input
                        value={chromaPath}
                        onChange={(e) => { setChromaPath(e.target.value); setChromaProbe(null); }}
                        placeholder="/path/to/chromadb/data"
                        onKeyDown={(e) => e.key === "Enter" && handleProbeChroma()}
                      />
                      <Button size="sm" onClick={handleProbeChroma} disabled={!chromaPath.trim() || chromaProbing}>
                        {chromaProbing ? "..." : "Probe"}
                      </Button>
                    </div>
                  </div>

                  {chromaProbe && (
                    <Card className={`p-3 ${chromaProbe.valid ? "border-emerald-500/30" : "border-red-500/30"}`}>
                      {chromaProbe.valid ? (
                        <div className="space-y-2">
                          <p className="text-xs text-emerald-400">Valid ChromaDB found</p>
                          <p className="text-xs text-muted-foreground">
                            {chromaProbe.collections?.length} collection(s) &bull; {chromaProbe.total_chunks?.toLocaleString()} total chunks
                          </p>
                          {chromaProbe.collections?.map((col) => (
                            <div key={col.name} className="flex justify-between text-xs">
                              <span className="text-foreground">{col.name}</span>
                              <span className="text-muted-foreground">{col.count.toLocaleString()} chunks</span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs text-red-400">{chromaProbe.error}</p>
                      )}
                    </Card>
                  )}

                  <div className="flex gap-2">
                    <Button variant="ghost" size="sm" onClick={() => { setShowChromaConnect(false); setChromaPath(""); setChromaProbe(null); }}>
                      Back
                    </Button>
                    {chromaProbe?.valid && (
                      <Button size="sm" onClick={handleConnectChroma}>
                        Connect
                      </Button>
                    )}
                  </div>
                </div>
              ) : (
                <div className="space-y-4">
                  <Card
                    className="cursor-pointer p-4 hover:bg-accent/50 transition-colors"
                    onClick={() => folderInputRef.current?.click()}
                  >
                    <div className="flex items-center gap-3">
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-amber-500">
                        <path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                      </svg>
                      <div>
                        <p className="text-sm font-medium text-foreground">Local Folder</p>
                        <p className="text-xs text-muted-foreground">Choose a local folder from your device</p>
                      </div>
                    </div>
                    <input
                      ref={folderInputRef}
                      type="file"
                      multiple
                      accept=".pdf,.epub,.docx,.doc,.txt,.md"
                      onChange={handleFolderPick}
                      className="hidden"
                      {...({ webkitdirectory: "true", directory: "true" } as Record<string, string>)}
                    />
                  </Card>

                  <Card
                    className="cursor-pointer p-4 hover:bg-accent/50 transition-colors"
                    onClick={() => setShowChromaConnect(true)}
                  >
                    <div className="flex items-center gap-3">
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-purple-400">
                        <path d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7" />
                        <path d="M20 7c0 2.21-3.582 4-8 4S4 9.21 4 7s3.582-4 8-4 8 1.79 8 4z" />
                        <path d="M4 12c0 2.21 3.582 4 8 4s8-1.79 8-4" />
                      </svg>
                      <div>
                        <p className="text-sm font-medium text-foreground">ChromaDB Directory</p>
                        <p className="text-xs text-muted-foreground">Connect an existing local ChromaDB directory</p>
                      </div>
                    </div>
                  </Card>

                  <Card className="p-4">
                    <div className="flex items-center gap-3">
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-blue-400">
                        <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12" />
                      </svg>
                      <div className="flex-1">
                        <p className="text-sm font-medium text-foreground">Upload Files</p>
                        <p className="text-xs text-muted-foreground">Upload documents manually</p>
                        <input
                          type="file"
                          multiple
                          accept=".pdf,.epub,.docx,.doc,.txt,.md"
                          onChange={handleUpload}
                          className="mt-2 block text-xs text-muted-foreground file:mr-2 file:rounded-md file:border-0 file:bg-accent file:px-3 file:py-1.5 file:text-xs file:text-foreground hover:file:bg-accent/80"
                        />
                      </div>
                    </div>
                  </Card>
                </div>
              )}
            </DialogContent>
          </Dialog>
        </>
      )}
    </div>
  );
}
