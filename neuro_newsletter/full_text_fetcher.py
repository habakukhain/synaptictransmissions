"""
Full Text Fetcher - Attempts to retrieve full text from multiple sources.

Sources (in order of preference):
1. PubMed Central (PMC) - Free full text
2. Unpaywall API - Legal open access versions
3. Publisher URL - Via institutional proxy if configured
"""

import re
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote_plus

import requests


@dataclass
class FullTextResult:
    """Result of a full-text fetch attempt."""
    text: Optional[str]
    source: Optional[str]  # "pmc", "unpaywall", "publisher", None
    url: Optional[str]
    is_full_text: bool  # False if we fell back to abstract


class FullTextFetcher:
    """Fetches full text from multiple sources with proxy support."""

    PMC_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    UNPAYWALL_BASE = "https://api.unpaywall.org/v2"

    def __init__(
        self,
        proxy_config: Optional[dict] = None,
        unpaywall_email: Optional[str] = None,
        timeout: int = 30
    ):
        """
        Initialize the fetcher.

        Args:
            proxy_config: Dict with proxy settings:
                - enabled: bool
                - url: EZProxy-style URL prefix (e.g., "https://proxy.uni.edu/login?url=")
                - http_proxy: HTTP proxy URL (e.g., "http://proxy.uni.edu:8080")
                - https_proxy: HTTPS proxy URL
                - username: Optional proxy username
                - password: Optional proxy password
            unpaywall_email: Email for Unpaywall API (required for polite pool)
            timeout: Request timeout in seconds
        """
        self.proxy_config = proxy_config or {}
        self.unpaywall_email = unpaywall_email or "neuro_newsletter@example.com"
        self.timeout = timeout

        # Set up session with proxy if configured
        self.session = requests.Session()
        self._configure_proxy()

    def _configure_proxy(self):
        """Configure session with proxy settings."""
        if not self.proxy_config.get("enabled"):
            return

        proxies = {}
        if self.proxy_config.get("http_proxy"):
            proxies["http"] = self.proxy_config["http_proxy"]
        if self.proxy_config.get("https_proxy"):
            proxies["https"] = self.proxy_config["https_proxy"]
        elif self.proxy_config.get("http_proxy"):
            # Use HTTP proxy for HTTPS if not specified
            proxies["https"] = self.proxy_config["http_proxy"]

        if proxies:
            self.session.proxies.update(proxies)

        # Handle proxy authentication
        if self.proxy_config.get("username") and self.proxy_config.get("password"):
            from requests.auth import HTTPProxyAuth
            self.session.auth = HTTPProxyAuth(
                self.proxy_config["username"],
                self.proxy_config["password"]
            )

    def _apply_ezproxy_url(self, url: str) -> str:
        """Apply EZProxy URL prefix if configured."""
        if not self.proxy_config.get("enabled"):
            return url

        ezproxy_url = self.proxy_config.get("url")
        if ezproxy_url:
            # EZProxy style: prefix the target URL
            return f"{ezproxy_url}{quote_plus(url)}"

        return url

    def _fetch_from_pmc(self, pmc_id: str) -> Optional[str]:
        """
        Fetch full text from PubMed Central.

        Args:
            pmc_id: PMC ID (e.g., "PMC1234567" or "1234567")

        Returns:
            Full text content or None
        """
        # Normalize PMC ID
        if pmc_id.upper().startswith("PMC"):
            pmc_id = pmc_id[3:]

        try:
            # Fetch full text XML from PMC
            url = f"{self.PMC_BASE}/efetch.fcgi"
            params = {
                "db": "pmc",
                "id": pmc_id,
                "rettype": "xml",
                "retmode": "xml"
            }

            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()

            # Extract text content from XML
            text = self._extract_text_from_pmc_xml(response.text)
            if text and len(text) > 500:  # Sanity check
                return text

        except requests.RequestException as e:
            print(f"    PMC fetch failed: {e}")

        return None

    def _extract_text_from_pmc_xml(self, xml_text: str) -> Optional[str]:
        """Extract readable text from PMC XML."""
        import xml.etree.ElementTree as ET

        try:
            root = ET.fromstring(xml_text)

            sections = []

            # Get abstract
            for abstract in root.findall(".//abstract"):
                text = self._get_element_text(abstract)
                if text:
                    sections.append(f"ABSTRACT:\n{text}")

            # Get body sections
            for body in root.findall(".//body"):
                for sec in body.findall(".//sec"):
                    title_elem = sec.find("title")
                    title = title_elem.text if title_elem is not None else ""

                    # Get paragraphs in this section
                    paragraphs = []
                    for p in sec.findall(".//p"):
                        p_text = self._get_element_text(p)
                        if p_text:
                            paragraphs.append(p_text)

                    if paragraphs:
                        if title:
                            sections.append(f"\n{title.upper()}:\n" + "\n".join(paragraphs))
                        else:
                            sections.append("\n".join(paragraphs))

            return "\n\n".join(sections) if sections else None

        except ET.ParseError:
            return None

    def _get_element_text(self, elem) -> str:
        """Recursively get all text from an XML element."""
        parts = []
        if elem.text:
            parts.append(elem.text)
        for child in elem:
            parts.append(self._get_element_text(child))
            if child.tail:
                parts.append(child.tail)
        return " ".join(parts).strip()

    def _fetch_from_unpaywall(self, doi: str) -> Optional[tuple[str, str]]:
        """
        Find open access version via Unpaywall.

        Args:
            doi: Paper DOI

        Returns:
            Tuple of (full_text, url) or None
        """
        try:
            url = f"{self.UNPAYWALL_BASE}/{quote_plus(doi)}"
            params = {"email": self.unpaywall_email}

            response = self.session.get(url, params=params, timeout=self.timeout)

            if response.status_code == 404:
                return None

            response.raise_for_status()
            data = response.json()

            # Find best open access location
            best_oa = data.get("best_oa_location")
            if not best_oa:
                return None

            pdf_url = best_oa.get("url_for_pdf")
            landing_url = best_oa.get("url_for_landing_page")

            # Try to get the actual content
            target_url = pdf_url or landing_url
            if target_url:
                text = self._fetch_and_extract_text(target_url)
                if text:
                    return text, target_url

        except requests.RequestException as e:
            print(f"    Unpaywall fetch failed: {e}")

        return None

    def _fetch_from_publisher(self, doi: str) -> Optional[tuple[str, str]]:
        """
        Fetch from publisher URL, using proxy if configured.

        Args:
            doi: Paper DOI

        Returns:
            Tuple of (full_text, url) or None
        """
        if not doi:
            return None

        publisher_url = f"https://doi.org/{doi}"
        proxied_url = self._apply_ezproxy_url(publisher_url)

        try:
            text = self._fetch_and_extract_text(proxied_url)
            if text:
                return text, publisher_url
        except Exception as e:
            print(f"    Publisher fetch failed: {e}")

        return None

    def _fetch_and_extract_text(self, url: str) -> Optional[str]:
        """
        Fetch URL and extract text content.

        Handles HTML pages and attempts to extract article content.
        """
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; NeuroNewsletter/1.0; Academic Research)"
            }

            response = self.session.get(
                url,
                headers=headers,
                timeout=self.timeout,
                allow_redirects=True
            )
            response.raise_for_status()

            content_type = response.headers.get("content-type", "").lower()

            # Handle HTML
            if "html" in content_type:
                return self._extract_text_from_html(response.text)

            # Handle plain text
            if "text/plain" in content_type:
                return response.text

            # PDF would require additional handling (pdfplumber, etc.)
            # For now, skip PDFs
            if "pdf" in content_type:
                return None

        except requests.RequestException:
            pass

        return None

    def _extract_text_from_html(self, html: str) -> Optional[str]:
        """Extract article text from HTML page."""
        # Simple extraction - look for common article content patterns
        # For production, consider using readability-lxml or similar

        text_parts = []

        # Remove script and style tags
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)

        # Look for article content in common containers
        article_patterns = [
            r'<article[^>]*>(.*?)</article>',
            r'<div[^>]*class="[^"]*article[^"]*"[^>]*>(.*?)</div>',
            r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
            r'<div[^>]*id="[^"]*article[^"]*"[^>]*>(.*?)</div>',
        ]

        for pattern in article_patterns:
            matches = re.findall(pattern, html, flags=re.DOTALL | re.IGNORECASE)
            if matches:
                for match in matches:
                    # Strip remaining HTML tags
                    text = re.sub(r'<[^>]+>', ' ', match)
                    # Clean up whitespace
                    text = re.sub(r'\s+', ' ', text).strip()
                    if len(text) > 500:
                        text_parts.append(text)

        if text_parts:
            return "\n\n".join(text_parts)

        # Fallback: extract all paragraph text
        paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', html, flags=re.DOTALL | re.IGNORECASE)
        if paragraphs:
            texts = []
            for p in paragraphs:
                text = re.sub(r'<[^>]+>', ' ', p)
                text = re.sub(r'\s+', ' ', text).strip()
                if len(text) > 50:
                    texts.append(text)
            if texts:
                return "\n\n".join(texts)

        return None

    def fetch_full_text(
        self,
        pmid: str,
        doi: Optional[str] = None,
        pmc_id: Optional[str] = None,
        abstract: str = ""
    ) -> FullTextResult:
        """
        Attempt to fetch full text from available sources.

        Args:
            pmid: PubMed ID
            doi: DOI if available
            pmc_id: PMC ID if available
            abstract: Fallback abstract text

        Returns:
            FullTextResult with text and source information
        """
        # Try PMC first (most reliable free source)
        if pmc_id:
            print(f"    Trying PMC ({pmc_id})...")
            text = self._fetch_from_pmc(pmc_id)
            if text:
                return FullTextResult(
                    text=text,
                    source="pmc",
                    url=f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_id.replace('PMC', '')}/",
                    is_full_text=True
                )

        # Try Unpaywall
        if doi:
            print(f"    Trying Unpaywall...")
            time.sleep(0.1)  # Be polite to Unpaywall
            result = self._fetch_from_unpaywall(doi)
            if result:
                text, url = result
                return FullTextResult(
                    text=text,
                    source="unpaywall",
                    url=url,
                    is_full_text=True
                )

        # Try publisher with proxy
        if doi and self.proxy_config.get("enabled"):
            print(f"    Trying publisher via proxy...")
            result = self._fetch_from_publisher(doi)
            if result:
                text, url = result
                return FullTextResult(
                    text=text,
                    source="publisher",
                    url=url,
                    is_full_text=True
                )

        # Fall back to abstract
        return FullTextResult(
            text=abstract,
            source=None,
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            is_full_text=False
        )

    def fetch_pmc_id(self, pmid: str) -> Optional[str]:
        """
        Look up PMC ID for a given PMID.

        Args:
            pmid: PubMed ID

        Returns:
            PMC ID or None
        """
        try:
            url = f"{self.PMC_BASE}/elink.fcgi"
            params = {
                "dbfrom": "pubmed",
                "db": "pmc",
                "id": pmid,
                "retmode": "json"
            }

            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()

            linksets = data.get("linksets", [])
            if linksets:
                linksetdbs = linksets[0].get("linksetdbs", [])
                for lsdb in linksetdbs:
                    if lsdb.get("dbto") == "pmc":
                        links = lsdb.get("links", [])
                        if links:
                            return f"PMC{links[0]}"

        except requests.RequestException:
            pass

        return None
