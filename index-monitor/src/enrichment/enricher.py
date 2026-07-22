"""
Enrichment service for company metadata
Adds CIK code and GICS industry classification
"""

import requests
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Any
import logging
import json
from pathlib import Path

logger = logging.getLogger(__name__)


class Enricher:
    """Enriches company data with metadata"""
    
    # SEC EDGAR API endpoints
    SEC_TICKERS_URL = 'https://www.sec.gov/files/company_tickers.json'
    
    def __init__(self, config):
        """Initialize enricher"""
        self.config = config
        self.cache_dir = Path('data/cache')
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / 'sec_tickers_cache.json'
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self._load_sec_cache()
    
    def _load_sec_cache(self):
        """Load SEC tickers cache from file"""
        try:
            if self.cache_file.exists():
                with open(self.cache_file, 'r') as f:
                    self.sec_cache = json.load(f)
                logger.info(f"Loaded SEC cache with {len(self.sec_cache)} entries")
            else:
                self.sec_cache = {}
        except Exception as e:
            logger.warning(f"Error loading SEC cache: {str(e)}")
            self.sec_cache = {}
    
    def _save_sec_cache(self):
        """Save SEC tickers cache to file"""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(self.sec_cache, f)
        except Exception as e:
            logger.warning(f"Error saving SEC cache: {str(e)}")
    
    def _fetch_sec_tickers(self) -> Dict[str, Any]:
        """Fetch SEC tickers from official source"""
        try:
            logger.info("Fetching SEC tickers from official source...")
            response = self.session.get(self.SEC_TICKERS_URL, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            # Convert to dict with ticker as key
            tickers_dict = {}
            for entry in data.values():
                ticker = entry.get('ticker', '').upper()
                if ticker:
                    tickers_dict[ticker] = entry
            
            return tickers_dict
            
        except Exception as e:
            logger.error(f"Error fetching SEC tickers: {str(e)}")
            return {}
    
    def _get_sec_info(self, ticker: str) -> Dict[str, Any]:
        """Get SEC info for ticker (CIK, company name)"""
        try:
            ticker = ticker.upper()
            
            # Check cache first
            if ticker in self.sec_cache:
                cached = self.sec_cache[ticker]
                if 'cached_at' in cached:
                    cached_date = datetime.fromisoformat(cached['cached_at'])
                    if datetime.now() - cached_date < timedelta(days=30):
                        logger.info(f"Using cached SEC info for {ticker}")
                        return cached
            
            # Fetch fresh data
            sec_tickers = self._fetch_sec_tickers()
            
            if ticker in sec_tickers:
                entry = sec_tickers[ticker]
                info = {
                    'cik_code': str(entry.get('cik_str', '')).zfill(10),
                    'company_name': entry.get('title', ''),
                    'cached_at': datetime.now().isoformat()
                }
                
                # Cache it
                self.sec_cache[ticker] = info
                self._save_sec_cache()
                
                logger.info(f"Found SEC info for {ticker}: CIK {info['cik_code']}")
                return info
            else:
                logger.warning(f"No SEC info found for {ticker}")
                return {}
                
        except Exception as e:
            logger.error(f"Error getting SEC info for {ticker}: {str(e)}")
            return {}
    
    def _get_gics_info(self, ticker: str) -> Dict[str, str]:
        """Get GICS sector and industry for ticker"""
        try:
            # Try Yahoo Finance API
            url = f'https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}'
            params = {'modules': 'assetProfile'}
            
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            asset_profile = data.get('quoteSummary', {}).get('result', [{}])[0].get('assetProfile', {})
            
            return {
                'gics_sector': asset_profile.get('sector', 'Unknown'),
                'gics_industry': asset_profile.get('industry', 'Unknown'),
            }
            
        except Exception as e:
            logger.warning(f"Error getting GICS info for {ticker}: {str(e)}")
            return {
                'gics_sector': 'Unknown',
                'gics_industry': 'Unknown',
            }
    
    def enrich(self, change: Dict[str, Any]) -> Dict[str, Any]:
        """Enrich a change record with metadata"""
        try:
            ticker = change.get('ticker', '').upper()
            
            if not ticker:
                logger.warning("Change record missing ticker")
                return change
            
            logger.info(f"Enriching {ticker}...")
            
            # Get SEC info (CIK)
            if self.config.enrichment.get('enable_sec_lookup', True):
                sec_info = self._get_sec_info(ticker)
                change.update(sec_info)
            
            # Get GICS info
            if self.config.enrichment.get('enable_gics_lookup', True):
                gics_info = self._get_gics_info(ticker)
                change.update(gics_info)
            
            # Ensure company_name is set
            if not change.get('company_name'):
                change['company_name'] = ticker
            
            # Ensure effective_date is set
            if not change.get('effective_date'):
                change['effective_date'] = change.get('announcement_date')
            
            return change
            
        except Exception as e:
            logger.error(f"Error enriching change: {str(e)}")
            return change
    
    def close(self):
        """Clean up resources"""
        self.session.close()
