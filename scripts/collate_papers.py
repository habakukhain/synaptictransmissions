#!/usr/bin/env python3
"""
Collate multiple paper draft files into a single post.

Usage:
    python collate_papers.py <folder_path> <output_file> [--title "Post Title"] [--category convergence]

Example:
    python collate_papers.py _drafts/synuclein_biomarkers _posts/2026-02-21-synuclein-biomarkers.md \
        --title "Synuclein Biomarkers" --category convergence
"""

import argparse
import os
import re
import yaml
from pathlib import Path
from datetime import date


def parse_front_matter(content: str) -> tuple[dict, str]:
    """Parse YAML front matter and body content from a markdown file."""
    if not content.startswith('---'):
        return {}, content

    # Find the closing ---
    end_match = re.search(r'\n---\s*\n', content[3:])
    if not end_match:
        return {}, content

    yaml_content = content[3:end_match.start() + 3]
    body = content[end_match.end() + 3:]

    try:
        front_matter = yaml.safe_load(yaml_content)
    except yaml.YAMLError:
        front_matter = {}

    return front_matter or {}, body.strip()


def generate_slug(front_matter: dict) -> str:
    """Generate a paper slug from author and year."""
    author = front_matter.get('paper_author', 'unknown').lower()
    year = str(front_matter.get('paper_year', date.today().year))
    return f"{author}-{year}"


def read_paper_file(filepath: Path) -> dict:
    """Read a paper draft file and return structured data."""
    content = filepath.read_text(encoding='utf-8')
    front_matter, body = parse_front_matter(content)

    slug = generate_slug(front_matter)

    paper = {
        'slug': slug,
        'title': front_matter.get('title', filepath.stem),
        'paper_author': front_matter.get('paper_author', ''),
        'paper_year': front_matter.get('paper_year', ''),
        'paper_journal': front_matter.get('paper_journal', ''),
        'paper_doi': front_matter.get('paper_doi', ''),
        'paper_et_al': front_matter.get('paper_et_al', False),
    }

    # Optional fields
    if front_matter.get('summary'):
        paper['summary'] = front_matter['summary']
    if front_matter.get('questions'):
        paper['questions'] = front_matter['questions']
    if front_matter.get('tags'):
        paper['tags'] = front_matter['tags']
    if front_matter.get('rating'):
        paper['rating'] = front_matter['rating']
    if front_matter.get('author_context'):
        paper['author_context'] = front_matter['author_context']

    # Content goes last for readability
    paper['content'] = body

    return paper


class LiteralStr(str):
    """String subclass that YAML will dump using literal block style."""
    pass


def literal_str_representer(dumper, data):
    """Custom representer for literal block strings."""
    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')


yaml.add_representer(LiteralStr, literal_str_representer)


def collate_papers(folder_path: Path, title: str, category: str, author: str) -> str:
    """Read all papers from folder and generate collated post content."""
    papers = []

    # Read all markdown files in the folder
    md_files = sorted(folder_path.glob('*.md'))

    if not md_files:
        raise ValueError(f"No markdown files found in {folder_path}")

    for filepath in md_files:
        paper = read_paper_file(filepath)
        # Convert content to literal string for better YAML formatting
        if 'content' in paper:
            paper['content'] = LiteralStr(paper['content'])
        if 'summary' in paper:
            paper['summary'] = LiteralStr(paper['summary'])
        papers.append(paper)

    # Build front matter
    front_matter = {
        'layout': 'collated',
        'title': title,
        'author': author,
        'categories': category,
        'papers': papers,
    }

    # Generate YAML with custom formatting for readability
    yaml_str = yaml.dump(
        front_matter,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )

    output = f"---\n{yaml_str}---\n"

    return output


def main():
    parser = argparse.ArgumentParser(description='Collate paper drafts into a single post')
    parser.add_argument('folder', type=Path, help='Folder containing paper draft files')
    parser.add_argument('output', type=Path, help='Output file path')
    parser.add_argument('--title', type=str, required=True, help='Title for the collated post')
    parser.add_argument('--category', type=str, default='convergence', help='Post category')
    parser.add_argument('--author', type=str, default='Habakuk Hain', help='Post author')

    args = parser.parse_args()

    if not args.folder.is_dir():
        print(f"Error: {args.folder} is not a directory")
        return 1

    try:
        content = collate_papers(args.folder, args.title, args.category, args.author)
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    # Ensure output directory exists
    args.output.parent.mkdir(parents=True, exist_ok=True)

    args.output.write_text(content, encoding='utf-8')
    print(f"Created: {args.output}")
    print(f"Papers collated: {len(list(args.folder.glob('*.md')))}")

    return 0


if __name__ == '__main__':
    exit(main())
