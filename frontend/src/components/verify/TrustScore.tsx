"use client";

import { Card } from "@/components/ui/card";

interface TrustScoreProps {
  score: number;
  totalClaims: number;
  supported: number;
  partiallySUpported: number;
  contradicted: number;
  conflicting: number;
  noEvidence: number;
}

export function TrustScore({
  score,
  totalClaims,
  supported,
  partiallySUpported,
  contradicted,
  conflicting,
  noEvidence,
}: TrustScoreProps) {
  const allNoEvidence = noEvidence === totalClaims && totalClaims > 0;

  const scoreColor = allNoEvidence
    ? "text-zinc-400"
    : score >= 0.8
      ? "text-emerald-400"
      : score >= 0.5
        ? "text-amber-400"
        : "text-red-400";

  return (
    <Card className="p-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-wider text-muted-foreground">Trust Score</p>
          {allNoEvidence ? (
            <p className="text-2xl font-light text-zinc-400">Insufficient Evidence</p>
          ) : (
            <p className={`text-4xl font-light ${scoreColor}`}>{Math.round(score * 100)}%</p>
          )}
        </div>
        <div className="text-right">
          <p className="text-xs uppercase tracking-wider text-muted-foreground">Claims Analyzed</p>
          <p className="text-4xl font-light text-foreground">{totalClaims}</p>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-4 text-xs">
        {supported > 0 && (
          <span className="text-emerald-400">{"\u2713"} {supported} Supported</span>
        )}
        {partiallySUpported > 0 && (
          <span className="text-amber-400">{"\u25D0"} {partiallySUpported} Partial</span>
        )}
        {contradicted > 0 && (
          <span className="text-red-400">{"\u2717"} {contradicted} Contradicted</span>
        )}
        {conflicting > 0 && (
          <span className="text-orange-400">{"\u26A0"} {conflicting} Conflicting</span>
        )}
        {noEvidence > 0 && (
          <span className="text-zinc-400">? {noEvidence} No Evidence</span>
        )}
      </div>
    </Card>
  );
}
