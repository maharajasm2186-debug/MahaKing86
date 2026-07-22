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
    
    # Official S&P Dow Jones Indices press release URLs
    FEEDS = {
        'sp100': 'https://www.spglobal.com/spdji/en/media-center/news-announcements/?search=S%26P+100',
        'sp500': 'https://www.spglobal.com/spdji/en/media-center/news-announcements/?search=S%26P+500',
        'sp400': 'https://www.spglobal.com/spdji/en/media-center/news-announcements/?search=S%26P+400',
        'sp600': 'https://www.spglobal.com/spdji/en/media-center/news-announcements/?search=S%26P+600',
        'dow': 'https://www.spglobal.com/spdji/en/media-center/news-announcements/?search=Dow',
    }
    
    # Alternative feeds from press release aggregators
    ALT_FEEDS = {
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
        self.alt_feed_url = self.ALT_FEEDS.get(index_type)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
    
    def scrape(self) -> List[Dict[str, Any]]:
        """Scrape press releases for index changes"""
        try:
            logger.info(f"Scraping {self.index_name}")
            
            changes = []
            
            # Try primary feed first
            logger.info(f"Trying primary feed: {self.feed_url}")
            primary_changes = self._scrape_feed(self.feed_url)
            changes.extend(primary_changes)
            
            # If no changes found, try alternative feed
            if not changes and self.alt_feed_url:
                logger.info(f"Trying alternative feed: {self.alt_feed_url}")
                alt_changes = self._scrape_feed(self.alt_feed_url)
                changes.extend(alt_changes)
            
            logger.info(f"Found {len(changes)} changes for {self.index_name}")
            return changes
            
        except Exception as e:
            logger.error(f"Error scraping {self.index_name}: {str(e)}")
            return []
    
    def _scrape_feed(self, feed_url: str) -> List[Dict[str, Any]]:
        """Scrape a specific feed URL"""
        try:
            response = self.session.get(feed_url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            changes = []
            
            # Find all press release links - try multiple selectors
            press_releases = []
            
            # Try different CSS selectors for press releases
            selectors = [
                'a.newsHeadline',
                'a.news-headline',
                'h3 a',
                'div.news-item a',
                'article a',
                'a[href*="news"]',
            ]
            
            for selector in selectors:
                press_releases.extend(soup.select(selector))
            
            # Remove duplicates
            press_releases = list(set(press_releases))
            
            # Check recent releases (last 30 days)
            cutoff_date = datetime.now() - timedelta(days=30)
            
            for pr in press_releases[:50]:  # Check first 50 recent releases
                try:
                    title = pr.get_text(strip=True)
                    link = pr.get('href', '')
                    
                    # Skip if no title or link
                    if not title or not link:
                        continue
                    
                    # Filter for index change announcements
                    if not self._is_index_change_announcement(title):
                        continue
                    
                    logger.info(f"Found potential announcement: {title[:100]}")
                    
                    # Extract changes from the press release
                    pr_changes = self._extract_changes_from_url(link)
                    if pr_changes:
                        changes.extend(pr_changes)
                        
                except Exception as e:
                    logger.debug(f"Error processing press release: {str(e)}")
                    continue
            
            return changes
            
        except Exception as e:
            logger.warning(f"Error scraping feed {feed_url}: {str(e)}")
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
            'added to',
            'removed from',
            'index addition',
            'index deletion',
            'index reconstitution',
        ]
        
        title_lower = title.lower()
        return any(keyword in title_lower for keyword in keywords)
    
    def _extract_changes_from_url(self, url: str) -> List[Dict[str, Any]]:
        """Extract specific changes from a press release URL"""
        try:
            if not url.startswith('http'):
                # Handle relative URLs
                if url.startswith('/'):
                    url = 'https://www.spglobal.com' + url
                else:
                    url = 'https://www.prnewswire.com' + url
            
            logger.debug(f"Fetching press release: {url}")
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            text = soup.get_text()
            
            changes = []
            
            # Parse additions
            additions = self._parse_company_list(text, 'added|addition|will be added|added to')
            for company in additions:
                if company.get('ticker'):
                    changes.append({
                        'ticker': company.get('ticker'),
                        'company_name': company.get('name'),
                        'action': 'ADD',
                        'announcement_date': datetime.now().date().isoformat(),
                        'press_release_url': url,
                    })
            
            # Parse removals
            removals = self._parse_company_list(text, 'removed|removal|will be removed|deleted|removed from')
            for company in removals:
                if company.get('ticker'):
                    changes.append({
                        'ticker': company.get('ticker'),
                        'company_name': company.get('name'),
                        'action': 'REMOVE',
                        'announcement_date': datetime.now().date().isoformat(),
                        'press_release_url': url,
                    })
            
            return changes
            
        except requests.exceptions.RequestException as e:
            logger.debug(f"Network error fetching {url}: {str(e)}")
            return []
        except Exception as e:
            logger.debug(f"Error extracting changes from {url}: {str(e)}")
            return []
    
    def _parse_company_list(self, text: str, action_pattern: str) -> List[Dict[str, str]]:
        """Parse company names and tickers from text"""
        companies = []
        
        # Pattern 1: Company Name (TICKER)
        pattern1 = r'([A-Z][A-Za-z\s&\.\-]+?)\s*\(([A-Z]{1,5})\)'
        
        # Pattern 2: TICKER - Company Name
        pattern2 = r'([A-Z]{1,5})\s*[-–]\s*([A-Z][A-Za-z\s&\.\-]+?)(?:\n|,|;|$)'
        
        # Pattern 3: Company Name ticker TICKER
        pattern3 = r'([A-Z][A-Za-z\s&\.\-]+?)\s+(?:ticker|symbol)?\s*([A-Z]{1,5})(?:\s|,|;|$)'
        
        for pattern in [pattern1, pattern2, pattern3]:
            matches = re.finditer(pattern, text, re.MULTILINE)
            for match in matches:
                try:
                    if pattern == pattern2:
                        ticker = match.group(1).strip()
                        name = match.group(2).strip()
                    else:
                        name = match.group(1).strip()
                        ticker = match.group(2).strip()
                    
                    # Basic validation
                    if 1 <= len(ticker) <= 5 and len(name) > 2 and len(name) < 100:
                        # Avoid duplicates
                        if not any(c['ticker'] == ticker for c in companies):
                            companies.append({
                                'name': name,
                                'ticker': ticker,
                            })
                except (IndexError, AttributeError):
                    continue
        
        return companies
    
    def close(self):
        """Close session"""
        self.session.close()
