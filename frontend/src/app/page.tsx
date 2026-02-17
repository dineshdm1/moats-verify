"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useAppStore } from "@/lib/stores";
import { verifyText, activateLibrary } from "@/lib/api";
import type { Library } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Progress } from "@/components/ui/progress";
import Link from "next/link";

export default function Home() {
  const router = useRouter();
  const { activeLibrary, libraries, isVerifying, setVerifying, setActiveLibrary } = useAppStore();
  const [text, setText] = useState("");
  const [progress, setProgress] = useState(0);
  const [progressText, setProgressText] = useState("");
  const [error, setError] = useState("");
  const [showLibPicker, setShowLibPicker] = useState(false);

  const handleVerify = useCallback(async () => {
    if (!text.trim() || isVerifying) return;
    setError("");
    setVerifying(true);
    setProgress(10);
    setProgressText("Extracting claims...");

    let progressInterval: ReturnType<typeof setInterval> | null = null;
    try {
      // Simulate progress since API doesn't stream progress
      progressInterval = setInterval(() => {
        setProgress((p) => Math.min(p + 8, 85));
      }, 1500);

      setProgressText("Retrieving evidence...");
      const result = await verifyText(text, activeLibrary?.id);

      clearInterval(progressInterval);
      setProgress(100);
      setProgressText("Complete!");
      setVerifying(false);

      setTimeout(() => {
        router.push(`/results/${result.verification_id}`);
      }, 500);
    } catch (err) {
      if (progressInterval) clearInterval(progressInterval);
      setVerifying(false);
      setProgress(0);
      setProgressText("");
      setError(err instanceof Error ? err.message : "Verification failed");
    }
  }, [text, activeLibrary, isVerifying, setVerifying, router]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file && file.type === "text/plain") {
      const reader = new FileReader();
      reader.onload = (ev) => setText(ev.target?.result as string || "");
      reader.readAsText(file);
    }
  }, []);

  const handleSwitchLibrary = async (lib: Library) => {
    try {
      await activateLibrary(lib.id);
      setActiveLibrary(lib);
      setShowLibPicker(false);
    } catch {}
  };

  // No library — first-time user
  if (!activeLibrary) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-6">
        <h1 className="text-2xl font-light text-foreground">Welcome to Moats Verify</h1>
        <p className="text-sm text-muted-foreground">Connect your documents to start verifying</p>
        <Link href="/library">
          <Button size="lg">Connect Sources</Button>
        </Link>
      </div>
    );
  }

  // Verifying state
  if (isVerifying) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-6">
        <h2 className="text-lg font-light text-foreground">Verifying claims...</h2>
        <div className="w-80">
          <Progress value={progress} className="h-2" />
        </div>
        <p className="text-sm text-muted-foreground">{progressText}</p>
      </div>
    );
  }

  // Ready to verify
  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 px-4">
      <h1 className="text-xl font-light text-foreground">What would you like to verify?</h1>

      <div
        className="w-full max-w-2xl"
        onDragOver={(e) => e.preventDefault()}
        onDrop={handleDrop}
      >
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Paste the text you want to fact-check..."
          className="min-h-[200px] resize-none bg-card text-sm"
        />
      </div>

      {error && (
        <p className="text-sm text-red-400">{error}</p>
      )}

      <Button
        size="lg"
        onClick={handleVerify}
        disabled={!text.trim()}
        className="min-w-[120px]"
      >
        VERIFY
      </Button>

      {/* Library picker */}
      <div className="relative">
        <button
          onClick={() => setShowLibPicker(!showLibPicker)}
          className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          Verifying against: {activeLibrary.name} ({activeLibrary.doc_count} docs)
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="ml-1">
            <path d="M6 9l6 6 6-6" />
          </svg>
        </button>

        {showLibPicker && libraries.length > 1 && (
          <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 rounded-md border border-border bg-card p-2 shadow-lg">
            <p className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Select Library</p>
            {libraries.map((lib) => (
              <button
                key={lib.id}
                onClick={() => handleSwitchLibrary(lib)}
                className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-xs transition-colors ${
                  activeLibrary.id === lib.id
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent"
                }`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${activeLibrary.id === lib.id ? "bg-emerald-500" : "bg-zinc-600"}`} />
                <div>
                  <p className="text-foreground">{lib.name}</p>
                  <p className="text-[10px] text-muted-foreground">{lib.doc_count} docs &bull; {lib.chunk_count.toLocaleString()} chunks</p>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
