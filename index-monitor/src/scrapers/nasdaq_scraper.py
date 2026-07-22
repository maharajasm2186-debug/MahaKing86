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
    
    # Press release feed URLs (multiple options to avoid 403 errors)
    FEED_URLS = [
        'https://www.nasdaq.com/news-and-insights/news-releases',
        'https://ir.nasdaq.com/news-releases/',
        'https://www.prnewswire.com/news/nasdaq/',
    ]
    
    def __init__(self):
        """Initialize Nasdaq scraper"""
        self.index_name = 'Nasdaq-100'
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Referer': 'https://www.nasdaq.com/',
        })
    
    def scrape(self) -> List[Dict[str, Any]]:
        """Scrape Nasdaq-100 index changes"""
        try:
            logger.info(f"Scraping {self.index_name}")
            
            changes = []
            
            # Try each feed URL
            for feed_url in self.FEED_URLS:
                try:
                    logger.info(f"Trying feed: {feed_url}")
                    response = self.session.get(feed_url, timeout=15)
                    response.raise_for_status()
                    
                    feed_changes = self._parse_feed(response.content, feed_url)
                    if feed_changes:
                        changes.extend(feed_changes)
                        break  # Success, stop trying other feeds
                except requests.exceptions.RequestException as e:
                    logger.debug(f"Error fetching {feed_url}: {str(e)}")
                    continue
            
            logger.info(f"Found {len(changes)} changes for {self.index_name}")
            return changes
            
        except Exception as e:
            logger.error(f"Error scraping {self.index_name}: {str(e)}")
            return []
    
    def _parse_feed(self, content: bytes, feed_url: str) -> List[Dict[str, Any]]:
        """Parse feed content for changes"""
        try:
            soup = BeautifulSoup(content, 'html.parser')
            changes = []
            
            # Find all press release links - try multiple selectors
            press_releases = []
            
            selectors = [
                'a.newsHeadline',
                'a.news-headline',
                'h3 a',
                'div.news-item a',
                'article a',
                'a[href*="news"]',
                'a[href*="press"]',
            ]
            
            for selector in selectors:
                press_releases.extend(soup.select(selector))
            
            # Remove duplicates
            press_releases = list(set(press_releases))
            
            for pr in press_releases[:50]:  # Check first 50 recent releases
                try:
                    title = pr.get_text(strip=True)
                    link = pr.get('href', '')
                    
                    # Skip if no title or link
                    if not title or not link:
                        continue
                    
                    # Filter for Nasdaq-100 index change announcements
                    keywords = [
                        'nasdaq-100',
                        'nasdaq 100',
                        'index change',
                        'constituent',
                        'added to',
                        'removed from',
                    ]
                    
                    title_lower = title.lower()
                    if not any(keyword in title_lower for keyword in keywords):
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
            logger.warning(f"Error parsing feed: {str(e)}")
            return []
    
    def _extract_changes_from_url(self, url: str) -> List[Dict[str, Any]]:
        """Extract specific changes from a press release URL"""
        try:
            if not url.startswith('http'):
                # Handle relative URLs
                if url.startswith('/'):
                    url = 'https://www.nasdaq.com' + url
                else:
                    url = 'https://ir.nasdaq.com' + url
            
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
        
        # Pattern 1: Company Name (TICKER) or Company Name, Inc. (TICKER)
        pattern1 = r'([A-Z][A-Za-z\s&\.\,\-]+?)\s*\(([A-Z]{1,5})\)'
        
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
                        # Remove trailing punctuation and common suffixes
                        name = re.sub(r',\s*Inc\.\s*$|,\s*Corp\.\s*$|,\s*Ltd\.\s*$', '', name)
                        
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
