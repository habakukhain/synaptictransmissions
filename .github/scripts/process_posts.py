#!/usr/bin/env python3
"""
Process new posts in _posts/ that don't have proper date formatting.

This script:
1. Finds posts without a date in the filename (YYYY-MM-DD prefix)
2. Renames them with the current date prefix
3. Adds/updates the date field in the front matter
4. Assigns sequential slug numbers per category
"""

import os
import re
from collections import defaultdict
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
        'layout', 'title', 'date', 'author', 'categories', 'slug', 'tags', 'image',
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


def get_category_slug_counts(posts_dir: str = '_posts') -> dict[str, int]:
    """Get the highest slug number used for each category.

    Returns:
        Dict mapping category name to highest slug number used
    """
    posts_path = Path(posts_dir)
    if not posts_path.exists():
        return {}

    category_max_slug = defaultdict(int)

    for filepath in posts_path.rglob('*.md'):
        content = filepath.read_text(encoding='utf-8')
        front_matter, _ = parse_front_matter(content)

        if not front_matter:
            continue

        category = front_matter.get('categories', '')
        if isinstance(category, list):
            category = category[0] if category else ''

        slug = front_matter.get('slug')
        if slug is not None:
            try:
                slug_num = int(slug)
                category_max_slug[category] = max(category_max_slug[category], slug_num)
            except (ValueError, TypeError):
                pass

    return dict(category_max_slug)


def get_post_date(front_matter: dict, filename: str) -> datetime:
    """Extract date from front matter or filename.

    Returns:
        datetime object for sorting
    """
    # Try front matter date first
    date_val = front_matter.get('date')
    if date_val:
        if isinstance(date_val, datetime):
            return date_val
        try:
            # Try parsing as datetime string
            return datetime.strptime(str(date_val).split()[0], '%Y-%m-%d')
        except ValueError:
            pass

    # Try filename date prefix
    match = DATE_PREFIX_PATTERN.match(filename)
    if match:
        try:
            return datetime.strptime(filename[:10], '%Y-%m-%d')
        except ValueError:
            pass

    # Default to now
    return datetime.now()


def process_posts(posts_dir: str = '_posts') -> list[str]:
    """Process all posts without date prefixes.

    Returns:
        List of processed file paths
    """
    posts_path = Path(posts_dir)
    if not posts_path.exists():
        print(f"Posts directory not found: {posts_dir}")
        return []

    now = datetime.now()
    date_prefix = now.strftime('%Y-%m-%d')
    datetime_str = now.strftime('%Y-%m-%d %H:%M:%S %z').strip() or now.strftime('%Y-%m-%d %H:%M:%S')

    # First pass: collect all posts and their metadata
    posts_data = []
    for filepath in posts_path.rglob('*.md'):
        content = filepath.read_text(encoding='utf-8')
        front_matter, body = parse_front_matter(content)

        if not front_matter:
            print(f"  Warning: No front matter found in {filepath}, skipping")
            continue

        category = front_matter.get('categories', '')
        if isinstance(category, list):
            category = category[0] if category else ''

        post_date = get_post_date(front_matter, filepath.name)

        posts_data.append({
            'filepath': filepath,
            'front_matter': front_matter,
            'body': body,
            'category': category,
            'date': post_date,
            'has_slug': front_matter.get('slug') is not None,
        })

    # Group posts by category and sort by date
    posts_by_category = defaultdict(list)
    for post in posts_data:
        posts_by_category[post['category']].append(post)

    for category in posts_by_category:
        posts_by_category[category].sort(key=lambda p: p['date'])

    # Calculate slug assignments: existing slugs first, then new ones by date
    category_max_slug = defaultdict(int)
    for post in posts_data:
        if post['has_slug']:
            slug = post['front_matter']['slug']
            try:
                slug_num = int(slug)
                category_max_slug[post['category']] = max(
                    category_max_slug[post['category']], slug_num
                )
            except (ValueError, TypeError):
                pass

    # Assign slugs to posts without them, in date order per category
    for category, posts in posts_by_category.items():
        for post in posts:
            if not post['has_slug']:
                category_max_slug[category] += 1
                post['front_matter']['slug'] = category_max_slug[category]
                post['new_slug'] = category_max_slug[category]

    # Second pass: write updated posts
    processed = []
    for post in posts_data:
        filepath = post['filepath']
        front_matter = post['front_matter']
        body = post['body']
        filename = filepath.name

        needs_update = False
        new_filepath = filepath

        # Handle posts without date prefix
        if not has_date_prefix(filename):
            print(f"Processing: {filepath}")

            # Add date to front matter if not present or empty
            if not front_matter.get('date'):
                front_matter['date'] = datetime_str
                print(f"  Added date: {datetime_str}")

            # Create new filename with date prefix
            new_filename = f"{date_prefix}-{filename}"
            new_filepath = filepath.parent / new_filename
            needs_update = True

        # Check if we assigned a new slug
        if 'new_slug' in post:
            print(f"  Added slug: {post['new_slug']} (category: {post['category']}) to {filepath.name}")
            needs_update = True

        if needs_update:
            # Serialize back
            new_content = serialize_front_matter(front_matter, body)

            # Write new file
            new_filepath.write_text(new_content, encoding='utf-8')

            # Remove old file if renamed
            if new_filepath != filepath:
                print(f"  Renamed to: {new_filepath}")
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
