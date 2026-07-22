"""
S&P Dow Jones Indices Press Release Scraper
Monitors S&P 100, 500, 400, 600 and Dow Industrial changes
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import List, Dict, Any
import logging
import re

logger = logging.getLogger(__name__)


class SPScraper:
    """Scrapes S&P Dow Jones Indices press releases"""
    
    # Press release feed URLs
    FEEDS = {
        'sp100': 'https://www.prnewswire.com/news/s%26p-dow-jones-indices/',
        'sp500': 'https://www.prnewswire.com/news/s%26p-dow-jones-indices/',
        'sp400': 'https://www.prnewswire.com/news/s%26p-dow-jones-indices/',
        'sp600': 'https://www.prnewswire.com/news/s%26p-dow-jones-indices/',
        'dow': 'https://www.prnewswire.com/news/s%26p-dow-jones-indices/',
    }
    
    # Index name mappings
    INDEX_NAMES = {
        'sp100': 'S&P 100',
        'sp500': 'S&P 500',
        'sp400': 'S&P 400',
        'sp600': 'S&P 600',
        'dow': 'Dow Industrial',
    }
    
    def __init__(self, index_type: str = 'sp500'):
        """Initialize scraper for specific index"""
        self.index_type = index_type
        self.index_name = self.INDEX_NAMES.get(index_type, 'S&P 500')
        self.feed_url = self.FEEDS.get(index_type)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def scrape(self) -> List[Dict[str, Any]]:
        """Scrape press releases for index changes"""
        try:
            logger.info(f"Scraping {self.index_name} from {self.feed_url}")
            
            response = self.session.get(self.feed_url, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            changes = []
            
            # Find all press release links
            press_releases = soup.find_all('a', {'class': 'newsHeadline'})
            
            # Check recent releases (last 7 days)
            cutoff_date = datetime.now() - timedelta(days=7)
            
            for pr in press_releases[:20]:  # Check first 20 recent releases
                try:
                    title = pr.get_text(strip=True)
                    link = pr.get('href', '')
                    
                    # Filter for index change announcements
                    if not self._is_index_change_announcement(title):
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
    
    def _is_index_change_announcement(self, title: str) -> bool:
        """Check if title indicates an index change announcement"""
        keywords = [
            'announces changes',
            'announces additions',
            'announces deletions',
            'announces removal',
            'index changes',
            'constituent changes',
            'will replace',
            'effective',
        ]
        
        title_lower = title.lower()
        return any(keyword in title_lower for keyword in keywords)
    
    def _extract_changes_from_url(self, url: str) -> List[Dict[str, Any]]:
        """Extract specific changes from a press release URL"""
        try:
            if not url.startswith('http'):
                url = 'https://www.prnewswire.com' + url
            
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
            removals = self._parse_company_list(text, 'removed|removal|will be removed|deleted')
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
        
        # Pattern: Company Name (TICKER)
        pattern = r'([A-Z][A-Za-z\s&\.\-]+?)\s*\(([A-Z]{1,5})\)'
        
        matches = re.finditer(pattern, text)
        for match in matches:
            name = match.group(1).strip()
            ticker = match.group(2).strip()
            
            # Basic validation
            if len(ticker) <= 5 and len(name) > 2:
                companies.append({
                    'name': name,
                    'ticker': ticker,
                })
        
        return companies
    
    def close(self):
        """Close session"""
        self.session.close()
