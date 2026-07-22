"""
Nasdaq Global Indexes Scraper
Monitors Nasdaq-100 quarterly changes
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Any
import logging
import re

logger = logging.getLogger(__name__)


class NasdaqScraper:
    """Scrapes Nasdaq Global Indexes announcements"""
    
    # Press release feed URL
    FEED_URL = 'https://ir.nasdaq.com/news-releases/'
    
    def __init__(self):
        """Initialize Nasdaq scraper"""
        self.index_name = 'Nasdaq-100'
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def scrape(self) -> List[Dict[str, Any]]:
        """Scrape Nasdaq-100 index changes"""
        try:
            logger.info(f"Scraping {self.index_name} from {self.FEED_URL}")
            
            response = self.session.get(self.FEED_URL, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            changes = []
            
            # Find all press release links
            press_releases = soup.find_all('a')
            
            for pr in press_releases[:30]:  # Check first 30 recent releases
                try:
                    title = pr.get_text(strip=True)
                    link = pr.get('href', '')
                    
                    # Filter for Nasdaq-100 index change announcements
                    if 'nasdaq-100' not in title.lower() or 'change' not in title.lower():
                        continue
                    
                    logger.info(f"Found potential announcement: {title[:100]}")
                    
                    # Extract changes from the press release
                    pr_changes = self._extract_changes_from_url(link)
                    if pr_changes:
                        changes.extend(pr_changes)
                        
                except Exception as e:
                    logger.warning(f"Error processing press release: {str(e)}")
                    continue
            
            logger.info(f"Found {len(changes)} changes for {self.index_name}")
            return changes
            
        except Exception as e:
            logger.error(f"Error scraping {self.index_name}: {str(e)}")
            return []
    
    def _extract_changes_from_url(self, url: str) -> List[Dict[str, Any]]:
        """Extract specific changes from a press release URL"""
        try:
            if not url.startswith('http'):
                url = 'https://ir.nasdaq.com' + url
            
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            text = soup.get_text()
            
            changes = []
            
            # Parse additions
            additions = self._parse_company_list(text, 'added|addition|will be added')
            for company in additions:
                changes.append({
                    'ticker': company.get('ticker'),
                    'company_name': company.get('name'),
                    'action': 'ADD',
                    'announcement_date': datetime.now().date().isoformat(),
                    'press_release_url': url,
                })
            
            # Parse removals
            removals = self._parse_company_list(text, 'removed|removal|will be removed')
            for company in removals:
                changes.append({
                    'ticker': company.get('ticker'),
                    'company_name': company.get('name'),
                    'action': 'REMOVE',
                    'announcement_date': datetime.now().date().isoformat(),
                    'press_release_url': url,
                })
            
            return changes
            
        except Exception as e:
            logger.warning(f"Error extracting changes from {url}: {str(e)}")
            return []
    
    def _parse_company_list(self, text: str, action_pattern: str) -> List[Dict[str, str]]:
        """Parse company names and tickers from text"""
        companies = []
        
        # Pattern: Company Name (TICKER) or Company Name, Inc. (TICKER)
        pattern = r'([A-Z][A-Za-z\s&\.\,\-]+?)\s*\(([A-Z]{1,5})\)'
        
        matches = re.finditer(pattern, text)
        for match in matches:
            name = match.group(1).strip()
            ticker = match.group(2).strip()
            
            # Basic validation
            if len(ticker) <= 5 and len(name) > 2:
                # Remove trailing punctuation and common suffixes
                name = re.sub(r',\s*Inc\.\s*$|,\s*Corp\.\s*$|,\s*Ltd\.\s*$', '', name)
                
                companies.append({
                    'name': name,
                    'ticker': ticker,
                })
        
        return companies
    
    def close(self):
        """Close session"""
        self.session.close()
