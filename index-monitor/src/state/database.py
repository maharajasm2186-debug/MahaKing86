"""
Database management for Index Monitor
Handles SQLite operations for tracking index changes
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)


class Database:
    """SQLite database manager"""
    
    def __init__(self, db_path: str = "data/changes.db"):
        """Initialize database connection"""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = None
        self.cursor = None
        self._connect()
        self._init_schema()
    
    def _connect(self):
        """Connect to database"""
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
    
    def _init_schema(self):
        """Initialize database schema"""
        # Main changes table
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS index_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                company_name TEXT,
                cik_code TEXT,
                gics_sector TEXT,
                gics_industry TEXT,
                action TEXT NOT NULL,
                index_name TEXT NOT NULL,
                effective_date DATE,
                announcement_date DATE,
                press_release_url TEXT,
                email_sent BOOLEAN DEFAULT 0,
                email_sent_date DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(ticker, action, index_name, effective_date)
            )
        """)
        
        # Notification log table
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS notification_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                change_id INTEGER NOT NULL,
                email_recipient TEXT,
                email_sent_date DATETIME,
                delivery_status TEXT,
                error_message TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(change_id) REFERENCES index_changes(id)
            )
        """)
        
        # Create indices for faster queries
        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ticker_action 
            ON index_changes(ticker, action)
        """)
        
        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_email_sent 
            ON index_changes(email_sent)
        """)
        
        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_created_at 
            ON index_changes(created_at)
        """)
        
        self.conn.commit()
        logger.info(f"Database initialized at {self.db_path}")
    
    def is_new_change(self, change: Dict[str, Any]) -> bool:
        """Check if change is new (not already in database)"""
        try:
            ticker = change.get('ticker')
            action = change.get('action')
            index_name = change.get('index_name')
            effective_date = change.get('effective_date')
            
            self.cursor.execute("""
                SELECT id FROM index_changes
                WHERE ticker = ? AND action = ? AND index_name = ? AND effective_date = ?
            """, (ticker, action, index_name, effective_date))
            
            result = self.cursor.fetchone()
            return result is None
            
        except Exception as e:
            logger.error(f"Error checking if change is new: {str(e)}")
            return True  # Assume new on error
    
    def insert_change(self, change: Dict[str, Any]) -> int:
        """Insert a new change into the database"""
        try:
            self.cursor.execute("""
                INSERT INTO index_changes (
                    ticker, company_name, cik_code, gics_sector, gics_industry,
                    action, index_name, effective_date, announcement_date,
                    press_release_url, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                change.get('ticker'),
                change.get('company_name'),
                change.get('cik_code'),
                change.get('gics_sector'),
                change.get('gics_industry'),
                change.get('action'),
                change.get('index_name'),
                change.get('effective_date'),
                change.get('announcement_date'),
                change.get('press_release_url'),
                datetime.now().isoformat(),
                datetime.now().isoformat()
            ))
            
            self.conn.commit()
            change_id = self.cursor.lastrowid
            logger.info(f"Inserted change {change_id}: {change.get('ticker')} - {change.get('action')}")
            return change_id
            
        except sqlite3.IntegrityError as e:
            logger.warning(f"Duplicate change detected: {str(e)}")
            return -1
        except Exception as e:
            logger.error(f"Error inserting change: {str(e)}")
            raise
    
    def mark_notified(self, change: Dict[str, Any]):
        """Mark a change as notified"""
        try:
            ticker = change.get('ticker')
            action = change.get('action')
            index_name = change.get('index_name')
            
            self.cursor.execute("""
                UPDATE index_changes
                SET email_sent = 1, email_sent_date = ?, updated_at = ?
                WHERE ticker = ? AND action = ? AND index_name = ? AND email_sent = 0
            """, (datetime.now().isoformat(), datetime.now().isoformat(), ticker, action, index_name))
            
            self.conn.commit()
            logger.info(f"Marked as notified: {ticker} - {action}")
            
        except Exception as e:
            logger.error(f"Error marking change as notified: {str(e)}")
    
    def get_unnotified_changes(self) -> List[Dict[str, Any]]:
        """Get all changes that haven't been notified yet"""
        try:
            self.cursor.execute("""
                SELECT * FROM index_changes
                WHERE email_sent = 0
                ORDER BY created_at DESC
            """)
            
            rows = self.cursor.fetchall()
            return [dict(row) for row in rows]
            
        except Exception as e:
            logger.error(f"Error fetching unnotified changes: {str(e)}")
            return []
    
    def get_recent_changes(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get changes from the last N days"""
        try:
            self.cursor.execute("""
                SELECT * FROM index_changes
                WHERE created_at >= datetime('now', '-' || ? || ' days')
                ORDER BY created_at DESC
            """, (days,))
            
            rows = self.cursor.fetchall()
            return [dict(row) for row in rows]
            
        except Exception as e:
            logger.error(f"Error fetching recent changes: {str(e)}")
            return []
    
    def get_changes_by_index(self, index_name: str) -> List[Dict[str, Any]]:
        """Get all changes for a specific index"""
        try:
            self.cursor.execute("""
                SELECT * FROM index_changes
                WHERE index_name = ?
                ORDER BY created_at DESC
            """, (index_name,))
            
            rows = self.cursor.fetchall()
            return [dict(row) for row in rows]
            
        except Exception as e:
            logger.error(f"Error fetching changes for {index_name}: {str(e)}")
            return []
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get database statistics"""
        try:
            self.cursor.execute("SELECT COUNT(*) as total FROM index_changes")
            total = self.cursor.fetchone()['total']
            
            self.cursor.execute("SELECT COUNT(*) as notified FROM index_changes WHERE email_sent = 1")
            notified = self.cursor.fetchone()['notified']
            
            self.cursor.execute("""
                SELECT action, COUNT(*) as count FROM index_changes
                GROUP BY action
            """)
            actions = {row['action']: row['count'] for row in self.cursor.fetchall()}
            
            self.cursor.execute("""
                SELECT index_name, COUNT(*) as count FROM index_changes
                GROUP BY index_name
            """)
            indices = {row['index_name']: row['count'] for row in self.cursor.fetchall()}
            
            return {
                'total_changes': total,
                'notified_changes': notified,
                'pending_changes': total - notified,
                'by_action': actions,
                'by_index': indices
            }
            
        except Exception as e:
            logger.error(f"Error getting statistics: {str(e)}")
            return {}
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()
