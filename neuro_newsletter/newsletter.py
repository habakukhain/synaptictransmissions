#!/usr/bin/env python3
"""
Neuro Newsletter Generator

Fetches recent neurology publications, analyzes them with Claude,
and generates a markdown newsletter for clinical neurologists.

Multi-pass system:
1. Fetch ALL papers from configured journals
2. Triage: Quick batch scoring to select top papers
3. Full text: Retrieve full text for selected papers
4. Analysis: In-depth Claude analysis of selected papers
5. Generate: Create markdown newsletter

Usage:
    python newsletter.py              # Full run
    python newsletter.py --dry-run    # Fetch papers without Claude analysis
    python newsletter.py --no-triage  # Skip triage, analyze all papers
    python newsletter.py --help       # Show help
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml

from pubmed_fetcher import PubMedFetcher
from full_text_fetcher import FullTextFetcher
from paper_analyzer import PaperAnalyzer
from newsletter_generator import NewsletterGenerator


def load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file."""
    config_file = Path(config_path)
    if not config_file.exists():
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)

    with open(config_file) as f:
        return yaml.safe_load(f)


def load_processed_papers(path: str = "processed_papers.json") -> set[str]:
    """Load set of already processed PMIDs."""
    processed_file = Path(path)
    if not processed_file.exists():
        return set()

    with open(processed_file) as f:
        data = json.load(f)
        return set(data.get("processed_pmids", []))


def save_processed_papers(pmids: set[str], path: str = "processed_papers.json"):
    """Save processed PMIDs to file."""
    data = {
        "processed_pmids": list(pmids),
        "last_run": datetime.now().isoformat()
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def get_api_key(config: dict) -> str:
    """Get Anthropic API key from environment or config."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        return api_key

    api_key = config.get("anthropic_api_key")
    if api_key:
        return api_key

    print("Error: ANTHROPIC_API_KEY not found.")
    print("Set it via environment variable or in config.yaml")
    sys.exit(1)


def fetch_full_texts(papers, config):
    """Fetch full texts for papers where available."""
    full_text_config = config.get("full_text", {})
    proxy_config = config.get("proxy", {})

    if not full_text_config.get("enabled", True):
        print("Full text fetching disabled in config")
        return {}

    unpaywall_email = full_text_config.get("unpaywall_email", "neuro_newsletter@example.com")

    fetcher = FullTextFetcher(
        proxy_config=proxy_config,
        unpaywall_email=unpaywall_email
    )

    full_texts = {}
    pmc_count = 0
    unpaywall_count = 0
    publisher_count = 0

    for i, paper in enumerate(papers, 1):
        print(f"  [{i}/{len(papers)}] {paper.title[:50]}...")

        result = fetcher.fetch_full_text(
            pmid=paper.pmid,
            doi=paper.doi,
            pmc_id=paper.pmc_id,
            abstract=paper.abstract or ""
        )

        if result.is_full_text and result.text:
            full_texts[paper.pmid] = result.text
            if result.source == "pmc":
                pmc_count += 1
            elif result.source == "unpaywall":
                unpaywall_count += 1
            elif result.source == "publisher":
                publisher_count += 1
            print(f"    -> Found full text via {result.source}")

    print(f"\nFull text retrieval summary:")
    print(f"  PMC (free): {pmc_count}")
    print(f"  Unpaywall (open access): {unpaywall_count}")
    print(f"  Publisher (via proxy): {publisher_count}")
    print(f"  Abstract only: {len(papers) - len(full_texts)}")

    return full_texts


def main():
    parser = argparse.ArgumentParser(
        description="Generate a neurology newsletter from recent publications"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch papers without Claude analysis (test mode)"
    )
    parser.add_argument(
        "--no-triage",
        action="store_true",
        help="Skip triage phase, process all papers (expensive)"
    )
    parser.add_argument(
        "--no-full-text",
        action="store_true",
        help="Skip full text fetching, use abstracts only"
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config file (default: config.yaml)"
    )
    parser.add_argument(
        "--reset-processed",
        action="store_true",
        help="Reset processed papers list (re-analyze all)"
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=None,
        help="Override number of papers to select after triage"
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=None,
        help="Maximum API budget in dollars (e.g., --budget 1.00)"
    )
    args = parser.parse_args()

    # Load config
    print("Loading configuration...")
    config = load_config(args.config)

    # Load or reset processed papers
    if args.reset_processed:
        processed_pmids = set()
        print("Processed papers list reset.")
    else:
        processed_pmids = load_processed_papers()
        print(f"Loaded {len(processed_pmids)} previously processed PMIDs")

    # Build journals dict for fetcher
    journals_config = config.get("journals", {})
    journals_by_category = {
        "neuromuscular": journals_config.get("neuromuscular", []),
        "neurovascular": journals_config.get("neurovascular", []),
        "general": journals_config.get("general", []),
        "subspecialty": journals_config.get("subspecialty", []),
        "neuroimmunology": journals_config.get("neuroimmunology", []),
        "pediatric": journals_config.get("pediatric", []),
        "neuropathology": journals_config.get("neuropathology", []),
        "neuroimaging": journals_config.get("neuroimaging", []),
        "neurocritical": journals_config.get("neurocritical", []),
        "reviews": journals_config.get("reviews", []),
        "adjacent_neurosurgery": journals_config.get("adjacent_neurosurgery", []),
        "adjacent_rheumatology": journals_config.get("adjacent_rheumatology", []),
        "mega_journals": journals_config.get("mega_journals", [])
    }

    mega_keywords = config.get("mega_journal_keywords", [])

    # Adjacent field keywords for filtering
    adjacent_keywords = {
        "adjacent_neurosurgery": config.get("adjacent_neurosurgery_keywords", []),
        "adjacent_rheumatology": config.get("adjacent_rheumatology_keywords", [])
    }
    lookback_days = config.get("lookback_days", 7)
    output_dir = config.get("output_dir", "./output")

    # Triage settings
    triage_config = config.get("triage", {})
    triage_top_n = args.top_n or triage_config.get("top_n", 50)
    triage_batch_size = triage_config.get("batch_size", 20)

    # Phase 1: Fetch ALL papers from PubMed (no limit)
    print("\n" + "=" * 50)
    print("PHASE 1: Fetching papers from PubMed")
    print("=" * 50)

    fetcher = PubMedFetcher(lookback_days=lookback_days)
    all_papers = fetcher.fetch_papers(
        journals_by_category=journals_by_category,
        mega_journal_keywords=mega_keywords,
        processed_pmids=processed_pmids,
        max_papers=9999,  # Effectively no limit
        adjacent_keywords=adjacent_keywords
    )

    if not all_papers:
        print("\nNo new papers found. Newsletter not generated.")
        return

    print(f"\nFound {len(all_papers)} new papers")

    # Show category breakdown
    by_category = {}
    for p in all_papers:
        by_category[p.source_category] = by_category.get(p.source_category, 0) + 1
    print("By category:")
    for cat, count in sorted(by_category.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}")

    pmc_available = sum(1 for p in all_papers if p.pmc_id)
    print(f"\n{pmc_available} have PMC IDs (free full text)")

    # Dry run mode
    if args.dry_run:
        print("\n" + "=" * 50)
        print("DRY RUN MODE - Skipping triage and analysis")
        print("=" * 50)

        print("\nSample papers that would be triaged:")
        for i, paper in enumerate(all_papers[:15], 1):
            pmc_tag = "[PMC]" if paper.pmc_id else ""
            print(f"  {i}. [{paper.source_category}]{pmc_tag} {paper.title[:60]}...")

        if len(all_papers) > 15:
            print(f"  ... and {len(all_papers) - 15} more papers")

        print(f"\nWould triage to select top {triage_top_n} papers")
        print("To run full analysis, remove --dry-run flag")
        return

    # Get API key for Claude operations
    api_key = get_api_key(config)
    analyzer = PaperAnalyzer(api_key=api_key)

    # Phase 2: Triage (unless --no-triage)
    triage_results = None  # Will be set if triage is performed
    if args.no_triage:
        print("\n" + "=" * 50)
        print("PHASE 2: Skipping triage (--no-triage)")
        print("=" * 50)
        selected_papers = all_papers
        print(f"Will analyze all {len(selected_papers)} papers (this may be expensive)")
    else:
        print("\n" + "=" * 50)
        print("PHASE 2: Triage - selecting top papers")
        print("=" * 50)

        selected_papers, triage_results = analyzer.triage_papers(
            all_papers,
            top_n=triage_top_n,
            batch_size=triage_batch_size
        )

    # Phase 3: Fetch full texts (only for selected papers)
    full_texts = {}
    if not args.no_full_text:
        print("\n" + "=" * 50)
        print("PHASE 3: Fetching full texts for selected papers")
        print("=" * 50)

        full_texts = fetch_full_texts(selected_papers, config)
    else:
        print("\n" + "=" * 50)
        print("PHASE 3: Skipping full text fetching (--no-full-text)")
        print("=" * 50)

    # Phase 4: Full analysis with Claude
    print("\n" + "=" * 50)
    print("PHASE 4: In-depth analysis with Claude")
    print("=" * 50)

    # Get budget from args or config
    budget_limit = args.budget or config.get("budget_limit")
    if budget_limit:
        print(f"Budget limit: ${budget_limit:.2f}")

    analyses = analyzer.analyze_papers(
        selected_papers,
        full_texts=full_texts,
        budget_limit=budget_limit,
        triage_results=triage_results
    )

    if not analyses:
        print("\nNo papers successfully analyzed. Newsletter not generated.")
        return

    # Phase 5: Generate newsletter
    print("\n" + "=" * 50)
    print("PHASE 5: Generating newsletter")
    print("=" * 50)

    generator = NewsletterGenerator(output_dir=output_dir)
    output_path = generator.generate(analyses, lookback_days=lookback_days)

    # Generate Jekyll blog drafts if enabled
    drafts_config = config.get("blog_drafts", {})
    if drafts_config.get("enabled", False):
        drafts_dir = drafts_config.get("drafts_dir", "../_drafts")
        author = drafts_config.get("author", "Habakuk Hain")
        min_importance = drafts_config.get("min_importance", 3)
        generator.generate_drafts(
            analyses,
            drafts_dir=drafts_dir,
            author=author,
            min_importance=min_importance
        )

    # Print summary
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"Papers fetched: {len(all_papers)}")
    print(f"Papers after triage: {len(selected_papers)}")
    print(f"Papers analyzed: {len(analyses)}")
    print()
    print(generator.generate_summary(analyses))

    # Print and save token usage log
    analyzer.token_log.print_summary()
    analyzer.token_log.save_to_file(output_dir)

    # Update processed papers (mark ALL fetched papers as processed)
    new_pmids = {paper.pmid for paper in all_papers}
    all_processed = processed_pmids | new_pmids
    save_processed_papers(all_processed)
    print(f"\nUpdated processed papers list ({len(all_processed)} total)")

    print(f"\nNewsletter saved to: {output_path}")
    print("\nDone!")


if __name__ == "__main__":
    main()
