"use client";

import { useState } from "react";
import type { VerdictItem } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const verdictStyles: Record<string, { icon: string; color: string; bg: string }> = {
  SUPPORTED: { icon: "\u2713", color: "text-emerald-400", bg: "border-emerald-500/20" },
  PARTIALLY_SUPPORTED: { icon: "\u25D0", color: "text-amber-400", bg: "border-amber-500/20" },
  CONTRADICTED: { icon: "\u2717", color: "text-red-400", bg: "border-red-500/20" },
  CONFLICTING: { icon: "\u26A0", color: "text-orange-400", bg: "border-orange-500/20" },
  NO_EVIDENCE: { icon: "?", color: "text-zinc-400", bg: "border-zinc-500/20" },
};

export function VerdictCard({ verdict }: { verdict: VerdictItem }) {
  const [expanded, setExpanded] = useState(false);
  const style = verdictStyles[verdict.verdict] || verdictStyles.NO_EVIDENCE;
  const evidenceText = verdict.evidence?.text || verdict.evidence_used;
  const evidenceSource = verdict.evidence?.source;
  const evidencePage = verdict.evidence?.page;
  const reasonText = verdict.reason || verdict.reasoning;

  return (
    <Card
      className={`cursor-pointer border-l-2 ${style.bg} p-4 transition-colors hover:bg-accent/50`}
      onClick={() => setExpanded(!expanded)}
    >
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-3">
          <span className={`text-lg ${style.color}`}>{style.icon}</span>
          <div>
            <div className="flex items-center gap-2">
              <span className={`text-xs font-semibold ${style.color}`}>{verdict.verdict.replace("_", " ")}</span>
              {verdict.contradiction_type && (
                <Badge variant="outline" className="text-[10px]">
                  {verdict.contradiction_type}
                </Badge>
              )}
            </div>
            <p className="mt-1 text-sm text-foreground">&ldquo;{verdict.claim}&rdquo;</p>
          </div>
        </div>
        <div className="text-right">
          <span className="text-xs text-muted-foreground">{Math.round(verdict.confidence * 100)}%</span>
          {typeof verdict.used_llm === "boolean" && (
            <p className="text-[10px] text-muted-foreground">
              {verdict.used_llm ? "via reasoning" : "via comparison"}
            </p>
          )}
        </div>
      </div>

      {expanded && (
        <div className="mt-4 space-y-3 pl-8">
          {evidenceText && (
            <div className="rounded-md bg-muted/50 p-3">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Evidence</p>
              <p className="mt-1 text-xs text-foreground">&ldquo;{evidenceText}&rdquo;</p>
              {evidenceSource ? (
                <p className="mt-2 text-[10px] text-muted-foreground">
                  {evidenceSource}
                  {evidencePage ? ` • Page ${evidencePage}` : ""}
                </p>
              ) : verdict.sources.length > 0 ? (
                <p className="mt-2 text-[10px] text-muted-foreground">
                  {verdict.sources.map((s, i) => (
                    <span key={i}>
                      {s.document_title}
                      {s.page ? ` \u2022 Page ${s.page}` : ""}
                      {s.paragraph ? ` \u2022 Paragraph ${s.paragraph}` : ""}
                      {i < verdict.sources.length - 1 ? " | " : ""}
                    </span>
                  ))}
                </p>
              ) : null}
            </div>
          )}

          {reasonText && (
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Reason</p>
              <p className="mt-1 text-xs text-muted-foreground">{reasonText}</p>
            </div>
          )}

          <div className="flex gap-4 text-[10px] text-muted-foreground">
            <span>Claim Type: {verdict.claim_type}</span>
            <span>Confidence: {Math.round(verdict.confidence * 100)}%</span>
          </div>
        </div>
      )}
    </Card>
  );
}
