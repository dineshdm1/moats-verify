"""Extract structured information from text.
Uses spaCy for NLP + regex for specific patterns.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
import re
from typing import Any, Optional


@dataclass
class NumericValue:
    raw: str
    value: float
    unit: Optional[str]
    confidence: float


@dataclass
class TemporalValue:
    raw: str
    start: datetime
    end: datetime
    confidence: float


@dataclass
class ClaimStructure:
    text: str
    numeric_values: list[NumericValue]
    temporal_values: list[TemporalValue]
    subject: Optional[str]
    polarity: str
    negation_words: list[str]
    extraction_confidence: float


@lru_cache(maxsize=1)
def _get_nlp() -> Any:
    import spacy

    try:
        return spacy.load("en_core_web_sm")
    except Exception:
        return spacy.blank("en")


class StructureExtractor:
    """Extract structured information from text."""

    CURRENCY_REGEX = r"([$€£])\s*(\d+(?:\.\d+)?)\s*([KkMmBb](?:illion)?)?"

    MAGNITUDE = {
        "k": 1e3,
        "K": 1e3,
        "m": 1e6,
        "M": 1e6,
        "million": 1e6,
        "b": 1e9,
        "B": 1e9,
        "billion": 1e9,
        "thousand": 1e3,
    }

    QUARTERS = {
        1: ("01-01", "03-31"),
        2: ("04-01", "06-30"),
        3: ("07-01", "09-30"),
        4: ("10-01", "12-31"),
    }

    NEGATION_WORDS = {
        "not",
        "no",
        "never",
        "n't",
        "none",
        "neither",
        "without",
        "lack",
        "fail",
        "failed",
        "unable",
        "deny",
        "denied",
        "refuse",
        "refused",
    }

    def extract(self, text: str) -> ClaimStructure:
        """Extract all structured information from text."""
        nlp = _get_nlp()
        doc = nlp(text)

        return ClaimStructure(
            text=text,
            numeric_values=self._extract_numbers(text),
            temporal_values=self._extract_temporal(text),
            subject=self._extract_subject(doc),
            polarity=self._extract_polarity(doc),
            negation_words=self._find_negations(doc),
            extraction_confidence=self._calculate_confidence(text, doc),
        )

    def _extract_numbers(self, text: str) -> list[NumericValue]:
        """Extract numeric values with units."""
        results: list[NumericValue] = []

        for match in re.finditer(self.CURRENCY_REGEX, text):
            symbol, num, magnitude = match.groups()
            value = float(num)
            if magnitude:
                value *= self.MAGNITUDE.get(magnitude[0], 1)

            currency = {"$": "USD", "€": "EUR", "£": "GBP"}.get(symbol, "USD")
            results.append(
                NumericValue(
                    raw=match.group(0),
                    value=value,
                    unit=currency,
                    confidence=0.95,
                )
            )

        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*%", text):
            results.append(
                NumericValue(
                    raw=match.group(0),
                    value=float(match.group(1)) / 100,
                    unit="percent",
                    confidence=0.98,
                )
            )

        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(million|billion|thousand)", text, re.I):
            value = float(match.group(1))
            mult = self.MAGNITUDE.get(match.group(2).lower(), 1)
            results.append(
                NumericValue(
                    raw=match.group(0),
                    value=value * mult,
                    unit=None,
                    confidence=0.90,
                )
            )

        return results

    def _extract_temporal(self, text: str) -> list[TemporalValue]:
        """Extract temporal values and normalize to date ranges."""
        results: list[TemporalValue] = []

        for match in re.finditer(r"Q([1-4])\s*(\d{4})", text):
            quarter = int(match.group(1))
            year = int(match.group(2))
            start_str, end_str = self.QUARTERS[quarter]

            results.append(
                TemporalValue(
                    raw=match.group(0),
                    start=datetime.strptime(f"{year}-{start_str}", "%Y-%m-%d"),
                    end=datetime.strptime(f"{year}-{end_str}", "%Y-%m-%d"),
                    confidence=0.95,
                )
            )

        for match in re.finditer(r"\b(20\d{2})\b", text):
            if re.search(rf"Q[1-4]\s*{match.group(1)}", text):
                continue
            year = int(match.group(1))
            results.append(
                TemporalValue(
                    raw=match.group(0),
                    start=datetime(year, 1, 1),
                    end=datetime(year, 12, 31),
                    confidence=0.85,
                )
            )

        months = {
            "january": 1,
            "february": 2,
            "march": 3,
            "april": 4,
            "may": 5,
            "june": 6,
            "july": 7,
            "august": 8,
            "september": 9,
            "october": 10,
            "november": 11,
            "december": 12,
        }
        for match in re.finditer(
            r"(january|february|march|april|may|june|july|august|september|october|november|december)\s*(\d{4})",
            text,
            re.I,
        ):
            month = months[match.group(1).lower()]
            year = int(match.group(2))
            if month == 12:
                end = datetime(year, 12, 31)
            else:
                end = datetime(year, month + 1, 1) - timedelta(days=1)

            results.append(
                TemporalValue(
                    raw=match.group(0),
                    start=datetime(year, month, 1),
                    end=end,
                    confidence=0.90,
                )
            )

        return results

    def _extract_subject(self, doc: Any) -> Optional[str]:
        """Extract the main subject of the sentence."""
        for token in doc:
            if token.dep_ == "nsubj":
                try:
                    for chunk in doc.noun_chunks:
                        if chunk.root == token:
                            return chunk.text
                except Exception:
                    return token.text
                return token.text
        return None

    def _extract_polarity(self, doc: Any) -> str:
        """Determine if statement is positive, negative, or uncertain."""
        negations = self._find_negations(doc)

        if len(negations) % 2 == 1:
            return "negative"
        if negations:
            return "positive"

        hedge_words = {"might", "may", "could", "possibly", "perhaps", "likely"}
        if any(token.text.lower() in hedge_words for token in doc):
            return "uncertain"

        return "positive"

    def _find_negations(self, doc: Any) -> list[str]:
        """Find all negation words in text."""
        negations: list[str] = []
        for token in doc:
            if token.text.lower() in self.NEGATION_WORDS:
                negations.append(token.text)
            if token.dep_ == "neg":
                negations.append(token.text)
        return negations

    def _calculate_confidence(self, text: str, doc: Any) -> float:
        """Calculate overall extraction confidence."""
        conf = 0.7

        if re.search(self.CURRENCY_REGEX, text):
            conf += 0.1
        if re.search(r"Q[1-4]\s*\d{4}", text):
            conf += 0.1
        if any(token.dep_ == "nsubj" for token in doc):
            conf += 0.05

        return min(conf, 0.95)
