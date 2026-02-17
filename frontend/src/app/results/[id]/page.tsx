"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { deleteVerification, getVerification } from "@/lib/api";
import type { VerdictItem } from "@/lib/api";
import { VerdictCard } from "@/components/verify/VerdictCard";
import { TrustScore } from "@/components/verify/TrustScore";
import { Button } from "@/components/ui/button";
import Link from "next/link";

interface VerificationData {
  id: string;
  input_text: string;
  trust_score: number;
  claims: VerdictItem[];
  created_at: string;
}

export default function ResultsPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;
  const [data, setData] = useState<VerificationData | null>(null);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    getVerification(id)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [id]);

  if (error) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-red-400">{error}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-muted-foreground">Loading...</p>
      </div>
    );
  }

  const counts = { supported: 0, partially_supported: 0, contradicted: 0, conflicting: 0, no_evidence: 0 };
  for (const c of data.claims) {
    const key = c.verdict.toLowerCase() as keyof typeof counts;
    if (key in counts) counts[key]++;
  }
  const reasoningCount = data.claims.filter((c) => c.used_llm === true).length;
  const comparisonCount = data.claims.filter((c) => c.used_llm === false).length;

  const handleExport = () => {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `verification_${id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleDelete = async () => {
    const confirmed = window.confirm("Delete this verification result? This cannot be undone.");
    if (!confirmed) return;

    setDeleting(true);
    try {
      await deleteVerification(id);
      router.push("/");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
      setDeleting(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <h1 className="text-lg font-semibold text-foreground">VERIFICATION RESULTS</h1>

      <TrustScore
        score={data.trust_score}
        totalClaims={data.claims.length}
        supported={counts.supported}
        partiallySUpported={counts.partially_supported}
        contradicted={counts.contradicted}
        conflicting={counts.conflicting}
        noEvidence={counts.no_evidence}
      />
      <p className="text-xs text-muted-foreground">
        Report methods: {comparisonCount} via comparison, {reasoningCount} via reasoning
      </p>

      <div className="space-y-3">
        {data.claims.map((verdict, i) => (
          <VerdictCard key={i} verdict={verdict} />
        ))}
      </div>

      <div className="flex justify-between pt-4">
        <Button variant="outline" onClick={handleExport}>
          Download JSON
        </Button>
        <div className="flex items-center gap-2">
          <Link href="/">
            <Button>Verify Another</Button>
          </Link>
          <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
            {deleting ? "Deleting..." : "Delete Result"}
          </Button>
        </div>
      </div>
    </div>
  );
}
