#!/usr/bin/env python3
"""
Process new posts in _posts/ that don't have proper date formatting.

This script:
1. Finds posts without a date in the filename (YYYY-MM-DD prefix)
2. Renames them with the current date prefix
3. Adds/updates the date field in the front matter
"""

import os
import re
from datetime import datetime
from pathlib import Path

import yaml


# Regex to match Jekyll date prefix: YYYY-MM-DD-
DATE_PREFIX_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}-')

# Regex to parse front matter
FRONT_MATTER_PATTERN = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)


def has_date_prefix(filename: str) -> bool:
    """Check if filename starts with YYYY-MM-DD- pattern."""
    return bool(DATE_PREFIX_PATTERN.match(filename))


def parse_front_matter(content: str) -> tuple[dict, str]:
    """Parse YAML front matter from markdown content.

    Returns:
        Tuple of (front_matter_dict, body_content)
    """
    match = FRONT_MATTER_PATTERN.match(content)
    if not match:
        return {}, content

    try:
        front_matter = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}, content

    body = content[match.end():]
    return front_matter, body


def serialize_front_matter(front_matter: dict, body: str) -> str:
    """Serialize front matter and body back to markdown."""
    # Custom serialization to preserve field order and formatting
    lines = ['---']

    # Define preferred field order
    field_order = [
        'layout', 'title', 'date', 'author', 'categories', 'tags', 'image',
        'rating', 'paper_title', 'paper_author', 'paper_journal', 'paper_year',
        'paper_doi', 'paper_et_al', 'summary', 'author_context'
    ]

    # Output fields in order
    seen = set()
    for field in field_order:
        if field in front_matter:
            seen.add(field)
            value = front_matter[field]
            lines.append(format_yaml_field(field, value))

    # Output remaining fields
    for field, value in front_matter.items():
        if field not in seen:
            lines.append(format_yaml_field(field, value))

    lines.append('---')
    lines.append('')

    return '\n'.join(lines) + body


def format_yaml_field(field: str, value) -> str:
    """Format a single YAML field."""
    if value is None or value == '':
        return f'{field}:'
    elif isinstance(value, bool):
        return f'{field}: {str(value).lower()}'
    elif isinstance(value, list):
        # Format as inline list with proper quoting
        items = ', '.join(f'"{item}"' if isinstance(item, str) else str(item) for item in value)
        return f'{field}: [{items}]'
    elif isinstance(value, str):
        # Quote strings that need it
        if ':' in value or '"' in value or '\n' in value or value.startswith('{') or value.startswith('['):
            escaped = value.replace('"', '\\"')
            return f'{field}: "{escaped}"'
        return f'{field}: "{value}"'
    else:
        return f'{field}: {value}'


def process_posts(posts_dir: str = '_posts') -> list[str]:
    """Process all posts without date prefixes.

    Returns:
        List of processed file paths
    """
    posts_path = Path(posts_dir)
    if not posts_path.exists():
        print(f"Posts directory not found: {posts_dir}")
        return []

    processed = []
    now = datetime.now()
    date_prefix = now.strftime('%Y-%m-%d')
    datetime_str = now.strftime('%Y-%m-%d %H:%M:%S %z').strip() or now.strftime('%Y-%m-%d %H:%M:%S')

    for filepath in posts_path.rglob('*.md'):
        filename = filepath.name

        # Skip files that already have a date prefix
        if has_date_prefix(filename):
            continue

        print(f"Processing: {filepath}")

        # Read content
        content = filepath.read_text(encoding='utf-8')

        # Parse front matter
        front_matter, body = parse_front_matter(content)

        if not front_matter:
            print(f"  Warning: No front matter found, skipping")
            continue

        # Add date to front matter if not present or empty
        if not front_matter.get('date'):
            front_matter['date'] = datetime_str
            print(f"  Added date: {datetime_str}")

        # Serialize back
        new_content = serialize_front_matter(front_matter, body)

        # Create new filename with date prefix
        new_filename = f"{date_prefix}-{filename}"
        new_filepath = filepath.parent / new_filename

        # Write new file
        new_filepath.write_text(new_content, encoding='utf-8')
        print(f"  Renamed to: {new_filepath}")

        # Remove old file
        filepath.unlink()

        processed.append(str(new_filepath))

    return processed


if __name__ == '__main__':
    processed = process_posts()
    if processed:
        print(f"\nProcessed {len(processed)} posts:")
        for path in processed:
            print(f"  - {path}")
    else:
        print("No posts needed processing")
