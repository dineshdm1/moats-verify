# Moats Verify — Refactor Instructions

You are refactoring an existing document verification tool into a simplified, open source project. The goal is a clean, local-first tool that anyone can install and run in under a minute.

## Project Overview

**What it does:** Users upload documents, then paste AI-generated text to verify claims against those documents. The system extracts facts, retrieves relevant passages, compares them, and returns verdicts with citations.

**Design philosophy:**
- Simple over feature-rich
- Local-first (data stays on user's machine)
- User brings their own LLM/embedding provider
- No jargon, no hype
- Professional developer tool aesthetic

---

## Current State

The existing codebase has unnecessary complexity:
- Cloud storage connectors (S3, GCS, Azure) — remove
- External vector database support (Pinecone, Weaviate, Qdrant) — remove
- Neo4j knowledge graph — remove
- Complex sync logic — simplify

**Keep:**
- FastAPI backend
- Next.js frontend (simplify to 3 pages)
- ChromaDB (embedded mode only)
- SQLite for metadata
- LLM settings UI (user configures their provider)
- FlashRank reranker

---

## Target Architecture

### Directory Structure

```
moats-verify/
├── backend/
│   ├── main.py                 # FastAPI app entry point
│   ├── config.py               # Configuration management
│   ├── api/
│   │   ├── __init__.py
│   │   ├── verify.py           # POST /api/verify
│   │   ├── library.py          # Library CRUD, sync
│   │   └── settings.py         # LLM configuration
│   ├── core/
│   │   ├── __init__.py
│   │   ├── pipeline.py         # Main verification orchestrator
│   │   ├── segmenter.py        # Split text into claims
│   │   ├── extractor.py        # Extract structure (numbers, dates, entities)
│   │   ├── retrieval.py        # ChromaDB search + reranking
│   │   ├── comparator.py       # Comparison logic
│   │   └── verdict.py          # Generate final verdict
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── ingest.py           # Document processing
│   │   ├── chunker.py          # Text chunking
│   │   └── parsers.py          # PDF, DOCX, EPUB, TXT, MD parsers
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── database.py         # SQLite operations
│   │   └── vectors.py          # ChromaDB operations (embedded only)
│   └── llm/
│       ├── __init__.py
│       └── provider.py         # LLM abstraction (OpenAI, Anthropic, Ollama, etc.)
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx        # Verify page (home)
│   │   │   ├── library/
│   │   │   │   └── page.tsx    # Library management
│   │   │   └── settings/
│   │   │       └── page.tsx    # LLM settings
│   │   ├── components/
│   │   │   ├── VerifyInput.tsx
│   │   │   ├── VerifyResults.tsx
│   │   │   ├── ClaimCard.tsx
│   │   │   ├── LibraryList.tsx
│   │   │   ├── SourceUploader.tsx
│   │   │   └── SettingsForm.tsx
│   │   └── lib/
│   │       ├── api.ts          # Backend API client
│   │       └── types.ts        # TypeScript types
│   └── package.json
│
├── data/                       # Created at runtime
│   ├── moats.db               # SQLite database
│   └── vectors/               # ChromaDB storage
│
├── README.md
├── pyproject.toml
└── requirements.txt
```

### Files to Delete

Remove entirely:
- Any Neo4j related files and imports
- Any cloud storage connectors (S3, GCS, Azure)
- Any external vector DB support (Pinecone, Weaviate, Qdrant)
- Any knowledge graph / intelligence layer code
- Any user authentication code
- Unused test files and dependencies

---

## The Verification Algorithm

This is the core of the product. The verification pipeline uses structured extraction and comparison before falling back to LLM.

### Pipeline Overview

```
Input text
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  STEP 1: CLAIM SEGMENTATION                                  │
│  Split input into individual claims                          │
│  Method: Sentence splitting + filtering (remove questions,   │
│          commands, fragments)                                │
│  LLM: NO                                                     │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  STEP 2: STRUCTURE EXTRACTION                                │
│  For each claim, extract:                                    │
│  - Numeric values ($5M, 15%, "five million")                │
│  - Temporal values (Q3 2024, January, "last year")          │
│  - Entities (subject, object)                                │
│  - Polarity (positive/negative, negation words)             │
│  Method: spaCy NLP + regex patterns                          │
│  LLM: NO                                                     │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  STEP 3: EVIDENCE RETRIEVAL                                  │
│  For each claim:                                             │
│  - Embed claim text                                          │
│  - Query ChromaDB with library_id filter                    │
│  - Rerank results with FlashRank                            │
│  - Return top 5 passages                                     │
│  Method: Vector similarity + cross-encoder reranking         │
│  LLM: NO (uses embedding model only)                         │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  STEP 4: EVIDENCE EXTRACTION                                 │
│  For each evidence passage, extract same structure:          │
│  - Numeric values                                            │
│  - Temporal values                                           │
│  - Entities                                                  │
│  - Polarity                                                  │
│  Method: Same extractors as claim                            │
│  LLM: NO                                                     │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  STEP 5: COMPARISON                                          │
│  Compare claim structure against evidence structure          │
│  See detailed comparison logic below                         │
│  Method: Type-specific comparison algorithms                 │
│  LLM: NO                                                     │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  STEP 6: VERDICT                                             │
│  If comparison produced clear result → use it                │
│  If comparison inconclusive → fall back to LLM               │
│  Method: Decision logic + optional LLM                       │
│  LLM: ONLY IF NEEDED                                         │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
Output: Verdict + Evidence + Reasoning
```

---

### Step 2: Structure Extraction (core/extractor.py)

```python
"""
Extract structured information from text.
Uses spaCy for NLP + regex for specific patterns.
"""

import re
import spacy
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime

# Load spaCy model (user must have it installed)
nlp = spacy.load("en_core_web_sm")


@dataclass
class NumericValue:
    raw: str           # Original text: "$5M"
    value: float       # Normalized: 5000000
    unit: Optional[str]  # "USD", "percent", None
    confidence: float


@dataclass 
class TemporalValue:
    raw: str           # Original text: "Q3 2024"
    start: datetime    # 2024-07-01
    end: datetime      # 2024-09-30
    confidence: float


@dataclass
class ClaimStructure:
    text: str
    numeric_values: List[NumericValue]
    temporal_values: List[TemporalValue]
    subject: Optional[str]
    polarity: str  # "positive", "negative", "uncertain"
    negation_words: List[str]
    extraction_confidence: float


class StructureExtractor:
    """Extract structured information from text."""
    
    # Currency patterns
    CURRENCY_REGEX = r'([$€£])\s*(\d+(?:\.\d+)?)\s*([KkMmBb](?:illion)?)?'
    
    # Magnitude multipliers
    MAGNITUDE = {
        'k': 1e3, 'K': 1e3,
        'm': 1e6, 'M': 1e6, 'million': 1e6,
        'b': 1e9, 'B': 1e9, 'billion': 1e9,
    }
    
    # Quarter to date ranges
    QUARTERS = {
        1: ('01-01', '03-31'),
        2: ('04-01', '06-30'),
        3: ('07-01', '09-30'),
        4: ('10-01', '12-31'),
    }
    
    # Negation indicators
    NEGATION_WORDS = {
        'not', 'no', 'never', "n't", 'none', 'neither',
        'without', 'lack', 'fail', 'failed', 'unable',
        'deny', 'denied', 'refuse', 'refused'
    }
    
    def extract(self, text: str) -> ClaimStructure:
        """Extract all structured information from text."""
        doc = nlp(text)
        
        return ClaimStructure(
            text=text,
            numeric_values=self._extract_numbers(text),
            temporal_values=self._extract_temporal(text),
            subject=self._extract_subject(doc),
            polarity=self._extract_polarity(doc),
            negation_words=self._find_negations(doc),
            extraction_confidence=self._calculate_confidence(text, doc)
        )
    
    def _extract_numbers(self, text: str) -> List[NumericValue]:
        """Extract numeric values with units."""
        results = []
        
        # Currency: $5M, €10B, £100K
        for match in re.finditer(self.CURRENCY_REGEX, text):
            symbol, num, magnitude = match.groups()
            value = float(num)
            if magnitude:
                value *= self.MAGNITUDE.get(magnitude[0], 1)
            
            currency = {'$': 'USD', '€': 'EUR', '£': 'GBP'}.get(symbol, 'USD')
            results.append(NumericValue(
                raw=match.group(0),
                value=value,
                unit=currency,
                confidence=0.95
            ))
        
        # Percentages: 15%, 3.5%
        for match in re.finditer(r'(\d+(?:\.\d+)?)\s*%', text):
            results.append(NumericValue(
                raw=match.group(0),
                value=float(match.group(1)) / 100,
                unit='percent',
                confidence=0.98
            ))
        
        # Plain numbers with magnitude: 5 million, 10 billion
        for match in re.finditer(r'(\d+(?:\.\d+)?)\s*(million|billion|thousand)', text, re.I):
            value = float(match.group(1))
            mult = self.MAGNITUDE.get(match.group(2).lower(), 1)
            results.append(NumericValue(
                raw=match.group(0),
                value=value * mult,
                unit=None,
                confidence=0.90
            ))
        
        return results
    
    def _extract_temporal(self, text: str) -> List[TemporalValue]:
        """Extract temporal values and normalize to date ranges."""
        results = []
        
        # Quarters: Q1 2024, Q3 2023
        for match in re.finditer(r'Q([1-4])\s*(\d{4})', text):
            quarter = int(match.group(1))
            year = int(match.group(2))
            start_str, end_str = self.QUARTERS[quarter]
            
            results.append(TemporalValue(
                raw=match.group(0),
                start=datetime.strptime(f"{year}-{start_str}", "%Y-%m-%d"),
                end=datetime.strptime(f"{year}-{end_str}", "%Y-%m-%d"),
                confidence=0.95
            ))
        
        # Years: 2024, 2023
        for match in re.finditer(r'\b(20\d{2})\b', text):
            # Skip if already captured in quarter
            if re.search(rf'Q[1-4]\s*{match.group(1)}', text):
                continue
            year = int(match.group(1))
            results.append(TemporalValue(
                raw=match.group(0),
                start=datetime(year, 1, 1),
                end=datetime(year, 12, 31),
                confidence=0.85
            ))
        
        # Months: January 2024, March 2023
        months = {
            'january': 1, 'february': 2, 'march': 3, 'april': 4,
            'may': 5, 'june': 6, 'july': 7, 'august': 8,
            'september': 9, 'october': 10, 'november': 11, 'december': 12
        }
        for match in re.finditer(r'(january|february|march|april|may|june|july|august|september|october|november|december)\s*(\d{4})', text, re.I):
            month = months[match.group(1).lower()]
            year = int(match.group(2))
            # Last day of month
            if month == 12:
                end = datetime(year, 12, 31)
            else:
                end = datetime(year, month + 1, 1) - timedelta(days=1)
            
            results.append(TemporalValue(
                raw=match.group(0),
                start=datetime(year, month, 1),
                end=end,
                confidence=0.90
            ))
        
        return results
    
    def _extract_subject(self, doc) -> Optional[str]:
        """Extract the main subject of the sentence."""
        for token in doc:
            if token.dep_ == 'nsubj':
                # Get the full noun phrase
                for chunk in doc.noun_chunks:
                    if chunk.root == token:
                        return chunk.text
                return token.text
        return None
    
    def _extract_polarity(self, doc) -> str:
        """Determine if statement is positive, negative, or uncertain."""
        negations = self._find_negations(doc)
        
        # Odd number of negations = negative
        if len(negations) % 2 == 1:
            return "negative"
        elif negations:
            return "positive"  # Double negative = positive
        
        # Check for hedge words
        hedge_words = {'might', 'may', 'could', 'possibly', 'perhaps', 'likely'}
        if any(token.text.lower() in hedge_words for token in doc):
            return "uncertain"
        
        return "positive"
    
    def _find_negations(self, doc) -> List[str]:
        """Find all negation words in text."""
        negations = []
        for token in doc:
            if token.text.lower() in self.NEGATION_WORDS:
                negations.append(token.text)
            if token.dep_ == 'neg':
                negations.append(token.text)
        return negations
    
    def _calculate_confidence(self, text: str, doc) -> float:
        """Calculate overall extraction confidence."""
        # Base confidence
        conf = 0.7
        
        # Boost if we found structured data
        if re.search(self.CURRENCY_REGEX, text):
            conf += 0.1
        if re.search(r'Q[1-4]\s*\d{4}', text):
            conf += 0.1
        if any(token.dep_ == 'nsubj' for token in doc):
            conf += 0.05
        
        return min(conf, 0.95)
```

---

### Step 5: Comparison Logic (core/comparator.py)

```python
"""
Compare claim structure against evidence structure.
Returns comparison result with confidence.
"""

from dataclasses import dataclass
from typing import Optional, List
from enum import Enum


class ComparisonResult(Enum):
    MATCH = "match"
    CONTRADICTION = "contradiction"
    PARTIAL = "partial"
    NO_COMPARISON = "no_comparison"  # Can't compare, need LLM


@dataclass
class Comparison:
    result: ComparisonResult
    contradiction_type: Optional[str]  # "magnitude", "temporal", "negation"
    confidence: float
    explanation: str


class Comparator:
    """Compare claim and evidence structures."""
    
    def __init__(self, numeric_tolerance: float = 0.05):
        """
        Args:
            numeric_tolerance: Allowed difference for numeric match (default 5%)
        """
        self.numeric_tolerance = numeric_tolerance
    
    def compare(self, claim: 'ClaimStructure', evidence: 'ClaimStructure') -> Comparison:
        """
        Compare claim against evidence.
        Tries comparison in order of reliability:
        1. Numeric comparison (most reliable)
        2. Temporal comparison
        3. Polarity comparison
        4. Give up → need LLM
        """
        
        # Try numeric comparison first
        if claim.numeric_values and evidence.numeric_values:
            result = self._compare_numeric(claim, evidence)
            if result.result != ComparisonResult.NO_COMPARISON:
                return result
        
        # Try temporal comparison
        if claim.temporal_values and evidence.temporal_values:
            result = self._compare_temporal(claim, evidence)
            if result.result != ComparisonResult.NO_COMPARISON:
                return result
        
        # Try polarity comparison
        if claim.polarity != "uncertain" and evidence.polarity != "uncertain":
            result = self._compare_polarity(claim, evidence)
            if result.result != ComparisonResult.NO_COMPARISON:
                return result
        
        # Can't compare with algorithms, need LLM
        return Comparison(
            result=ComparisonResult.NO_COMPARISON,
            contradiction_type=None,
            confidence=0.0,
            explanation="Cannot compare structurally, requires reasoning"
        )
    
    def _compare_numeric(self, claim: 'ClaimStructure', evidence: 'ClaimStructure') -> Comparison:
        """Compare numeric values between claim and evidence."""
        
        # Get primary numeric values (first of each)
        claim_num = claim.numeric_values[0]
        evidence_num = evidence.numeric_values[0]
        
        # Must have same unit type for comparison
        if claim_num.unit != evidence_num.unit:
            # Different units - can't compare directly
            return Comparison(
                result=ComparisonResult.NO_COMPARISON,
                contradiction_type=None,
                confidence=0.0,
                explanation=f"Different units: {claim_num.unit} vs {evidence_num.unit}"
            )
        
        # Handle zero case
        if abs(evidence_num.value) < 1e-10:
            if abs(claim_num.value) < 1e-10:
                return Comparison(
                    result=ComparisonResult.MATCH,
                    contradiction_type=None,
                    confidence=0.95,
                    explanation="Both values are zero"
                )
            else:
                return Comparison(
                    result=ComparisonResult.CONTRADICTION,
                    contradiction_type="magnitude",
                    confidence=0.95,
                    explanation=f"Claim: {claim_num.raw}, Evidence: ~0"
                )
        
        # Calculate percentage difference
        diff = abs(claim_num.value - evidence_num.value) / abs(evidence_num.value)
        
        if diff <= self.numeric_tolerance:
            return Comparison(
                result=ComparisonResult.MATCH,
                contradiction_type=None,
                confidence=min(claim_num.confidence, evidence_num.confidence),
                explanation=f"Values match: {claim_num.raw} ≈ {evidence_num.raw} (within {self.numeric_tolerance*100:.0f}% tolerance)"
            )
        else:
            return Comparison(
                result=ComparisonResult.CONTRADICTION,
                contradiction_type="magnitude",
                confidence=min(claim_num.confidence, evidence_num.confidence) * 0.95,
                explanation=f"Values differ: claim says {claim_num.raw}, evidence says {evidence_num.raw} ({diff*100:.1f}% difference)"
            )
    
    def _compare_temporal(self, claim: 'ClaimStructure', evidence: 'ClaimStructure') -> Comparison:
        """Compare temporal values between claim and evidence."""
        
        claim_temp = claim.temporal_values[0]
        evidence_temp = evidence.temporal_values[0]
        
        # Check if periods overlap
        if claim_temp.start <= evidence_temp.end and evidence_temp.start <= claim_temp.end:
            # Periods overlap - check if they're the same
            start_diff = abs((claim_temp.start - evidence_temp.start).days)
            end_diff = abs((claim_temp.end - evidence_temp.end).days)
            
            if start_diff <= 7 and end_diff <= 7:
                return Comparison(
                    result=ComparisonResult.MATCH,
                    contradiction_type=None,
                    confidence=min(claim_temp.confidence, evidence_temp.confidence),
                    explanation=f"Time periods match: {claim_temp.raw} ≈ {evidence_temp.raw}"
                )
            else:
                return Comparison(
                    result=ComparisonResult.PARTIAL,
                    contradiction_type="temporal",
                    confidence=0.7,
                    explanation=f"Time periods overlap but differ: {claim_temp.raw} vs {evidence_temp.raw}"
                )
        else:
            # No overlap - contradiction
            return Comparison(
                result=ComparisonResult.CONTRADICTION,
                contradiction_type="temporal",
                confidence=min(claim_temp.confidence, evidence_temp.confidence) * 0.9,
                explanation=f"Time periods don't match: claim says {claim_temp.raw}, evidence says {evidence_temp.raw}"
            )
    
    def _compare_polarity(self, claim: 'ClaimStructure', evidence: 'ClaimStructure') -> Comparison:
        """Compare polarity (positive/negative) between claim and evidence."""
        
        if claim.polarity == evidence.polarity:
            return Comparison(
                result=ComparisonResult.MATCH,
                contradiction_type=None,
                confidence=0.75,  # Lower confidence for polarity-only match
                explanation="Statement polarity matches"
            )
        else:
            return Comparison(
                result=ComparisonResult.CONTRADICTION,
                contradiction_type="negation",
                confidence=0.85,
                explanation=f"Polarity mismatch: claim is {claim.polarity}, evidence is {evidence.polarity}"
            )
```

---

### Step 6: Verdict Generation (core/verdict.py)

```python
"""
Generate final verdict from comparison results.
Falls back to LLM when needed.
"""

from dataclasses import dataclass
from typing import List, Optional
from enum import Enum


class Verdict(Enum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    PARTIAL = "partial"
    NO_EVIDENCE = "no_evidence"


@dataclass
class ClaimVerdict:
    claim_text: str
    verdict: Verdict
    confidence: float
    evidence_text: str
    evidence_source: str  # filename
    evidence_page: Optional[int]
    reason: str  # Plain language explanation
    used_llm: bool  # Whether LLM was needed


class VerdictGenerator:
    """Generate verdicts from comparison results."""
    
    def __init__(self, llm_provider):
        self.llm = llm_provider
    
    def generate(
        self,
        claim: 'ClaimStructure',
        evidence_passages: List[dict],
        comparison: 'Comparison'
    ) -> ClaimVerdict:
        """Generate verdict for a claim."""
        
        if not evidence_passages:
            return ClaimVerdict(
                claim_text=claim.text,
                verdict=Verdict.NO_EVIDENCE,
                confidence=0.95,
                evidence_text="",
                evidence_source="",
                evidence_page=None,
                reason="No relevant passages found in your documents.",
                used_llm=False
            )
        
        best_evidence = evidence_passages[0]
        
        # If comparison was conclusive, use it
        if comparison.result == ComparisonResult.MATCH:
            return ClaimVerdict(
                claim_text=claim.text,
                verdict=Verdict.SUPPORTED,
                confidence=comparison.confidence,
                evidence_text=best_evidence['text'],
                evidence_source=best_evidence['source'],
                evidence_page=best_evidence.get('page'),
                reason=comparison.explanation,
                used_llm=False
            )
        
        elif comparison.result == ComparisonResult.CONTRADICTION:
            return ClaimVerdict(
                claim_text=claim.text,
                verdict=Verdict.CONTRADICTED,
                confidence=comparison.confidence,
                evidence_text=best_evidence['text'],
                evidence_source=best_evidence['source'],
                evidence_page=best_evidence.get('page'),
                reason=comparison.explanation,
                used_llm=False
            )
        
        elif comparison.result == ComparisonResult.PARTIAL:
            return ClaimVerdict(
                claim_text=claim.text,
                verdict=Verdict.PARTIAL,
                confidence=comparison.confidence,
                evidence_text=best_evidence['text'],
                evidence_source=best_evidence['source'],
                evidence_page=best_evidence.get('page'),
                reason=comparison.explanation,
                used_llm=False
            )
        
        else:
            # NO_COMPARISON - need LLM
            return self._llm_verdict(claim, evidence_passages)
    
    def _llm_verdict(self, claim: 'ClaimStructure', evidence_passages: List[dict]) -> ClaimVerdict:
        """Use LLM when structured comparison isn't possible."""
        
        evidence_text = "\n\n".join([
            f"[{p['source']}, page {p.get('page', '?')}]: {p['text']}"
            for p in evidence_passages[:3]
        ])
        
        prompt = f"""You are verifying a claim against source documents.

CLAIM: {claim.text}

EVIDENCE FROM DOCUMENTS:
{evidence_text}

Based on the evidence, determine:
1. Does the evidence SUPPORT, CONTRADICT, or PARTIALLY SUPPORT the claim?
2. If there's no relevant evidence, say NO_EVIDENCE.

Respond in this exact format:
VERDICT: [SUPPORTED/CONTRADICTED/PARTIAL/NO_EVIDENCE]
CONFIDENCE: [0.0-1.0]
REASON: [One sentence explaining why]
"""
        
        response = self.llm.complete(prompt)
        
        # Parse response
        verdict = Verdict.NO_EVIDENCE
        confidence = 0.5
        reason = "Could not determine from evidence."
        
        for line in response.strip().split('\n'):
            if line.startswith('VERDICT:'):
                v = line.replace('VERDICT:', '').strip().upper()
                if v == 'SUPPORTED':
                    verdict = Verdict.SUPPORTED
                elif v == 'CONTRADICTED':
                    verdict = Verdict.CONTRADICTED
                elif v == 'PARTIAL':
                    verdict = Verdict.PARTIAL
            elif line.startswith('CONFIDENCE:'):
                try:
                    confidence = float(line.replace('CONFIDENCE:', '').strip())
                except:
                    pass
            elif line.startswith('REASON:'):
                reason = line.replace('REASON:', '').strip()
        
        best_evidence = evidence_passages[0] if evidence_passages else {}
        
        return ClaimVerdict(
            claim_text=claim.text,
            verdict=verdict,
            confidence=confidence,
            evidence_text=best_evidence.get('text', ''),
            evidence_source=best_evidence.get('source', ''),
            evidence_page=best_evidence.get('page'),
            reason=reason,
            used_llm=True
        )
```

---

### Main Pipeline (core/pipeline.py)

```python
"""
Main verification pipeline.
Orchestrates: segmentation → extraction → retrieval → comparison → verdict
"""

from typing import List
from dataclasses import dataclass

from .segmenter import ClaimSegmenter
from .extractor import StructureExtractor
from .retrieval import EvidenceRetriever
from .comparator import Comparator
from .verdict import VerdictGenerator, ClaimVerdict, Verdict


@dataclass
class VerificationResult:
    trust_score: float
    claims: List[ClaimVerdict]
    total_claims: int
    supported_count: int
    contradicted_count: int
    no_evidence_count: int


class VerificationPipeline:
    """Main verification pipeline."""
    
    def __init__(
        self,
        llm_provider,
        vector_store,
        numeric_tolerance: float = 0.05
    ):
        self.segmenter = ClaimSegmenter()
        self.extractor = StructureExtractor()
        self.retriever = EvidenceRetriever(vector_store)
        self.comparator = Comparator(numeric_tolerance)
        self.verdict_gen = VerdictGenerator(llm_provider)
    
    def verify(self, text: str, library_id: str) -> VerificationResult:
        """
        Verify all claims in text against documents in library.
        
        Args:
            text: Text to verify (e.g., AI-generated content)
            library_id: ID of document library to check against
            
        Returns:
            VerificationResult with trust score and per-claim verdicts
        """
        
        # Step 1: Segment into claims
        claim_texts = self.segmenter.segment(text)
        
        verdicts = []
        
        for claim_text in claim_texts:
            # Step 2: Extract structure from claim
            claim_structure = self.extractor.extract(claim_text)
            
            # Step 3: Retrieve relevant evidence
            evidence_passages = self.retriever.retrieve(
                query=claim_text,
                library_id=library_id,
                top_k=5
            )
            
            if not evidence_passages:
                verdicts.append(ClaimVerdict(
                    claim_text=claim_text,
                    verdict=Verdict.NO_EVIDENCE,
                    confidence=0.95,
                    evidence_text="",
                    evidence_source="",
                    evidence_page=None,
                    reason="No relevant passages found in your documents.",
                    used_llm=False
                ))
                continue
            
            # Step 4: Extract structure from best evidence
            evidence_structure = self.extractor.extract(evidence_passages[0]['text'])
            
            # Step 5: Compare
            comparison = self.comparator.compare(claim_structure, evidence_structure)
            
            # Step 6: Generate verdict
            verdict = self.verdict_gen.generate(
                claim=claim_structure,
                evidence_passages=evidence_passages,
                comparison=comparison
            )
            
            verdicts.append(verdict)
        
        # Calculate trust score
        trust_score = self._calculate_trust_score(verdicts)
        
        return VerificationResult(
            trust_score=trust_score,
            claims=verdicts,
            total_claims=len(verdicts),
            supported_count=sum(1 for v in verdicts if v.verdict == Verdict.SUPPORTED),
            contradicted_count=sum(1 for v in verdicts if v.verdict == Verdict.CONTRADICTED),
            no_evidence_count=sum(1 for v in verdicts if v.verdict == Verdict.NO_EVIDENCE)
        )
    
    def _calculate_trust_score(self, verdicts: List[ClaimVerdict]) -> float:
        """Calculate weighted trust score."""
        weights = {
            Verdict.SUPPORTED: 1.0,
            Verdict.PARTIAL: 0.6,
            Verdict.CONTRADICTED: 0.0,
            Verdict.NO_EVIDENCE: None,  # Exclude from calculation
        }
        
        weighted_sum = 0.0
        total_weight = 0.0
        
        for v in verdicts:
            weight = weights.get(v.verdict)
            if weight is not None:
                weighted_sum += weight * v.confidence
                total_weight += v.confidence
        
        if total_weight == 0:
            return 0.0
        
        return weighted_sum / total_weight
```

---

## Frontend Specification

### Page 1: Verify (Home — `/`)

Main interface. Simple and focused.

```
┌────────────────────────────────────────────────────────────┐
│  moats verify                                              │
│                                                            │
│  Library: [Financial Reports ▼]                            │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐ │
│  │                                                      │ │
│  │  Paste text to verify against your documents...      │ │
│  │                                                      │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                            │
│                                            [Verify]        │
└────────────────────────────────────────────────────────────┘
```

**After verification:**

```
┌────────────────────────────────────────────────────────────┐
│  TRUST SCORE          CLAIMS           SOURCES             │
│     78%                  4             3 docs              │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  ┌────────────────────────────────────────────────────┐   │
│  │  ✓ SUPPORTED                              92%      │   │
│  │  "Revenue reached $4.8M in Q3 2024"                │   │
│  │                                                    │   │
│  │  Evidence:                                         │   │
│  │  "Q3 revenue was $4.8 million, up from..."        │   │
│  │  — Q3_Report.pdf, page 12                         │   │
│  │                                                    │   │
│  │  Values match: $4.8M ≈ $4.8 million               │   │
│  └────────────────────────────────────────────────────┘   │
│                                                            │
│  ┌────────────────────────────────────────────────────┐   │
│  │  ✗ CONTRADICTED                           87%      │   │
│  │  "The product launched in January"                 │   │
│  │                                                    │   │
│  │  Evidence:                                         │   │
│  │  "Launch was delayed to March 2024..."            │   │
│  │  — Product_Update.docx, page 3                    │   │
│  │                                                    │   │
│  │  Time periods don't match: January vs March       │   │
│  └────────────────────────────────────────────────────┘   │
│                                                            │
│                                      [Verify Another]      │
└────────────────────────────────────────────────────────────┘
```

**Verdict colors:**
- SUPPORTED: green
- CONTRADICTED: red  
- PARTIAL: yellow/orange
- NO EVIDENCE: gray

### Page 2: Library (`/library`)

```
┌────────────────────────────────────────────────────────────┐
│  moats verify  /  library                                  │
│                                                            │
│  Your Libraries                                [+ New]     │
│                                                            │
│  ┌────────────────────────────────────────────────────┐   │
│  │  📚 Financial Reports                    [Active]  │   │
│  │  /Users/me/Documents/reports                       │   │
│  │  23 documents · 1,847 chunks · Ready               │   │
│  │  [Sync]  [Delete]                                  │   │
│  └────────────────────────────────────────────────────┘   │
│                                                            │
│  Add Source                                                │
│  [📁 Select Folder]     [📄 Upload Files]                 │
│  Supported: PDF, DOCX, EPUB, TXT, MD                      │
└────────────────────────────────────────────────────────────┘
```

### Page 3: Settings (`/settings`)

Keep the existing LLM settings UI pattern. User configures:
- Provider (OpenAI, Anthropic, OpenRouter, Ollama, LM Studio, Custom)
- API Key
- Base URL
- Chat Model
- Embedding Model

No defaults — user must configure before first use.

---

## LLM Provider (llm/provider.py)

Use the existing provider abstraction. Support:
- OpenAI
- Anthropic
- OpenRouter
- Ollama
- LM Studio
- Custom endpoint (OpenAI-compatible)

User configures in Settings. No hardcoded defaults.

---

## Dependencies

```
# requirements.txt

# API
fastapi>=0.109.0
uvicorn>=0.27.0
python-multipart>=0.0.6

# Storage
chromadb>=0.4.22

# NLP
spacy>=3.7.0

# Document parsing
PyMuPDF>=1.23.0
python-docx>=1.1.0
ebooklib>=0.18

# Reranking
flashrank>=0.2.0

# LLM clients
httpx>=0.26.0
openai>=1.10.0
anthropic>=0.18.0

# CLI
click>=8.1.0

# Utils
pydantic>=2.5.0
```

Note: User must install spaCy model separately:
```bash
python -m spacy download en_core_web_sm
```

---

## README.md

```markdown
# Moats Verify

Verify AI-generated text against your documents.

## Quick Start

```bash
pip install moats-verify
python -m spacy download en_core_web_sm
moats serve
```

Open http://localhost:8080

## Setup

1. Go to **Settings** and configure your LLM provider
2. Go to **Library** and add your documents
3. Click **Sync** to process documents
4. Go to **Verify** and paste text to check

## How it works

For each claim in your text:

1. **Extract structure** — numbers, dates, entities
2. **Find evidence** — search your documents for relevant passages
3. **Compare** — check if values match, dates align, statements agree
4. **Verdict** — supported, contradicted, partial, or no evidence

When structured comparison isn't possible (e.g., causal claims), the system uses your configured LLM.

## Supported formats

PDF, DOCX, EPUB, TXT, Markdown

## LLM providers

Configure any of these in Settings:
- OpenAI
- Anthropic
- OpenRouter
- Ollama
- LM Studio
- Any OpenAI-compatible endpoint

## Local-first

- Documents stay on your machine
- Vector store runs locally (ChromaDB)
- You control which LLM to use

## License

MIT
```

---

## Tasks

### 1. Delete unnecessary code

- [ ] Remove Neo4j files and imports
- [ ] Remove cloud storage connectors
- [ ] Remove external vector DB support
- [ ] Remove knowledge graph / intelligence layer
- [ ] Remove authentication code
- [ ] Clean up unused dependencies

### 2. Implement core algorithm

- [ ] Create `core/segmenter.py` — claim segmentation
- [ ] Create `core/extractor.py` — structure extraction (per spec above)
- [ ] Create `core/comparator.py` — comparison logic (per spec above)
- [ ] Create `core/verdict.py` — verdict generation (per spec above)
- [ ] Create `core/pipeline.py` — main orchestrator (per spec above)
- [ ] Update `api/verify.py` to use new pipeline

### 3. Simplify frontend

- [ ] Reduce to 3 pages: Verify, Library, Settings
- [ ] Keep existing Settings UI for LLM configuration
- [ ] Remove cloud/external DB UI elements
- [ ] Update results display to show verdict reasons

### 4. Update documentation

- [ ] Write new README.md
- [ ] Create pyproject.toml for pip
- [ ] Delete old spec.md, architecture.md

### 5. Test

- [ ] Verify installation: `pip install -e .`
- [ ] Verify CLI: `moats serve`
- [ ] Test flow: create library → sync → verify
- [ ] Test numeric comparison
- [ ] Test temporal comparison
- [ ] Test LLM fallback

---

## Notes

- No hardcoded LLM defaults. User must configure.
- spaCy model (`en_core_web_sm`) must be installed separately.
- Keep dark theme UI.
- Plain language in verdicts — no technical jargon.
- Show when LLM was used vs structured comparison (optional, for transparency).
```
