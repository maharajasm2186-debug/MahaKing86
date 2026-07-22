"""
Email notification service
Sends formatted email notifications for index changes
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Any
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class EmailClient:
    """Sends email notifications"""
    
    def __init__(self, config):
        """Initialize email client"""
        self.config = config
        self.smtp_config = config.get_smtp_config()
    
    def send_notification(self, changes: List[Dict[str, Any]]) -> bool:
        """Send email notification for changes"""
        try:
            if not changes:
                logger.warning("No changes to notify")
                return False
            
            # Group changes by index
            changes_by_index = {}
            for change in changes:
                index = change.get('index_name', 'Unknown')
                if index not in changes_by_index:
                    changes_by_index[index] = {'ADD': [], 'REMOVE': []}
                
                action = change.get('action', 'UNKNOWN')
                changes_by_index[index][action].append(change)
            
            # Generate HTML email
            html_body = self._generate_html_body(changes_by_index)
            
            # Send email
            return self._send_email(html_body)
            
        except Exception as e:
            logger.error(f"Error sending notification: {str(e)}")
            return False
    
    def _generate_html_body(self, changes_by_index: Dict[str, Dict[str, List]]) -> str:
        """Generate HTML email body"""
        html = """
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; }
                .header { background-color: #1f77b4; color: white; padding: 20px; }
                .index-section { margin: 20px 0; }
                .index-title { background-color: #e8f4f8; padding: 10px; font-weight: bold; }
                table { border-collapse: collapse; width: 100%; margin: 10px 0; }
                th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
                th { background-color: #f2f2f2; }
                .add { background-color: #d4edda; }
                .remove { background-color: #f8d7da; }
                .footer { margin-top: 20px; font-size: 12px; color: #666; }
            </style>
        </head>
        <body>
            <div class="header">
                <h1>📊 Index Constituent Changes</h1>
                <p>Notification generated on """ + datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC") + """</p>
            </div>
        """
        
        for index_name, actions in changes_by_index.items():
            html += f"""
            <div class="index-section">
                <div class="index-title">{index_name}</div>
            """
            
            # Additions
            if actions['ADD']:
                html += """
                <h3>✅ Companies Added</h3>
                <table>
                    <tr>
                        <th>Ticker</th>
                        <th>Company Name</th>
                        <th>CIK Code</th>
                        <th>GICS Sector</th>
                        <th>GICS Industry</th>
                    </tr>
                """
                for change in actions['ADD']:
                    html += f"""
                    <tr class="add">
                        <td><strong>{change.get('ticker', 'N/A')}</strong></td>
                        <td>{change.get('company_name', 'N/A')}</td>
                        <td>{change.get('cik_code', 'N/A')}</td>
                        <td>{change.get('gics_sector', 'N/A')}</td>
                        <td>{change.get('gics_industry', 'N/A')}</td>
                    </tr>
                    """
                html += "</table>"
            
            # Removals
            if actions['REMOVE']:
                html += """
                <h3>❌ Companies Removed</h3>
                <table>
                    <tr>
                        <th>Ticker</th>
                        <th>Company Name</th>
                        <th>CIK Code</th>
                        <th>GICS Sector</th>
                        <th>GICS Industry</th>
                    </tr>
                """
                for change in actions['REMOVE']:
                    html += f"""
                    <tr class="remove">
                        <td><strong>{change.get('ticker', 'N/A')}</strong></td>
                        <td>{change.get('company_name', 'N/A')}</td>
                        <td>{change.get('cik_code', 'N/A')}</td>
                        <td>{change.get('gics_sector', 'N/A')}</td>
                        <td>{change.get('gics_industry', 'N/A')}</td>
                    </tr>
                    """
                html += "</table>"
            
            html += "</div>"
        
        html += """
            <div class="footer">
                <p>This is an automated notification from Index Monitor.</p>
                <p>For more information, visit the GitHub repository.</p>
            </div>
        </body>
        </html>
        """
        
        return html
    
    def _send_email(self, html_body: str) -> bool:
        """Send email via SMTP"""
        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = '📊 Index Constituent Changes Detected'
            msg['From'] = self.smtp_config['sender_email']
            msg['To'] = self.smtp_config['recipient']
            
            # Attach HTML
            msg.attach(MIMEText(html_body, 'html'))
            
            # Send email
            logger.info(f"Connecting to SMTP server {self.smtp_config['server']}:{self.smtp_config['port']}")
            
            with smtplib.SMTP(self.smtp_config['server'], self.smtp_config['port']) as server:
                server.starttls()
                server.login(self.smtp_config['sender_email'], self.smtp_config['sender_password'])
                server.send_message(msg)
            
            logger.info(f"Email sent successfully to {self.smtp_config['recipient']}")
            return True
            
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP authentication failed: {str(e)}")
            return False
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Error sending email: {str(e)}")
            return False
