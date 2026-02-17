"""Split input text into atomic claims."""

from __future__ import annotations

import re


class ClaimSegmenter:
    """Sentence-based claim segmentation with lightweight filtering."""

    _split_pattern = re.compile(r"(?<=[.!?])\s+|\n+")
    _command_starters = {
        "write",
        "summarize",
        "list",
        "explain",
        "show",
        "tell",
        "give",
        "create",
        "generate",
        "draft",
    }

    def segment(self, text: str) -> list[str]:
        """Return candidate factual claims from input text."""

        if not text or not text.strip():
            return []

        parts = [part.strip() for part in self._split_pattern.split(text) if part and part.strip()]
        claims: list[str] = []
        for part in parts:
            if self._is_claim_candidate(part):
                claims.append(part)
        return claims

    def _is_claim_candidate(self, sentence: str) -> bool:
        if len(sentence) < 12:
            return False
        if sentence.endswith("?"):
            return False

        tokens = sentence.split()
        if len(tokens) < 3:
            return False

        first = tokens[0].lower().strip("\"'`([{“”])")
        if first in self._command_starters:
            return False

        alnum_ratio = sum(ch.isalnum() for ch in sentence) / max(len(sentence), 1)
        if alnum_ratio < 0.5:
            return False

        return True
