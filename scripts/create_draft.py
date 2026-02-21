#!/usr/bin/env python3
"""
Create a draft blog post from a DOI or URL.

Usage:
    python create_draft.py                     # Interactive prompt
    python create_draft.py 10.1038/s41467-026-69289-0
    python create_draft.py https://doi.org/10.1038/s41467-026-69289-0
    python create_draft.py --doi 10.1038/s41467-026-69289-0
    python create_draft.py --url https://example.com/paper
"""

import argparse
import json
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path
from datetime import date
from typing import Optional, Dict


def extract_doi(input_str: str) -> Optional[str]:
    """Extract DOI from various input formats."""
    # Remove common URL prefixes
    input_str = input_str.strip()

    # Handle doi.org URLs
    if 'doi.org/' in input_str:
        match = re.search(r'doi\.org/(.+?)(?:\s|$)', input_str)
        if match:
            return match.group(1)

    # Handle direct DOI format (10.xxxx/...)
    match = re.search(r'(10\.\d{4,}/[^\s]+)', input_str)
    if match:
        return match.group(1)

    return None


def fetch_doi_metadata(doi: str) -> Optional[Dict]:
    """Fetch metadata from CrossRef API for a given DOI."""
    url = f"https://api.crossref.org/works/{doi}"

    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'SynapticTransmissions/1.0 (mailto:draft-creator@example.com)',
            'Accept': 'application/json'
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data.get('message', {})
    except urllib.error.HTTPError as e:
        print(f"Error fetching DOI metadata: HTTP {e.code}")
        return None
    except urllib.error.URLError as e:
        print(f"Error fetching DOI metadata: {e.reason}")
        return None


def parse_metadata(metadata: dict) -> dict:
    """Parse CrossRef metadata into our format."""
    # Get first author's last name
    authors = metadata.get('author', [])
    first_author = authors[0].get('family', 'Unknown') if authors else 'Unknown'
    has_et_al = len(authors) > 1

    # Get title
    titles = metadata.get('title', ['Untitled'])
    title = titles[0] if titles else 'Untitled'

    # Get journal
    container = metadata.get('container-title', [''])
    journal = container[0] if container else ''
    # Use short container title if available
    short_container = metadata.get('short-container-title', [])
    if short_container:
        journal = short_container[0]

    # Get year
    published = metadata.get('published', {})
    date_parts = published.get('date-parts', [[None]])
    year = date_parts[0][0] if date_parts and date_parts[0] else date.today().year

    # Get DOI
    doi = metadata.get('DOI', '')

    return {
        'title': title,
        'paper_author': first_author,
        'paper_et_al': has_et_al,
        'paper_journal': journal,
        'paper_year': str(year),
        'paper_doi': f"https://doi.org/{doi}" if doi else '',
    }


def slugify(text: str, max_length: int = 60) -> str:
    """Convert text to a URL-friendly slug."""
    # Convert to lowercase and replace spaces with hyphens
    slug = text.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')

    # Truncate to max length at word boundary
    if len(slug) > max_length:
        slug = slug[:max_length].rsplit('-', 1)[0]

    return slug


def generate_draft(paper_info: dict, output_dir: Path) -> Path:
    """Generate a draft markdown file."""
    slug = slugify(paper_info['title'])
    filename = f"{slug}.md"
    filepath = output_dir / filename

    # Handle duplicate filenames
    counter = 1
    while filepath.exists():
        filepath = output_dir / f"{slug}-{counter}.md"
        counter += 1

    content = f"""---
layout: post
title: "{paper_info['title']}"
author: "Habakuk Hain"
categories: transmission
tags: []
image:
rating:
paper_title: "{paper_info['title']}"
paper_author: "{paper_info['paper_author']}"
paper_journal: "{paper_info['paper_journal']}"
paper_year: "{paper_info['paper_year']}"
paper_doi: "{paper_info['paper_doi']}"
paper_et_al: {str(paper_info['paper_et_al']).lower()}
summary: ""
author_context: ""
---

**Problem**:

**Result**:

**Open Questions**:
"""

    filepath.write_text(content, encoding='utf-8')
    return filepath


def main():
    parser = argparse.ArgumentParser(description='Create a draft blog post from a DOI or URL')
    parser.add_argument('input', nargs='?', help='DOI or URL (optional, will prompt if not provided)')
    parser.add_argument('--doi', help='DOI of the paper')
    parser.add_argument('--url', help='URL of the paper')
    parser.add_argument('--output-dir', type=Path, default=Path('_drafts'),
                        help='Output directory for draft (default: _drafts)')

    args = parser.parse_args()

    # Determine input
    input_str = args.doi or args.url or args.input

    if not input_str:
        input_str = input("Enter DOI or URL: ").strip()
        if not input_str:
            print("No input provided.")
            return 1

    # Extract DOI
    doi = extract_doi(input_str)

    if not doi:
        print(f"Could not extract DOI from: {input_str}")
        print("Please provide a valid DOI (e.g., 10.1038/s41467-026-69289-0)")
        return 1

    print(f"Fetching metadata for DOI: {doi}")

    # Fetch metadata
    metadata = fetch_doi_metadata(doi)
    if not metadata:
        print("Failed to fetch metadata.")
        return 1

    # Parse metadata
    paper_info = parse_metadata(metadata)

    print(f"Found: {paper_info['paper_author']} et al. - {paper_info['title'][:60]}...")

    # Ensure output directory exists
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Generate draft
    filepath = generate_draft(paper_info, args.output_dir)

    print(f"Created draft: {filepath}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
