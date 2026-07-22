#!/usr/bin/env python3
"""
Index Monitor - Main Entry Point
Monitors S&P, Russell, Nasdaq-100, and Dow indices for constituent changes
"""

import sys
import logging
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from state.database import Database
from scrapers.sp_scraper import SPScraper
from scrapers.russell_scraper import RussellScraper
from scrapers.nasdaq_scraper import NasdaqScraper
from enrichment.enricher import Enricher
from notification.email_client import EmailClient
from utils.logger import setup_logger

logger = setup_logger(__name__)


class IndexMonitor:
    """Main orchestrator for index monitoring"""
    
    def __init__(self, config_path: str = "config.yaml"):
        """Initialize the monitor"""
        self.config = Config(config_path)
        self.db = Database(self.config.db_path)
        self.enricher = Enricher(self.config)
        self.email_client = EmailClient(self.config)
        
        # Initialize scrapers
        self.scrapers = {}
        if self.config.indices.get('sp100'):
            self.scrapers['S&P 100'] = SPScraper('sp100')
        if self.config.indices.get('sp500'):
            self.scrapers['S&P 500'] = SPScraper('sp500')
        if self.config.indices.get('sp400'):
            self.scrapers['S&P 400'] = SPScraper('sp400')
        if self.config.indices.get('sp600'):
            self.scrapers['S&P 600'] = SPScraper('sp600')
        if self.config.indices.get('dow_industrial'):
            self.scrapers['Dow Industrial'] = SPScraper('dow')
        if self.config.indices.get('nasdaq100'):
            self.scrapers['Nasdaq-100'] = NasdaqScraper()
        if self.config.indices.get('russell3000'):
            self.scrapers['Russell 3000'] = RussellScraper('r3000')
        if self.config.indices.get('russell2000'):
            self.scrapers['Russell 2000'] = RussellScraper('r2000')
        if self.config.indices.get('russell1000'):
            self.scrapers['Russell 1000'] = RussellScraper('r1000')
    
    def run(self):
        """Execute the monitoring cycle"""
        logger.info("=" * 80)
        logger.info(f"Starting Index Monitor run at {datetime.now().isoformat()}")
        logger.info("=" * 80)
        
        all_changes = []
        
        # Scrape each index
        for index_name, scraper in self.scrapers.items():
            try:
                logger.info(f"Scraping {index_name}...")
                changes = scraper.scrape()
                
                if changes:
                    logger.info(f"Found {len(changes)} changes for {index_name}")
                    for change in changes:
                        change['index_name'] = index_name
                    all_changes.extend(changes)
                else:
                    logger.info(f"No changes found for {index_name}")
                    
            except Exception as e:
                logger.error(f"Error scraping {index_name}: {str(e)}", exc_info=True)
                continue
        
        if not all_changes:
            logger.info("No new changes detected across all indices")
            return
        
        logger.info(f"Total changes detected: {len(all_changes)}")
        
        # Enrich changes with metadata
        enriched_changes = []
        for change in all_changes:
            try:
                logger.info(f"Enriching {change.get('ticker')} ({change.get('action')})...")
                enriched = self.enricher.enrich(change)
                enriched_changes.append(enriched)
            except Exception as e:
                logger.error(f"Error enriching {change.get('ticker')}: {str(e)}", exc_info=True)
                # Still include the change, even if enrichment failed
                enriched_changes.append(change)
        
        # Store in database and check for duplicates
        new_changes = []
        for change in enriched_changes:
            try:
                if self.db.is_new_change(change):
                    self.db.insert_change(change)
                    new_changes.append(change)
                    logger.info(f"Stored new change: {change.get('ticker')} - {change.get('action')}")
                else:
                    logger.info(f"Duplicate change detected: {change.get('ticker')} - {change.get('action')}")
            except Exception as e:
                logger.error(f"Error storing change: {str(e)}", exc_info=True)
        
        if not new_changes:
            logger.info("All detected changes were duplicates")
            return
        
        logger.info(f"New changes to notify: {len(new_changes)}")
        
        # Send notifications
        try:
            if self.config.notification.get('enabled', True):
                logger.info("Sending email notification...")
                success = self.email_client.send_notification(new_changes)
                
                if success:
                    logger.info("Email notification sent successfully")
                    # Mark changes as notified
                    for change in new_changes:
                        self.db.mark_notified(change)
                else:
                    logger.error("Failed to send email notification")
            else:
                logger.info("Notifications disabled in config")
                
        except Exception as e:
            logger.error(f"Error sending notification: {str(e)}", exc_info=True)
        
        logger.info("=" * 80)
        logger.info(f"Index Monitor run completed at {datetime.now().isoformat()}")
        logger.info("=" * 80)


def main():
    """Entry point"""
    try:
        monitor = IndexMonitor()
        monitor.run()
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
