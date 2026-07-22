"""
Configuration management for Index Monitor
"""

import os
import yaml
from pathlib import Path
from typing import Dict, Any


class Config:
    """Configuration loader and manager"""
    
    def __init__(self, config_path: str = "config.yaml"):
        """Load configuration from YAML file"""
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self._validate_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")
        
        with open(self.config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        return config or {}
    
    def _validate_config(self):
        """Validate required configuration sections"""
        required_sections = ['email', 'indices', 'notification']
        for section in required_sections:
            if section not in self.config:
                raise ValueError(f"Missing required config section: {section}")
    
    @property
    def email(self) -> Dict[str, Any]:
        """Email configuration"""
        return self.config.get('email', {})
    
    @property
    def indices(self) -> Dict[str, bool]:
        """Indices to monitor"""
        return self.config.get('indices', {})
    
    @property
    def enrichment(self) -> Dict[str, Any]:
        """Enrichment configuration"""
        return self.config.get('enrichment', {})
    
    @property
    def notification(self) -> Dict[str, Any]:
        """Notification configuration"""
        return self.config.get('notification', {})
    
    @property
    def db_path(self) -> str:
        """Database file path"""
        return self.config.get('database', {}).get('path', 'data/changes.db')
    
    @property
    def log_level(self) -> str:
        """Logging level"""
        return self.config.get('logging', {}).get('level', 'INFO')
    
    @property
    def log_file(self) -> str:
        """Log file path"""
        return self.config.get('logging', {}).get('file', 'logs/monitor.log')
    
    def get_smtp_config(self) -> Dict[str, Any]:
        """Get SMTP configuration with environment variable substitution"""
        email_config = self.email
        
        # Support environment variables for sensitive data
        smtp_config = {
            'server': email_config.get('smtp_server', 'smtp.gmail.com'),
            'port': email_config.get('smtp_port', 587),
            'sender_email': email_config.get('sender_email') or os.getenv('SMTP_SENDER_EMAIL'),
            'sender_password': email_config.get('sender_password') or os.getenv('SMTP_PASSWORD'),
            'recipient': email_config.get('recipient', 'maharajasm2186@gmail.com'),
        }
        
        if not smtp_config['sender_email']:
            raise ValueError("SMTP sender email not configured")
        if not smtp_config['sender_password']:
            raise ValueError("SMTP password not configured (set SMTP_PASSWORD env var)")
        
        return smtp_config
    
    def get_sec_api_key(self) -> str:
        """Get SEC API key if configured"""
        return self.enrichment.get('sec_api_key') or os.getenv('SEC_API_KEY', '')
    
    def get_yahoo_api_key(self) -> str:
        """Get Yahoo Finance API key if configured"""
        return self.enrichment.get('yahoo_api_key') or os.getenv('YAHOO_API_KEY', '')
