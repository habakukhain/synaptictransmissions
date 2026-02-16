"""
Paper Analyzer - Uses Claude API to analyze and rank neurology papers.

Supports a two-pass system:
1. Triage: Quick batch scoring of all papers based on title/abstract
2. Full analysis: In-depth analysis of top-scoring papers
"""

import time
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import anthropic

from pubmed_fetcher import Paper


@dataclass
class TokenUsage:
    """Token usage for a single API call."""
    phase: str  # "triage" or "analysis"
    input_tokens: int
    output_tokens: int
    input_chars: int  # Character count of input text
    paper_count: int  # Number of papers in this call
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    pmid: Optional[str] = None  # For analysis calls
    full_text_used: bool = False  # Whether full text was used


@dataclass
class TokenLog:
    """Aggregated token usage log."""
    entries: list[TokenUsage] = field(default_factory=list)

    def add(self, usage: TokenUsage):
        self.entries.append(usage)

    # Pricing per million tokens (Claude Sonnet)
    INPUT_PRICE_PER_M = 3.0
    OUTPUT_PRICE_PER_M = 15.0

    def get_current_cost(self) -> float:
        """Get current total cost in dollars."""
        total_input = sum(e.input_tokens for e in self.entries)
        total_output = sum(e.output_tokens for e in self.entries)
        return (total_input * self.INPUT_PRICE_PER_M + total_output * self.OUTPUT_PRICE_PER_M) / 1_000_000

    def get_summary(self) -> dict:
        """Get summary statistics by phase."""
        summary = {
            "triage": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "papers": 0, "input_chars": 0},
            "analysis": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "papers": 0, "input_chars": 0,
                        "full_text_papers": 0, "abstract_only_papers": 0},
            "total": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        }

        for entry in self.entries:
            phase = entry.phase
            summary[phase]["calls"] += 1
            summary[phase]["input_tokens"] += entry.input_tokens
            summary[phase]["output_tokens"] += entry.output_tokens
            summary[phase]["total_tokens"] += entry.input_tokens + entry.output_tokens
            summary[phase]["papers"] += entry.paper_count
            summary[phase]["input_chars"] += entry.input_chars

            if phase == "analysis":
                if entry.full_text_used:
                    summary["analysis"]["full_text_papers"] += 1
                else:
                    summary["analysis"]["abstract_only_papers"] += 1

            summary["total"]["calls"] += 1
            summary["total"]["input_tokens"] += entry.input_tokens
            summary["total"]["output_tokens"] += entry.output_tokens
            summary["total"]["total_tokens"] += entry.input_tokens + entry.output_tokens

        return summary

    def print_summary(self):
        """Print a formatted summary of token usage."""
        s = self.get_summary()

        print("\n" + "=" * 60)
        print("TOKEN USAGE SUMMARY")
        print("=" * 60)

        # Triage stats
        t = s["triage"]
        if t["calls"] > 0:
            print(f"\nTRIAGE PHASE:")
            print(f"  API calls: {t['calls']}")
            print(f"  Papers processed: {t['papers']}")
            print(f"  Input characters: {t['input_chars']:,}")
            print(f"  Input tokens: {t['input_tokens']:,}")
            print(f"  Output tokens: {t['output_tokens']:,}")
            print(f"  Total tokens: {t['total_tokens']:,}")
            if t['papers'] > 0:
                print(f"  Avg tokens/paper: {t['total_tokens'] // t['papers']}")

        # Analysis stats
        a = s["analysis"]
        if a["calls"] > 0:
            print(f"\nANALYSIS PHASE:")
            print(f"  API calls: {a['calls']}")
            print(f"  Papers analyzed: {a['papers']}")
            print(f"    - Full text: {a['full_text_papers']}")
            print(f"    - Abstract only: {a['abstract_only_papers']}")
            print(f"  Input characters: {a['input_chars']:,}")
            print(f"  Input tokens: {a['input_tokens']:,}")
            print(f"  Output tokens: {a['output_tokens']:,}")
            print(f"  Total tokens: {a['total_tokens']:,}")
            if a['papers'] > 0:
                print(f"  Avg tokens/paper: {a['total_tokens'] // a['papers']}")

        # Comparison
        total = s["total"]
        print(f"\nTOTAL:")
        print(f"  Total API calls: {total['calls']}")
        print(f"  Total input tokens: {total['input_tokens']:,}")
        print(f"  Total output tokens: {total['output_tokens']:,}")
        print(f"  Total tokens: {total['total_tokens']:,}")

        if t["total_tokens"] > 0 and a["total_tokens"] > 0:
            ratio = a["total_tokens"] / t["total_tokens"]
            print(f"\n  Analysis/Triage ratio: {ratio:.1f}x")
            triage_pct = (t["total_tokens"] / total["total_tokens"]) * 100
            analysis_pct = (a["total_tokens"] / total["total_tokens"]) * 100
            print(f"  Triage: {triage_pct:.1f}% of tokens")
            print(f"  Analysis: {analysis_pct:.1f}% of tokens")

        # Cost estimate (Claude Sonnet pricing: $3/M input, $15/M output)
        input_cost = total["input_tokens"] * 3 / 1_000_000
        output_cost = total["output_tokens"] * 15 / 1_000_000
        total_cost = input_cost + output_cost
        print(f"\nESTIMATED COST (Sonnet pricing):")
        print(f"  Input: ${input_cost:.4f}")
        print(f"  Output: ${output_cost:.4f}")
        print(f"  Total: ${total_cost:.4f}")

        print("=" * 60)

    def save_to_file(self, output_dir: str = "./output"):
        """Save detailed log to JSON file."""
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        filename = path / f"token_log_{timestamp}.json"

        data = {
            "timestamp": timestamp,
            "summary": self.get_summary(),
            "entries": [
                {
                    "phase": e.phase,
                    "input_tokens": e.input_tokens,
                    "output_tokens": e.output_tokens,
                    "input_chars": e.input_chars,
                    "paper_count": e.paper_count,
                    "timestamp": e.timestamp,
                    "pmid": e.pmid,
                    "full_text_used": e.full_text_used
                }
                for e in self.entries
            ]
        }

        with open(filename, "w") as f:
            json.dump(data, f, indent=2)

        print(f"\nToken log saved to: {filename}")
        return filename


@dataclass
class TriageResult:
    """Result from triage scoring."""
    paper: Paper
    score: int  # 1-10 priority score
    category: str  # evidence-based, pathophysiology, reviews, clinical-pearls
    reason: str  # Brief reason for score


@dataclass
class PaperAnalysis:
    """Analysis result for a single paper."""
    paper: Paper
    importance: str  # "+" to "+++++"
    importance_score: int  # 1-5 for sorting
    category: str  # evidence-based, pathophysiology, reviews, clinical-pearls
    keywords: list[str]  # 3 keywords for the paper
    summary: str
    author_context: str
    problem_addressed: str
    actual_result: str
    what_is_left_open: str
    full_text_used: bool  # Whether full text was available for analysis


ANALYSIS_PROMPT_ABSTRACT = """You are a clinical neurologist with subspecialty training in neuromuscular and neurovascular medicine who also has a solid grasp of basic research. You read papers looking for insights that would change how you think about disease mechanisms, diagnostics, or treatment—not just incremental confirmations of what's already known.

Analyze this research paper for a newsletter aimed at practicing ADULT neurologists. For pediatric papers, focus on aspects relevant to adult practice (genetic insights, mechanisms, transition of care).

Paper Information:
Title: {title}
Journal: {journal}
Authors: {authors}
Affiliations: {affiliations}

Abstract:
{abstract}

Analyze this paper and provide your assessment in the following JSON format:

{{
    "importance": "<+ to +++++>",
    "category": "<evidence-based|pathophysiology|reviews|clinical-pearls>",
    "keywords": ["<keyword1>", "<keyword2>", "<keyword3>"],
    "summary": "<2-3 sentence accessible summary for busy clinicians>",
    "author_context": "<Brief note on author expertise/institution, or 'Not specified' if unclear>",
    "problem_addressed": "<What gap in knowledge was addressed - one sentence>",
    "actual_result": "<What they actually found - one sentence>",
    "what_is_left_open": "<What remains to be determined - one sentence>"
}}

Importance Ranking Criteria:
- +++++ : Paradigm-shifting—changes how we fundamentally think about this disease/treatment
- ++++ : Major advance with clear clinical implications or novel mechanistic insight
- +++ : Solid contribution that practicing neurologists should know about
- ++ : Incremental evidence or confirmatory study
- + : Niche interest or preliminary data

{mega_journal_note}

Categories:
- evidence-based: Large multicenter RCTs, meta-analyses with direct clinical relevance, new guidelines
- pathophysiology: Novel insights into disease mechanisms, neuropathology, biomarkers (especially neuromuscular/neurovascular, but other fields if paradigm-shifting)
- reviews: Review articles, state-of-the-art summaries, educational pieces
- clinical-pearls: Instructive case reports, diagnostic pearls, practical clinical observations

Keywords: Provide exactly 3 specific keywords that capture the essence of this paper (e.g., "myasthenia gravis", "complement inhibition", "phase 3 trial").

Respond ONLY with valid JSON, no additional text."""


ANALYSIS_PROMPT_FULL_TEXT = """You are a clinical neurologist with subspecialty training in neuromuscular and neurovascular medicine who also has a solid grasp of basic research. You read papers looking for insights that would change how you think about disease mechanisms, diagnostics, or treatment—not just incremental confirmations of what's already known.

Analyze this research paper for a newsletter aimed at practicing ADULT neurologists. For pediatric papers, focus on aspects relevant to adult practice (genetic insights, mechanisms, transition of care).

Paper Information:
Title: {title}
Journal: {journal}
Authors: {authors}
Affiliations: {affiliations}

Full Text:
{full_text}

Based on the full text of this paper, provide your assessment in the following JSON format:

{{
    "importance": "<+ to +++++>",
    "category": "<evidence-based|pathophysiology|reviews|clinical-pearls>",
    "keywords": ["<keyword1>", "<keyword2>", "<keyword3>"],
    "summary": "<2-3 sentence accessible summary for busy clinicians>",
    "author_context": "<Brief note on author expertise/institution, or 'Not specified' if unclear>",
    "problem_addressed": "<What gap in knowledge was addressed - one sentence>",
    "actual_result": "<What they actually found - one sentence>",
    "what_is_left_open": "<What remains to be determined - one sentence>"
}}

Importance Ranking Criteria:
- +++++ : Paradigm-shifting—changes how we fundamentally think about this disease/treatment
- ++++ : Major advance with clear clinical implications or novel mechanistic insight
- +++ : Solid contribution that practicing neurologists should know about
- ++ : Incremental evidence or confirmatory study
- + : Niche interest or preliminary data

{mega_journal_note}

Categories:
- evidence-based: Large multicenter RCTs, meta-analyses with direct clinical relevance, new guidelines
- pathophysiology: Novel insights into disease mechanisms, neuropathology, biomarkers (especially neuromuscular/neurovascular, but other fields if paradigm-shifting)
- reviews: Review articles, state-of-the-art summaries, educational pieces
- clinical-pearls: Instructive case reports, diagnostic pearls, practical clinical observations

Keywords: Provide exactly 3 specific keywords that capture the essence of this paper (e.g., "myasthenia gravis", "complement inhibition", "phase 3 trial").

Respond ONLY with valid JSON, no additional text."""


TRIAGE_PROMPT = """You are a clinical neurologist with subspecialty training in neuromuscular and neurovascular medicine, and a solid grasp of basic research. You're triaging papers for a weekly newsletter aimed at ADULT neurologists, looking for work that would change how you think about disease, diagnostics, or treatment.

Score each paper from 1-10:
- 9-10: Paradigm-shifting or immediately practice-changing
- 7-8: Significant clinical implications or novel mechanistic insights
- 5-6: Solid contribution worth knowing about
- 3-4: Incremental or confirmatory
- 1-2: Minimal interest

Papers from Nature, Science, Cell, NEJM, Lancet, JAMA with neurology relevance should score at least 7.

For pathophysiology/biomarker research, weight neuromuscular and neurovascular topics more heavily, but include other fields if the findings are paradigm-shifting.

IMPORTANT: For pediatric neurology papers, only score highly (5+) if the findings have clear relevance for adult neurologists—e.g., genetic discoveries explaining adult-onset disease, mechanisms applicable across ages, or conditions that transition to adult care. Score low (1-3) papers focused purely on pediatric developmental issues, neonatal conditions, or child-specific treatments without adult implications.

Categorize each paper into ONE of these categories:
- "evidence-based": Large multicenter RCTs, meta-analyses (especially clinically relevant), new guidelines
- "pathophysiology": Novel disease mechanisms, neuropathology, biomarkers
- "reviews": Review articles, state-of-the-art summaries
- "clinical-pearls": Instructive case reports, diagnostic pearls, practical observations

For each paper, provide:
- score (1-10)
- category: one of the four categories above
- reason: 5-10 word explanation

Papers to triage:
{papers}

Respond with a JSON array, one object per paper in the same order:
[
  {{"pmid": "12345", "score": 8, "category": "evidence-based", "reason": "Large RCT shows efficacy in MG"}},
  ...
]

Respond ONLY with valid JSON array, no additional text."""


class PaperAnalyzer:
    """Analyzes papers using Claude API."""

    MEGA_JOURNALS = {
        "nature", "science", "cell", "new england journal of medicine",
        "n engl j med", "lancet", "jama", "nature medicine",
        "nature neuroscience", "nature communications", "science translational medicine"
    }

    # Maximum characters of full text to send (to manage token usage)
    MAX_FULL_TEXT_CHARS = 50000

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-20250514"):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.token_log = TokenLog()

    def _is_mega_journal(self, journal: str) -> bool:
        """Check if journal is a mega-journal."""
        return journal.lower() in self.MEGA_JOURNALS

    def _parse_importance(self, importance_str: str) -> int:
        """Convert importance string to numeric score."""
        return importance_str.count("+")

    def _format_paper_for_triage(self, paper: Paper, index: int) -> str:
        """Format a paper for triage batch processing."""
        # Truncate abstract for triage (first ~300 chars is usually enough)
        abstract_preview = (paper.abstract or "No abstract")[:300]
        if len(paper.abstract or "") > 300:
            abstract_preview += "..."

        return f"""[{index}] PMID: {paper.pmid}
Journal: {paper.journal}
Title: {paper.title}
Abstract: {abstract_preview}
"""

    def triage_batch(self, papers: list[Paper]) -> list[TriageResult]:
        """
        Triage a batch of papers (max ~20 at a time for context limits).

        Args:
            papers: List of papers to triage

        Returns:
            List of TriageResult objects
        """
        if not papers:
            return []

        # Format papers for the prompt
        papers_text = "\n".join(
            self._format_paper_for_triage(p, i+1)
            for i, p in enumerate(papers)
        )

        prompt = TRIAGE_PROMPT.format(papers=papers_text)
        input_chars = len(prompt)

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}]
            )

            # Log token usage
            self.token_log.add(TokenUsage(
                phase="triage",
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                input_chars=input_chars,
                paper_count=len(papers)
            ))

            response_text = response.content[0].text.strip()

            # Handle markdown code blocks
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                # Find the closing ```
                end_idx = len(lines) - 1
                for i, line in enumerate(lines[1:], 1):
                    if line.startswith("```"):
                        end_idx = i
                        break
                response_text = "\n".join(lines[1:end_idx])

            scores_data = json.loads(response_text)

            # Build results, matching by PMID
            pmid_to_paper = {p.pmid: p for p in papers}
            results = []

            for item in scores_data:
                pmid = str(item.get("pmid", ""))
                if pmid in pmid_to_paper:
                    results.append(TriageResult(
                        paper=pmid_to_paper[pmid],
                        score=int(item.get("score", 5)),
                        category=item.get("category", "general"),
                        reason=item.get("reason", "")
                    ))

            return results

        except (json.JSONDecodeError, anthropic.APIError) as e:
            print(f"    Warning: Triage batch failed: {e}")
            # Return default scores so we don't lose papers
            return [
                TriageResult(paper=p, score=5, category="general", reason="Triage failed")
                for p in papers
            ]

    # Target category distribution for balanced selection
    CATEGORY_TARGETS = {
        "evidence-based": 0.30,  # 30% - trials, meta-analyses, guidelines
        "pathophysiology": 0.35,  # 35% - mechanisms, biomarkers
        "reviews": 0.15,  # 15% - review articles
        "clinical-pearls": 0.20  # 20% - case reports, clinical observations
    }

    def triage_papers(
        self,
        papers: list[Paper],
        top_n: int = 50,
        batch_size: int = 20,
        rate_limit_delay: float = 0.5
    ) -> tuple[list[Paper], list[TriageResult]]:
        """
        Triage all papers and return the top N for full analysis, balanced across categories.

        Args:
            papers: All papers to triage
            top_n: Number of top papers to return
            batch_size: Papers per API call
            rate_limit_delay: Delay between API calls

        Returns:
            Tuple of (list of top N papers, list of their TriageResults)
        """
        print(f"\nTriaging {len(papers)} papers to select top {top_n}...")

        all_results: list[TriageResult] = []

        # Process in batches
        num_batches = (len(papers) + batch_size - 1) // batch_size

        for i in range(0, len(papers), batch_size):
            batch = papers[i:i + batch_size]
            batch_num = i // batch_size + 1
            print(f"  Batch {batch_num}/{num_batches} ({len(batch)} papers)...")

            results = self.triage_batch(batch)
            all_results.extend(results)

            if i + batch_size < len(papers):
                time.sleep(rate_limit_delay)

        # Print triage summary
        score_dist = {}
        cat_dist = {}
        for r in all_results:
            score_dist[r.score] = score_dist.get(r.score, 0) + 1
            cat_dist[r.category] = cat_dist.get(r.category, 0) + 1

        print(f"\nTriage complete. Score distribution:")
        for score in sorted(score_dist.keys(), reverse=True):
            print(f"  Score {score}: {score_dist[score]} papers")

        print(f"\nCategory distribution (all papers):")
        for cat, count in sorted(cat_dist.items(), key=lambda x: -x[1]):
            print(f"  {cat}: {count}")

        # Balanced selection: ensure each category is represented
        # Sort each category by score
        by_category: dict[str, list[TriageResult]] = {}
        for r in all_results:
            cat = r.category
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(r)

        for cat in by_category:
            by_category[cat].sort(key=lambda r: -r.score)

        # Allocate slots based on target distribution
        selected: list[TriageResult] = []
        remaining_slots = top_n

        # First pass: give each category its target allocation (or all available)
        for cat, target_pct in self.CATEGORY_TARGETS.items():
            target_count = max(1, int(top_n * target_pct))  # At least 1 per category
            available = by_category.get(cat, [])
            to_take = min(target_count, len(available))
            selected.extend(available[:to_take])
            # Remove selected from available pool
            by_category[cat] = available[to_take:]
            remaining_slots -= to_take

        # Second pass: fill remaining slots with highest-scoring papers from any category
        all_remaining = []
        for cat_papers in by_category.values():
            all_remaining.extend(cat_papers)
        all_remaining.sort(key=lambda r: -r.score)

        if remaining_slots > 0:
            selected.extend(all_remaining[:remaining_slots])

        # Sort final selection by score for display
        selected.sort(key=lambda r: -r.score)

        # Limit to top_n (in case we overallocated)
        selected = selected[:top_n]
        top_papers = [r.paper for r in selected]

        # Final category distribution
        final_cat_dist = {}
        for r in selected:
            final_cat_dist[r.category] = final_cat_dist.get(r.category, 0) + 1

        print(f"\nSelected {len(top_papers)} papers for full analysis (balanced):")
        for cat in ["evidence-based", "pathophysiology", "reviews", "clinical-pearls"]:
            count = final_cat_dist.get(cat, 0)
            target = int(top_n * self.CATEGORY_TARGETS.get(cat, 0))
            print(f"  {cat}: {count} (target: {target})")

        if selected:
            print(f"  Score range: {selected[-1].score} - {selected[0].score}")

        # Show top papers
        print(f"\nTop papers selected:")
        for i, r in enumerate(selected[:10], 1):
            print(f"  {i}. [Score {r.score}] [{r.category}] {r.paper.title[:50]}...")
            print(f"      Reason: {r.reason}")

        if len(selected) > 10:
            print(f"  ... and {len(selected) - 10} more")

        return top_papers, selected

    def _truncate_text(self, text: str, max_chars: int) -> str:
        """Truncate text to max characters, trying to break at sentence boundaries."""
        if len(text) <= max_chars:
            return text

        truncated = text[:max_chars]
        # Try to break at last sentence
        last_period = truncated.rfind(". ")
        if last_period > max_chars * 0.8:
            truncated = truncated[:last_period + 1]

        return truncated + "\n\n[Text truncated for length]"

    def analyze_paper(
        self,
        paper: Paper,
        full_text: Optional[str] = None
    ) -> Optional[PaperAnalysis]:
        """
        Analyze a single paper using Claude.

        Args:
            paper: Paper object with metadata
            full_text: Optional full text content (if None, uses abstract)

        Returns:
            PaperAnalysis object or None if analysis failed
        """
        # Determine if we're using full text
        use_full_text = full_text is not None and len(full_text) > len(paper.abstract or "")

        # Build the prompt
        mega_note = ""
        if self._is_mega_journal(paper.journal):
            mega_note = "Note: This paper is from a high-impact mega-journal. Neurology-related papers from these journals should receive at least +++ importance."

        authors_str = ", ".join(paper.authors[:5])
        if len(paper.authors) > 5:
            authors_str += f" et al. ({len(paper.authors)} authors)"

        affiliations_str = "; ".join(paper.affiliations) if paper.affiliations else "Not specified"

        if use_full_text:
            # Truncate full text if needed
            truncated_text = self._truncate_text(full_text, self.MAX_FULL_TEXT_CHARS)
            prompt = ANALYSIS_PROMPT_FULL_TEXT.format(
                title=paper.title,
                journal=paper.journal,
                authors=authors_str,
                affiliations=affiliations_str,
                full_text=truncated_text,
                mega_journal_note=mega_note
            )
        else:
            prompt = ANALYSIS_PROMPT_ABSTRACT.format(
                title=paper.title,
                journal=paper.journal,
                authors=authors_str,
                affiliations=affiliations_str,
                abstract=paper.abstract or "Abstract not available",
                mega_journal_note=mega_note
            )

        input_chars = len(prompt)

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )

            # Log token usage
            self.token_log.add(TokenUsage(
                phase="analysis",
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                input_chars=input_chars,
                paper_count=1,
                pmid=paper.pmid,
                full_text_used=use_full_text
            ))

            # Parse JSON response
            response_text = response.content[0].text.strip()

            # Handle potential markdown code blocks
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1])

            analysis_data = json.loads(response_text)

            importance = analysis_data.get("importance", "++")
            importance_score = self._parse_importance(importance)

            # Enforce minimum importance for mega-journals
            if self._is_mega_journal(paper.journal) and importance_score < 3:
                importance = "+++"
                importance_score = 3

            return PaperAnalysis(
                paper=paper,
                importance=importance,
                importance_score=importance_score,
                category=analysis_data.get("category", "pathophysiology"),
                keywords=analysis_data.get("keywords", []),
                summary=analysis_data.get("summary", ""),
                author_context=analysis_data.get("author_context", "Not specified"),
                problem_addressed=analysis_data.get("problem_addressed", ""),
                actual_result=analysis_data.get("actual_result", ""),
                what_is_left_open=analysis_data.get("what_is_left_open", ""),
                full_text_used=use_full_text
            )

        except json.JSONDecodeError as e:
            print(f"  Warning: Failed to parse Claude response for PMID {paper.pmid}: {e}")
            return None
        except anthropic.APIError as e:
            print(f"  Warning: API error for PMID {paper.pmid}: {e}")
            return None

    # Estimated tokens per analysis (for budget planning)
    EST_TOKENS_FULL_TEXT = 15000  # ~50k chars input + output
    EST_TOKENS_ABSTRACT = 800     # ~2k chars input + output
    EST_OUTPUT_TOKENS = 350       # Typical output size

    def analyze_papers(
        self,
        papers: list[Paper],
        full_texts: Optional[dict[str, str]] = None,
        rate_limit_delay: float = 0.5,
        budget_limit: Optional[float] = None,
        triage_results: Optional[list] = None
    ) -> list[PaperAnalysis]:
        """
        Analyze multiple papers with optional budget limiting.

        Budget strategy (when budget_limit is set):
        1. Papers are analyzed in priority order (highest triage scores first)
        2. Full text analysis is used while budget allows
        3. When budget gets tight, switches to abstract-only mode
        4. When budget is exhausted, remaining papers are skipped

        Args:
            papers: List of papers to analyze
            full_texts: Optional dict mapping PMID to full text content
            rate_limit_delay: Delay between API calls in seconds
            budget_limit: Maximum budget in dollars (None = unlimited)
            triage_results: Optional list of TriageResults for priority ordering

        Returns:
            List of PaperAnalysis objects, sorted by category then importance
        """
        analyses = []
        full_texts = full_texts or {}

        # Sort papers by triage score if available (highest first)
        if triage_results:
            pmid_to_score = {r.paper.pmid: r.score for r in triage_results}
            papers = sorted(papers, key=lambda p: -pmid_to_score.get(p.pmid, 0))

        full_text_count = sum(1 for p in papers if p.pmid in full_texts)
        print(f"\nAnalyzing {len(papers)} papers with Claude...")
        print(f"  Full text available for {full_text_count} papers")

        if budget_limit:
            print(f"  Budget limit: ${budget_limit:.2f}")

        # Budget tracking
        force_abstract_only = False
        skipped_count = 0

        for i, paper in enumerate(papers, 1):
            # Check budget before each analysis
            if budget_limit:
                current_cost = self.token_log.get_current_cost()
                remaining_budget = budget_limit - current_cost
                remaining_papers = len(papers) - i + 1

                # Estimate cost for remaining papers
                # Reserve ~$0.01 per paper for abstract-only as minimum
                min_cost_per_paper = self.EST_TOKENS_ABSTRACT * (
                    TokenLog.INPUT_PRICE_PER_M + TokenLog.OUTPUT_PRICE_PER_M * 0.3
                ) / 1_000_000

                if remaining_budget <= 0:
                    print(f"  [{i}/{len(papers)}] SKIPPED - Budget exhausted (${current_cost:.3f} spent)")
                    skipped_count += 1
                    continue
                elif remaining_budget < min_cost_per_paper * remaining_papers:
                    # Not enough budget even for abstract-only on all remaining papers
                    # Analyze what we can
                    if remaining_budget < min_cost_per_paper:
                        print(f"  [{i}/{len(papers)}] SKIPPED - Budget exhausted (${current_cost:.3f} spent)")
                        skipped_count += 1
                        continue
                    force_abstract_only = True
                elif not force_abstract_only:
                    # Check if we should switch to abstract-only to preserve budget
                    # Switch when we can't afford full-text for all remaining papers
                    full_text_cost = self.EST_TOKENS_FULL_TEXT * (
                        TokenLog.INPUT_PRICE_PER_M + TokenLog.OUTPUT_PRICE_PER_M * 0.02
                    ) / 1_000_000
                    if remaining_budget < full_text_cost * remaining_papers:
                        force_abstract_only = True
                        print(f"  ** Switching to abstract-only mode to stay within budget **")

            # Determine whether to use full text
            full_text = full_texts.get(paper.pmid)
            if force_abstract_only:
                full_text = None  # Force abstract-only

            text_indicator = "[FULL]" if full_text else "[ABS]"
            if budget_limit:
                cost_str = f" (${self.token_log.get_current_cost():.3f})"
            else:
                cost_str = ""
            print(f"  [{i}/{len(papers)}] {text_indicator} {paper.title[:50]}...{cost_str}")

            analysis = self.analyze_paper(paper, full_text=full_text)
            if analysis:
                analyses.append(analysis)

            # Rate limiting
            if i < len(papers):
                time.sleep(rate_limit_delay)

        # Sort by category (for grouping), then by importance (descending)
        category_order = {"evidence-based": 0, "pathophysiology": 1, "reviews": 2, "clinical-pearls": 3}
        analyses.sort(
            key=lambda a: (category_order.get(a.category, 4), -a.importance_score)
        )

        print(f"\nSuccessfully analyzed {len(analyses)} papers")
        full_text_analyzed = sum(1 for a in analyses if a.full_text_used)
        print(f"  {full_text_analyzed} with full text, {len(analyses) - full_text_analyzed} with abstract only")
        if skipped_count > 0:
            print(f"  {skipped_count} papers skipped due to budget limit")

        return analyses
