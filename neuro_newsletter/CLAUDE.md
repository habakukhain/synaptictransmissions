# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Automated neurology newsletter generator that fetches recent publications from PubMed, triages them with AI, and generates curated markdown newsletters for clinical neurologists. Specializes in neuromuscular disorders, neurovascular diseases, and general neurology.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Full run (requires ANTHROPIC_API_KEY environment variable)
python newsletter.py

# Useful flags
python newsletter.py --dry-run          # Fetch papers without Claude analysis
python newsletter.py --no-triage        # Skip triage, analyze all papers
python newsletter.py --no-full-text     # Skip full text fetching
python newsletter.py --reset-processed  # Clear processed papers list
python newsletter.py --budget 1.00      # Limit API spending to $1
```

## Architecture

Five-phase pipeline orchestrated by `newsletter.py`:

1. **PubMed Fetching** (`pubmed_fetcher.py`): Queries NCBI E-utilities API for papers from 25+ configured neurology journals plus mega-journals (Nature, NEJM, etc.) filtered by neuro keywords

2. **Triage** (`paper_analyzer.py`): Batch scores papers 1-10 using Claude, categorizes into evidence-based/pathophysiology/reviews/clinical-pearls, selects balanced top N (default 20)

3. **Full Text Fetching** (`full_text_fetcher.py`): Attempts retrieval from PMC, Unpaywall, or publisher proxy (in priority order)

4. **Analysis** (`paper_analyzer.py`): In-depth Claude analysis generating importance ratings (+ to +++++), summaries, 3 keywords per paper. Supports budget limiting with graceful degradation (switches to abstract-only, then stops).

5. **Newsletter Generation** (`newsletter_generator.py`): Creates markdown newsletters grouped by category (Evidence-Based Medicine, Pathophysiology & Mechanisms, Reviews, Clinical Pearls), ordered by importance within each section

6. **Blog Drafts** (`newsletter_generator.py`): Generates individual Jekyll-formatted draft posts in `_drafts/` for papers above a configurable importance threshold

## Key Configuration

- `config.yaml`: Journal lists, mega-journal keywords, lookback days, triage settings, budget limit, proxy config, blog drafts settings
- `processed_papers.json`: Tracks previously processed PMIDs to avoid re-analysis

## Blog Integration

When `blog_drafts.enabled` is true in config.yaml, the generator creates individual Jekyll draft posts:
- Output: `../../_drafts/` (relative to output_dir, i.e., the blog's `_drafts/` folder)
- Only papers with importance >= `min_importance` (default 3, which is rating 6+ on 0-10 scale)
- Each draft includes: front matter (title, author, tags, rating), citation, summary, and critical evaluation

## Budget Limiting

Set `budget_limit` in config.yaml or use `--budget` flag. When budget is constrained:
1. Triage always completes (cheap)
2. Analysis processes papers in priority order (highest triage scores first)
3. Switches to abstract-only when budget gets tight
4. Stops when budget exhausted

Token usage summary and detailed JSON log saved to `output/token_log_*.json` after each run.

## API Rate Limits

- NCBI: 0.35s between requests
- Unpaywall: 0.1s between requests
- Claude: 0.5s between analysis calls

## Core Data Flow

`Paper` dataclass flows through pipeline: PubMedFetcher creates them, FullTextFetcher enriches with text, PaperAnalyzer produces `TriageResult` and `PaperAnalysis`, NewsletterGenerator outputs markdown.
