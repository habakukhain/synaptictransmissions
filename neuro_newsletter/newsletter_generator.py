"""
Newsletter Generator - Creates markdown newsletters from analyzed papers.
Also generates Jekyll-formatted draft blog posts.
"""

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from paper_analyzer import PaperAnalysis


class NewsletterGenerator:
    """Generates markdown newsletters from paper analyses."""

    IMPORTANCE_STARS = {
        5: "\u2605\u2605\u2605\u2605\u2605",
        4: "\u2605\u2605\u2605\u2605",
        3: "\u2605\u2605\u2605",
        2: "\u2605\u2605",
        1: "\u2605"
    }

    # Newsletter sections in display order
    CATEGORY_ORDER = ["evidence-based", "pathophysiology", "reviews", "clinical-pearls"]

    CATEGORY_HEADERS = {
        "evidence-based": "Evidence-Based Medicine",
        "pathophysiology": "Pathophysiology & Mechanisms",
        "reviews": "Reviews",
        "clinical-pearls": "Clinical Pearls & Case Reports"
    }

    CATEGORY_DESCRIPTIONS = {
        "evidence-based": "Multicenter trials, meta-analyses, and guidelines",
        "pathophysiology": "Disease mechanisms, neuropathology, and biomarkers",
        "reviews": "State-of-the-art summaries and educational pieces",
        "clinical-pearls": "Instructive cases and practical observations"
    }

    def __init__(self, output_dir: str = "./output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _format_paper_link(self, analysis: PaperAnalysis) -> str:
        """Generate link for paper (DOI preferred, PubMed fallback)."""
        if analysis.paper.doi:
            return f"https://doi.org/{analysis.paper.doi}"
        return f"https://pubmed.ncbi.nlm.nih.gov/{analysis.paper.pmid}/"

    def _format_authors(self, analysis: PaperAnalysis) -> str:
        """Format author list for display."""
        authors = analysis.paper.authors
        if not authors:
            return "Authors not listed"

        if len(authors) == 1:
            return authors[0]
        elif len(authors) == 2:
            return f"{authors[0]} and {authors[1]}"
        else:
            return f"{authors[0]} et al."

    def _format_paper(self, analysis: PaperAnalysis) -> str:
        """Format a single paper entry."""
        link = self._format_paper_link(analysis)
        authors_short = self._format_authors(analysis)
        stars = self.IMPORTANCE_STARS.get(analysis.importance_score, "\u2605")

        # Format keywords
        keywords_str = " | ".join(analysis.keywords) if analysis.keywords else ""

        # Add indicator for full text analysis
        source_indicator = ""
        if analysis.full_text_used:
            source_indicator = " | Full text analyzed"

        lines = [
            f"### [{analysis.paper.title}]({link})",
            f"{stars} | {keywords_str}",
            f"**{analysis.paper.journal}**{source_indicator}",
            "",
            f"> {analysis.summary}",
            "",
            f"**Authors**: {authors_short} ({analysis.author_context})",
            "",
            "**Critical Evaluation**:",
            f"- **Problem**: {analysis.problem_addressed}",
            f"- **Result**: {analysis.actual_result}",
            f"- **Open Questions**: {analysis.what_is_left_open}",
            "",
            "---",
            ""
        ]

        return "\n".join(lines)

    def generate(
        self,
        analyses: list[PaperAnalysis],
        lookback_days: int = 7,
        output_filename: Optional[str] = None
    ) -> Path:
        """
        Generate a markdown newsletter from paper analyses.

        Args:
            analyses: List of analyzed papers (should already be sorted)
            lookback_days: Number of days covered
            output_filename: Custom filename, or auto-generated if None

        Returns:
            Path to the generated newsletter file
        """
        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=lookback_days)

        # Generate header
        header = [
            "# Neurology Newsletter",
            f"**Week of {start_date.strftime('%B %d')} - {end_date.strftime('%B %d, %Y')}**",
            "",
            f"*{len(analyses)} papers reviewed from {lookback_days} days of publications*",
            "",
            "---",
            ""
        ]

        # Group papers by category
        papers_by_category: dict[str, list[PaperAnalysis]] = {}
        for analysis in analyses:
            cat = analysis.category
            if cat not in papers_by_category:
                papers_by_category[cat] = []
            papers_by_category[cat].append(analysis)

        # Sort within each category by importance (descending)
        for cat in papers_by_category:
            papers_by_category[cat].sort(key=lambda a: -a.importance_score)

        # Generate body - sections in defined order
        body = []

        for category in self.CATEGORY_ORDER:
            if category not in papers_by_category:
                continue

            papers = papers_by_category[category]
            section_title = self.CATEGORY_HEADERS.get(category, category.title())
            section_desc = self.CATEGORY_DESCRIPTIONS.get(category, "")

            body.append(f"## {section_title}")
            body.append(f"*{section_desc}*")
            body.append("")

            for analysis in papers:
                body.append(self._format_paper(analysis))

        # Generate footer
        footer = [
            "",
            "---",
            "",
            f"*Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')} using Claude AI*",
            "",
            "*This newsletter is auto-generated. Always verify findings in original sources.*"
        ]

        # Combine all sections
        content = "\n".join(header + body + footer)

        # Write to file
        if output_filename is None:
            output_filename = f"newsletter_{end_date.strftime('%Y-%m-%d')}.md"

        output_path = self.output_dir / output_filename
        output_path.write_text(content)

        print(f"\nNewsletter generated: {output_path}")
        return output_path

    def generate_summary(self, analyses: list[PaperAnalysis]) -> str:
        """Generate a brief summary of the newsletter contents."""
        if not analyses:
            return "No papers to summarize."

        # Count by importance
        by_importance = {}
        for a in analyses:
            score = a.importance_score
            by_importance[score] = by_importance.get(score, 0) + 1

        # Count by category
        by_category = {}
        for a in analyses:
            cat = a.category
            by_category[cat] = by_category.get(cat, 0) + 1

        # Count full text vs abstract
        full_text_count = sum(1 for a in analyses if a.full_text_used)
        abstract_count = len(analyses) - full_text_count

        summary_lines = [
            f"Total papers: {len(analyses)}",
            f"  Full text analyzed: {full_text_count}",
            f"  Abstract only: {abstract_count}",
            "",
            "By category:"
        ]

        for cat in self.CATEGORY_ORDER:
            if cat in by_category:
                header = self.CATEGORY_HEADERS.get(cat, cat)
                summary_lines.append(f"  {header}: {by_category[cat]}")

        summary_lines.append("")
        summary_lines.append("By importance:")

        for level in sorted(by_importance.keys(), reverse=True):
            stars = self.IMPORTANCE_STARS.get(level, "\u2605")
            summary_lines.append(f"  {stars}: {by_importance[level]}")

        return "\n".join(summary_lines)

    def _slugify(self, title: str) -> str:
        """Convert title to URL-friendly slug."""
        # Remove special characters, keep alphanumeric and spaces
        slug = re.sub(r'[^\w\s-]', '', title.lower())
        # Replace spaces with hyphens
        slug = re.sub(r'[\s_]+', '-', slug)
        # Remove multiple consecutive hyphens
        slug = re.sub(r'-+', '-', slug)
        # Trim to reasonable length
        return slug[:60].strip('-')

    def _abbreviate_journal(self, journal: str) -> str:
        """Abbreviate common journal names."""
        abbreviations = {
            "Nature communications": "Nat Comm",
            "Nature Communications": "Nat Comm",
            "Nature medicine": "Nat Med",
            "Nature Medicine": "Nat Med",
            "Nature neuroscience": "Nat Neurosci",
            "Nature Neuroscience": "Nat Neurosci",
            "Nature": "Nature",
            "Science": "Science",
            "Cell": "Cell",
            "Neurology": "Neurology",
            "JAMA Neurology": "JAMA Neurol",
            "JAMA": "JAMA",
            "Lancet Neurology": "Lancet Neurol",
            "Lancet": "Lancet",
            "Annals of Neurology": "Ann Neurol",
            "Brain": "Brain",
            "Stroke": "Stroke",
            "New England Journal of Medicine": "NEJM",
            "N Engl J Med": "NEJM",
            "Journal of Neurology, Neurosurgery, and Psychiatry": "JNNP",
            "Journal of Neurology": "J Neurol",
            "Muscle & nerve": "Muscle Nerve",
            "Muscle Nerve": "Muscle Nerve",
            "Movement Disorders": "Mov Disord",
            "Epilepsia": "Epilepsia",
            "Multiple Sclerosis Journal": "Mult Scler",
            "Journal of neurointerventional surgery": "J NeuroInterv Surg",
            "Journal of NeuroInterventional Surgery": "J NeuroInterv Surg",
        }
        return abbreviations.get(journal, journal)

    def _get_first_author_lastname(self, analysis: PaperAnalysis) -> str:
        """Extract last name of first author."""
        authors = analysis.paper.authors
        if not authors:
            return "Unknown"
        first_author = authors[0]
        # Handle "Lastname, Firstname" format
        if "," in first_author:
            return first_author.split(",")[0].strip()
        # Handle "Firstname Lastname" format
        parts = first_author.split()
        return parts[-1] if parts else "Unknown"

    def _format_citation(self, analysis: PaperAnalysis) -> str:
        """Format citation as 'Lastname et al., Journal 2025'."""
        lastname = self._get_first_author_lastname(analysis)
        journal_abbrev = self._abbreviate_journal(analysis.paper.journal)
        year = analysis.paper.publication_date[:4] if analysis.paper.publication_date else "2026"

        authors = analysis.paper.authors
        if authors and len(authors) > 1:
            return f"{lastname} et al., {journal_abbrev} {year}"
        return f"{lastname}, {journal_abbrev} {year}"

    def _format_draft(self, analysis: PaperAnalysis, author: str = "Habakuk Hain") -> str:
        """Format a single paper as a Jekyll draft blog post."""
        link = self._format_paper_link(analysis)

        # Convert 1-5 importance to 0-10 scale
        rating = analysis.importance_score * 2

        # Format keywords as Jekyll tags (exactly 3, properly quoted)
        tags = analysis.keywords[:3] if analysis.keywords else []
        tags_formatted = ", ".join(f'"{tag}"' for tag in tags)

        # Extract citation components
        first_author = self._get_first_author_lastname(analysis)
        journal_abbrev = self._abbreviate_journal(analysis.paper.journal)
        year = analysis.paper.publication_date[:4] if analysis.paper.publication_date else "2026"
        has_multiple_authors = len(analysis.paper.authors) > 1 if analysis.paper.authors else False

        # Escape quotes in title and summary for YAML
        escaped_title = analysis.paper.title.replace('"', '\\"')
        escaped_summary = analysis.summary.replace('"', '\\"')

        # Escape author context for YAML
        escaped_author_context = analysis.author_context.replace('"', '\\"') if analysis.author_context else ""

        # Build front matter
        front_matter = [
            "---",
            "layout: post",
            f'title: "{escaped_title}"',
            "date:",
            f'author: "{author}"',
            "categories: transmission",
            f"tags: [{tags_formatted}]",
            "image:",
            f"rating: {rating}",
            f'paper_title: "{escaped_title}"',
            f'paper_author: "{first_author}"',
            f'paper_journal: "{journal_abbrev}"',
            f'paper_year: "{year}"',
            f'paper_doi: "{link}"',
            f"paper_et_al: {str(has_multiple_authors).lower()}",
            f'summary: "{escaped_summary}"',
            f'author_context: "{escaped_author_context}"',
            "---",
            ""
        ]

        # Build post body (content after the citation/summary which are now handled by template)
        body = [
            f"**Problem**: {analysis.problem_addressed}",
            "",
            f"**Result**: {analysis.actual_result}",
            "",
            f"**Open Questions**: {analysis.what_is_left_open}",
            ""
        ]

        return "\n".join(front_matter + body)

    def generate_drafts(
        self,
        analyses: list[PaperAnalysis],
        drafts_dir: str = "../_drafts",
        author: str = "Habakuk Hain",
        min_importance: int = 3
    ) -> list[Path]:
        """
        Generate Jekyll draft blog posts from paper analyses.

        Args:
            analyses: List of analyzed papers
            drafts_dir: Path to Jekyll _drafts directory (relative to output_dir or absolute)
            author: Author name for front matter
            min_importance: Minimum importance score to generate draft (1-5)

        Returns:
            List of paths to generated draft files
        """
        # Resolve drafts directory
        drafts_path = Path(drafts_dir)
        if not drafts_path.is_absolute():
            drafts_path = self.output_dir / drafts_path
        drafts_path = drafts_path.resolve()

        # Ensure directory exists
        drafts_path.mkdir(parents=True, exist_ok=True)

        generated = []

        for analysis in analyses:
            # Skip low-importance papers
            if analysis.importance_score < min_importance:
                continue

            # Generate draft content
            content = self._format_draft(analysis, author=author)

            # Create filename from title
            slug = self._slugify(analysis.paper.title)
            filename = f"{slug}.md"
            filepath = drafts_path / filename

            # Write draft
            filepath.write_text(content)
            generated.append(filepath)

        if generated:
            print(f"\nGenerated {len(generated)} blog drafts in: {drafts_path}")

        return generated
