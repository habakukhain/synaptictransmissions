"""
Zotero Uploader - Uploads analyzed papers to Zotero library.

Creates a dated collection and adds papers with full metadata,
tags, notes, and PDF attachments when available.
"""

from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests
from pyzotero import zotero


@dataclass
class ZoteroUploadResult:
    """Result of uploading papers to Zotero."""
    collection_key: str
    collection_name: str
    items_created: int
    pdfs_attached: int
    errors: list[str]


class ZoteroUploader:
    """Uploads papers to Zotero library with full metadata."""

    def __init__(
        self,
        api_key: str,
        library_id: str,
        library_type: str = "user"
    ):
        """
        Initialize the Zotero uploader.

        Args:
            api_key: Zotero API key
            library_id: Library ID (user ID or group ID)
            library_type: "user" or "group"
        """
        self.api_key = api_key
        self.library_id = library_id
        self.library_type = library_type
        self.zot = zotero.Zotero(library_id, library_type, api_key)

    def _create_collection(self, name: str, parent_key: Optional[str] = None) -> str:
        """
        Create a new collection in Zotero.

        Args:
            name: Collection name
            parent_key: Optional parent collection key

        Returns:
            The collection key
        """
        collection_data = {"name": name}
        if parent_key:
            collection_data["parentCollection"] = parent_key

        result = self.zot.create_collections([collection_data])

        if "successful" in result and result["successful"]:
            # Get the key from the first successful creation
            first_key = list(result["successful"].keys())[0]
            return result["successful"][first_key]["data"]["key"]

        raise Exception(f"Failed to create collection: {result}")

    def _parse_publication_date(self, pub_date: str) -> str:
        """
        Parse publication date string to Zotero format (YYYY-MM-DD).

        Args:
            pub_date: Date string like "2025 Feb 15" or "2025 Feb" or "2025"

        Returns:
            ISO format date string
        """
        try:
            # Try full date
            dt = datetime.strptime(pub_date, "%Y %b %d")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

        try:
            # Try month/year
            dt = datetime.strptime(pub_date, "%Y %b")
            return dt.strftime("%Y-%m")
        except ValueError:
            pass

        try:
            # Try year only
            dt = datetime.strptime(pub_date, "%Y")
            return dt.strftime("%Y")
        except ValueError:
            pass

        # Return as-is if can't parse
        return pub_date

    def _create_item_data(self, analysis, add_notes: bool = True) -> dict:
        """
        Create Zotero item data from a PaperAnalysis object.

        Args:
            analysis: PaperAnalysis object
            add_notes: Whether to include analysis notes

        Returns:
            Dict with Zotero item template data
        """
        paper = analysis.paper

        # Build creators list
        creators = []
        for author in paper.authors:
            parts = author.rsplit(" ", 1)
            if len(parts) == 2:
                creators.append({
                    "creatorType": "author",
                    "firstName": parts[0],
                    "lastName": parts[1]
                })
            else:
                creators.append({
                    "creatorType": "author",
                    "lastName": author,
                    "firstName": ""
                })

        # Build tags from keywords and category
        tags = []
        for keyword in analysis.keywords:
            tags.append({"tag": keyword})
        tags.append({"tag": f"category:{analysis.category}"})
        tags.append({"tag": f"source:{paper.source_category}"})
        tags.append({"tag": f"importance:{analysis.importance_score}"})

        # Create item data
        item_data = {
            "itemType": "journalArticle",
            "title": paper.title,
            "creators": creators,
            "abstractNote": paper.abstract or "",
            "publicationTitle": paper.journal,
            "date": self._parse_publication_date(paper.publication_date),
            "DOI": paper.doi or "",
            "extra": f"PMID: {paper.pmid}",
            "tags": tags,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{paper.pmid}/",
        }

        return item_data

    def _create_note(self, analysis, item_key: str) -> Optional[str]:
        """
        Create a Zotero note with the analysis summary.

        Args:
            analysis: PaperAnalysis object
            item_key: Parent item key

        Returns:
            Note key or None
        """
        note_content = f"""<h2>Newsletter Analysis</h2>
<p><strong>Importance:</strong> {analysis.importance} ({analysis.importance_score}/5)</p>
<p><strong>Category:</strong> {analysis.category}</p>
<p><strong>Keywords:</strong> {', '.join(analysis.keywords)}</p>

<h3>Summary</h3>
<p>{analysis.summary}</p>

<h3>Critical Evaluation</h3>
<p><strong>Problem Addressed:</strong> {analysis.problem_addressed}</p>
<p><strong>Key Result:</strong> {analysis.actual_result}</p>
<p><strong>Open Questions:</strong> {analysis.what_is_left_open}</p>

<p><em>Author Context:</em> {analysis.author_context}</p>
<p><em>Analysis based on: {'Full text' if analysis.full_text_used else 'Abstract only'}</em></p>
"""

        note_data = {
            "itemType": "note",
            "parentItem": item_key,
            "note": note_content,
            "tags": [{"tag": "newsletter-analysis"}]
        }

        try:
            result = self.zot.create_items([note_data])
            if "successful" in result and result["successful"]:
                first_key = list(result["successful"].keys())[0]
                return result["successful"][first_key]["data"]["key"]
        except Exception as e:
            print(f"    Warning: Failed to create note: {e}")

        return None

    def _download_pdf(self, doi: str, pmc_id: Optional[str], unpaywall_email: str) -> Optional[str]:
        """
        Attempt to download PDF for a paper.

        Args:
            doi: Paper DOI
            pmc_id: PMC ID if available
            unpaywall_email: Email for Unpaywall API

        Returns:
            Path to downloaded PDF or None
        """
        # Try Unpaywall first for PDF URL
        if doi:
            try:
                url = f"https://api.unpaywall.org/v2/{doi}"
                params = {"email": unpaywall_email}
                response = requests.get(url, params=params, timeout=30)

                if response.status_code == 200:
                    data = response.json()
                    best_oa = data.get("best_oa_location")
                    if best_oa:
                        pdf_url = best_oa.get("url_for_pdf")
                        if pdf_url:
                            # Download the PDF
                            pdf_response = requests.get(
                                pdf_url,
                                timeout=60,
                                headers={"User-Agent": "Mozilla/5.0 (compatible; NeuroNewsletter/1.0)"}
                            )
                            if pdf_response.status_code == 200 and "pdf" in pdf_response.headers.get("content-type", "").lower():
                                # Save to temp file
                                fd, path = tempfile.mkstemp(suffix=".pdf")
                                with os.fdopen(fd, "wb") as f:
                                    f.write(pdf_response.content)
                                return path
            except Exception:
                pass

        # Try PMC PDF
        if pmc_id:
            try:
                pmc_num = pmc_id.replace("PMC", "")
                pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_num}/pdf/"
                pdf_response = requests.get(
                    pdf_url,
                    timeout=60,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; NeuroNewsletter/1.0)"},
                    allow_redirects=True
                )
                if pdf_response.status_code == 200 and len(pdf_response.content) > 1000:
                    content_type = pdf_response.headers.get("content-type", "").lower()
                    if "pdf" in content_type:
                        fd, path = tempfile.mkstemp(suffix=".pdf")
                        with os.fdopen(fd, "wb") as f:
                            f.write(pdf_response.content)
                        return path
            except Exception:
                pass

        return None

    def _attach_pdf(self, item_key: str, pdf_path: str, title: str) -> bool:
        """
        Attach a PDF to a Zotero item.

        Args:
            item_key: Parent item key
            pdf_path: Path to PDF file
            title: Paper title for filename

        Returns:
            True if successful
        """
        try:
            # Clean title for filename
            clean_title = "".join(c for c in title[:50] if c.isalnum() or c in " -_").strip()
            filename = f"{clean_title}.pdf"

            self.zot.attachment_simple([pdf_path], item_key)
            return True
        except Exception as e:
            print(f"    Warning: Failed to attach PDF: {e}")
            return False

    def upload_papers(
        self,
        analyses: list,
        collection_name: Optional[str] = None,
        add_notes: bool = True,
        attach_pdfs: bool = True,
        unpaywall_email: str = "neuro_newsletter@example.com"
    ) -> ZoteroUploadResult:
        """
        Upload analyzed papers to Zotero.

        Args:
            analyses: List of PaperAnalysis objects
            collection_name: Name for the collection (default: "Neuro Newsletter DD.MM.YYYY")
            add_notes: Whether to add analysis notes to items
            attach_pdfs: Whether to attempt PDF attachment
            unpaywall_email: Email for Unpaywall API

        Returns:
            ZoteroUploadResult with upload statistics
        """
        # Create collection with date-based name
        if not collection_name:
            today = datetime.now()
            collection_name = f"Neuro Newsletter {today.strftime('%d.%m.%Y')}"

        print(f"\nCreating Zotero collection: {collection_name}")
        collection_key = self._create_collection(collection_name)
        print(f"  Collection created: {collection_key}")

        items_created = 0
        pdfs_attached = 0
        errors = []

        for i, analysis in enumerate(analyses, 1):
            paper = analysis.paper
            print(f"  [{i}/{len(analyses)}] {paper.title[:50]}...")

            try:
                # Create the item data
                item_data = self._create_item_data(analysis, add_notes)
                item_data["collections"] = [collection_key]

                # Create the item
                result = self.zot.create_items([item_data])

                if "successful" in result and result["successful"]:
                    first_key = list(result["successful"].keys())[0]
                    item_key = result["successful"][first_key]["data"]["key"]
                    items_created += 1

                    # Add analysis note
                    if add_notes:
                        self._create_note(analysis, item_key)

                    # Try to attach PDF
                    if attach_pdfs:
                        pdf_path = self._download_pdf(paper.doi, paper.pmc_id, unpaywall_email)
                        if pdf_path:
                            if self._attach_pdf(item_key, pdf_path, paper.title):
                                pdfs_attached += 1
                                print(f"    -> PDF attached")
                            # Clean up temp file
                            try:
                                os.unlink(pdf_path)
                            except Exception:
                                pass

                    # Rate limiting
                    time.sleep(0.5)

                else:
                    error_msg = f"Failed to create item for {paper.pmid}: {result}"
                    errors.append(error_msg)
                    print(f"    -> Error: {error_msg}")

            except Exception as e:
                error_msg = f"Error uploading {paper.pmid}: {str(e)}"
                errors.append(error_msg)
                print(f"    -> Error: {error_msg}")

        return ZoteroUploadResult(
            collection_key=collection_key,
            collection_name=collection_name,
            items_created=items_created,
            pdfs_attached=pdfs_attached,
            errors=errors
        )
