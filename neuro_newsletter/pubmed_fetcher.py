"""
PubMed Fetcher - Retrieves recent neurology publications via NCBI E-utilities API.
"""

import time
import requests
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass


@dataclass
class Paper:
    """Represents a paper fetched from PubMed."""
    pmid: str
    title: str
    abstract: str
    authors: list[str]
    affiliations: list[str]
    journal: str
    doi: Optional[str]
    pmc_id: Optional[str]  # PMC ID for free full text access
    publication_date: str
    source_category: str  # neuromuscular, neurovascular, general, subspecialty, mega_journal


class PubMedFetcher:
    """Fetches papers from PubMed using NCBI E-utilities API."""

    BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def __init__(self, lookback_days: int = 7):
        self.lookback_days = lookback_days
        self.session = requests.Session()

    def _build_date_range(self) -> tuple[str, str]:
        """Build date range for PubMed query."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=self.lookback_days)
        return start_date.strftime("%Y/%m/%d"), end_date.strftime("%Y/%m/%d")

    def _search_journal(self, journal: str, start_date: str, end_date: str) -> list[str]:
        """Search for PMIDs from a specific journal within date range."""
        query = f'"{journal}"[Journal] AND ("{start_date}"[PDAT] : "{end_date}"[PDAT])'

        params = {
            "db": "pubmed",
            "term": query,
            "retmax": 500,
            "retmode": "json",
            "usehistory": "n"
        }

        try:
            response = self.session.get(f"{self.BASE_URL}/esearch.fcgi", params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("esearchresult", {}).get("idlist", [])
        except requests.RequestException as e:
            print(f"  Warning: Failed to search {journal}: {e}")
            return []

    def _fetch_paper_details(self, pmids: list[str]) -> list[dict]:
        """Fetch detailed information for a list of PMIDs."""
        if not pmids:
            return []

        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            "rettype": "abstract"
        }

        try:
            response = self.session.get(f"{self.BASE_URL}/efetch.fcgi", params=params)
            response.raise_for_status()
            return self._parse_xml_response(response.text)
        except requests.RequestException as e:
            print(f"  Warning: Failed to fetch paper details: {e}")
            return []

    def _parse_xml_response(self, xml_text: str) -> list[dict]:
        """Parse PubMed XML response to extract paper details."""
        import xml.etree.ElementTree as ET

        papers = []
        try:
            root = ET.fromstring(xml_text)

            for article in root.findall(".//PubmedArticle"):
                paper = self._parse_article(article)
                if paper:
                    papers.append(paper)
        except ET.ParseError as e:
            print(f"  Warning: XML parse error: {e}")

        return papers

    def _parse_article(self, article) -> Optional[dict]:
        """Parse a single PubmedArticle element."""
        try:
            medline = article.find(".//MedlineCitation")
            if medline is None:
                return None

            pmid_elem = medline.find(".//PMID")
            pmid = pmid_elem.text if pmid_elem is not None else None
            if not pmid:
                return None

            article_elem = medline.find(".//Article")
            if article_elem is None:
                return None

            # Title
            title_elem = article_elem.find(".//ArticleTitle")
            title = self._get_text_content(title_elem) if title_elem is not None else ""

            # Abstract
            abstract_parts = []
            abstract_elem = article_elem.find(".//Abstract")
            if abstract_elem is not None:
                for abstract_text in abstract_elem.findall(".//AbstractText"):
                    label = abstract_text.get("Label", "")
                    text = self._get_text_content(abstract_text)
                    if label and text:
                        abstract_parts.append(f"{label}: {text}")
                    elif text:
                        abstract_parts.append(text)
            abstract = " ".join(abstract_parts)

            # Authors and affiliations
            authors = []
            affiliations = []
            author_list = article_elem.find(".//AuthorList")
            if author_list is not None:
                for author in author_list.findall(".//Author"):
                    lastname = author.find("LastName")
                    forename = author.find("ForeName")
                    if lastname is not None:
                        name = lastname.text or ""
                        if forename is not None and forename.text:
                            name = f"{forename.text} {name}"
                        authors.append(name)

                    for aff in author.findall(".//AffiliationInfo/Affiliation"):
                        if aff.text and aff.text not in affiliations:
                            affiliations.append(aff.text)

            # Journal
            journal_elem = article_elem.find(".//Journal/Title")
            journal = journal_elem.text if journal_elem is not None else ""

            # DOI
            doi = None
            for eloc in article_elem.findall(".//ELocationID"):
                if eloc.get("EIdType") == "doi":
                    doi = eloc.text
                    break

            # Check ArticleIdList for DOI and PMC ID
            pmc_id = None
            article_id_list = article.find(".//PubmedData/ArticleIdList")
            if article_id_list is not None:
                for aid in article_id_list.findall(".//ArticleId"):
                    id_type = aid.get("IdType")
                    if id_type == "doi" and doi is None:
                        doi = aid.text
                    elif id_type == "pmc":
                        pmc_id = aid.text

            # Publication date
            pub_date = ""
            pub_date_elem = article_elem.find(".//Journal/JournalIssue/PubDate")
            if pub_date_elem is not None:
                year = pub_date_elem.find("Year")
                month = pub_date_elem.find("Month")
                day = pub_date_elem.find("Day")

                date_parts = []
                if year is not None and year.text:
                    date_parts.append(year.text)
                if month is not None and month.text:
                    date_parts.append(month.text)
                if day is not None and day.text:
                    date_parts.append(day.text)
                pub_date = " ".join(date_parts)

            return {
                "pmid": pmid,
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "affiliations": affiliations[:3],  # Keep top 3 affiliations
                "journal": journal,
                "doi": doi,
                "pmc_id": pmc_id,
                "publication_date": pub_date
            }

        except Exception as e:
            print(f"  Warning: Failed to parse article: {e}")
            return None

    def _get_text_content(self, elem) -> str:
        """Extract all text content from an element, including nested elements."""
        if elem is None:
            return ""

        parts = []
        if elem.text:
            parts.append(elem.text)

        for child in elem:
            parts.append(self._get_text_content(child))
            if child.tail:
                parts.append(child.tail)

        return "".join(parts).strip()

    def fetch_papers(
        self,
        journals_by_category: dict[str, list[str]],
        mega_journal_keywords: list[str],
        processed_pmids: set[str],
        max_papers: int = 150,
        adjacent_keywords: dict[str, list[str]] = None
    ) -> list[Paper]:
        """
        Fetch papers from all configured journals.

        Args:
            journals_by_category: Dict mapping category to list of journal names
            mega_journal_keywords: Keywords to filter mega-journal papers
            processed_pmids: Set of already processed PMIDs to skip
            max_papers: Maximum number of papers to return
            adjacent_keywords: Dict mapping adjacent category names to keyword lists

        Returns:
            List of Paper objects
        """
        if adjacent_keywords is None:
            adjacent_keywords = {}

        start_date, end_date = self._build_date_range()
        print(f"Fetching papers from {start_date} to {end_date}")

        all_papers = []
        seen_pmids = set(processed_pmids)

        # Process each category
        for category, journals in journals_by_category.items():
            is_mega = category == "mega_journals"
            is_adjacent = category.startswith("adjacent_")
            print(f"\nSearching {category} journals ({len(journals)} journals)...")

            for journal in journals:
                # Rate limiting - be nice to NCBI
                time.sleep(0.35)

                pmids = self._search_journal(journal, start_date, end_date)
                new_pmids = [p for p in pmids if p not in seen_pmids]

                if not new_pmids:
                    continue

                print(f"  {journal}: {len(new_pmids)} new papers")

                # Fetch details in batches
                for i in range(0, len(new_pmids), 50):
                    batch = new_pmids[i:i+50]
                    time.sleep(0.35)

                    paper_data = self._fetch_paper_details(batch)

                    for data in paper_data:
                        # Filter mega-journals for neurology keywords
                        if is_mega:
                            text = f"{data['title']} {data['abstract']}".lower()
                            if not any(kw.lower() in text for kw in mega_journal_keywords):
                                continue

                        # Filter adjacent-field journals for relevant keywords
                        if is_adjacent and category in adjacent_keywords:
                            text = f"{data['title']} {data['abstract']}".lower()
                            if not any(kw.lower() in text for kw in adjacent_keywords[category]):
                                continue

                        paper = Paper(
                            pmid=data["pmid"],
                            title=data["title"],
                            abstract=data["abstract"],
                            authors=data["authors"],
                            affiliations=data["affiliations"],
                            journal=data["journal"],
                            doi=data["doi"],
                            pmc_id=data["pmc_id"],
                            publication_date=data["publication_date"],
                            source_category=category
                        )

                        all_papers.append(paper)
                        seen_pmids.add(data["pmid"])

                        if len(all_papers) >= max_papers:
                            print(f"\nReached max papers limit ({max_papers})")
                            return all_papers

        print(f"\nTotal papers fetched: {len(all_papers)}")
        return all_papers
