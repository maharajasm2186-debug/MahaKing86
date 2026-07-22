# Index Monitor

A comprehensive, forward-looking monitoring system that detects constituent changes across major US equity indices and delivers immediate email notifications with enriched company metadata.

## Features

- **Multi-Index Monitoring**: Tracks S&P 100/500/400/600, Nasdaq-100, Russell 3000/2000/1000, and Dow Industrial
- **Real-Time Detection**: Monitors official press releases from index providers
- **Automatic Enrichment**: Adds company metadata including CIK codes and GICS industry classification
- **Email Notifications**: Sends formatted HTML emails to specified recipient
- **State Management**: SQLite database tracks all changes and prevents duplicate notifications
- **Audit Trail**: Complete historical record of all detected changes
- **GitHub Integration**: Automated scheduling via GitHub Actions, change logs stored in repository
- **Error Resilience**: Automatic retry logic and comprehensive error handling

## Monitored Indices

| Index | Provider | Update Frequency | Notification Lead Time |
|-------|----------|------------------|------------------------|
| S&P 100 | S&P Dow Jones Indices | Ad-hoc | 1-2 business days |
| S&P 500 | S&P Dow Jones Indices | Ad-hoc | 1-2 business days |
| S&P 400 | S&P Dow Jones Indices | Ad-hoc | 1-2 business days |
| S&P 600 | S&P Dow Jones Indices | Ad-hoc | 1-2 business days |
| Nasdaq-100 | Nasdaq Global Indexes | Quarterly | 1-2 weeks prior |
| Russell 3000 | FTSE Russell | Semi-annual (June) | 1 month prior |
| Russell 2000 | FTSE Russell | Semi-annual (June) | 1 month prior |
| Russell 1000 | FTSE Russell | Semi-annual (June) | 1 month prior |
| Dow Industrial | S&P Dow Jones Indices | Ad-hoc | 1-2 business days |

## Data Collected

For each detected change, the system captures:

- **Company Information**: Name, ticker symbol
- **SEC Data**: CIK code (from SEC EDGAR)
- **Industry Classification**: GICS sector and industry
- **Change Details**: Action (ADD/REMOVE), index name, effective date
- **Source Information**: Press release URL and announcement date

## Installation

### Prerequisites

- Python 3.8+
- Git
- GitHub account with repository access

### Local Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/yourusername/index-monitor.git
   cd index-monitor
   ```

2. **Create virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Create configuration file**:
   ```bash
   cp config.example.yaml config.yaml
   ```

5. **Edit config.yaml** with your settings:
   ```yaml
   email:
     smtp_server: smtp.gmail.com
     smtp_port: 587
     sender_email: your-email@gmail.com
     sender_password: your-app-password
     recipient: maharajasm2186@gmail.com
   ```

## Configuration

### Email Setup (Gmail)

1. **Enable 2-Factor Authentication** on your Google account
2. **Generate App Password**:
   - Visit https://myaccount.google.com/apppasswords
   - Select "Mail" and "Windows Computer"
   - Copy the generated 16-character password
3. **Update config.yaml** with the app password

### Environment Variables

Sensitive credentials can be set via environment variables instead of config file:

```bash
export SMTP_SENDER_EMAIL="your-email@gmail.com"
export SMTP_PASSWORD="your-app-password"
```

### Index Selection

Enable/disable specific indices in `config.yaml`:

```yaml
indices:
  sp100: true
  sp500: true
  sp400: true
  sp600: true
  nasdaq100: true
  russell3000: true
  russell2000: true
  russell1000: true
  dow_industrial: true
```

## Usage

### Local Execution

Run the monitor manually:

```bash
python -m src.main
```

### Scheduled Execution (Local)

#### On Linux/macOS (Cron):

1. **Edit crontab**:
   ```bash
   crontab -e
   ```

2. **Add schedule** (runs every 6 hours):
   ```cron
   0 0,6,12,18 * * * cd /path/to/index-monitor && python -m src.main >> logs/cron.log 2>&1
   ```

#### On Windows (Task Scheduler):

1. **Create basic task** with trigger: "Repeat every 6 hours"
2. **Action**: Start program: `python.exe`
3. **Arguments**: `-m src.main`
4. **Start in**: `/path/to/index-monitor`

### Automated Execution (GitHub Actions)

The repository includes a GitHub Actions workflow that automatically:

- Runs every 6 hours (0:00, 6:00, 12:00, 18:00 UTC)
- Detects index changes
- Sends email notifications
- Commits change logs to repository
- Creates issues on errors

#### Setup GitHub Actions

1. **Add secrets to repository** (Settings → Secrets and variables → Actions):
   - `SMTP_SENDER_EMAIL`: Your Gmail address
   - `SMTP_PASSWORD`: Your Gmail app password

2. **Workflow runs automatically** on the schedule

3. **View runs**: Actions tab → Index Monitor workflow

## Email Notifications

### Format

Emails are sent in HTML format with:

- **Header**: Timestamp and summary
- **By Index**: Changes grouped by index
- **By Action**: Separate tables for additions and removals
- **Columns**: Ticker, Company Name, CIK Code, GICS Sector, GICS Industry
- **Color Coding**: Green for additions, red for removals

### Example

```
📊 Index Constituent Changes

S&P 500
✅ Companies Added
| Ticker | Company Name | CIK Code | GICS Sector | GICS Industry |
|--------|--------------|----------|-------------|---------------|
| ACME   | ACME Corp    | 0000001234 | Technology | Software |

❌ Companies Removed
| Ticker | Company Name | CIK Code | GICS Sector | GICS Industry |
|--------|--------------|----------|-------------|---------------|
| OLD    | Old Company  | 0000005678 | Industrials | Machinery |
```

## Database

### Schema

**index_changes table**:
- `id`: Unique identifier
- `ticker`: Stock ticker symbol
- `company_name`: Full company name
- `cik_code`: SEC CIK code (10-digit)
- `gics_sector`: GICS sector classification
- `gics_industry`: GICS industry classification
- `action`: 'ADD' or 'REMOVE'
- `index_name`: Index name (e.g., 'S&P 500')
- `effective_date`: Date change takes effect
- `announcement_date`: Date of announcement
- `press_release_url`: Link to press release
- `email_sent`: Boolean flag
- `email_sent_date`: Timestamp of notification
- `created_at`: Record creation timestamp
- `updated_at`: Record update timestamp

### Accessing the Database

```bash
sqlite3 data/changes.db

# View recent changes
SELECT ticker, action, index_name, created_at FROM index_changes ORDER BY created_at DESC LIMIT 10;

# Get statistics
SELECT action, COUNT(*) FROM index_changes GROUP BY action;

# Find changes for specific index
SELECT * FROM index_changes WHERE index_name = 'S&P 500' AND action = 'ADD';
```

## Troubleshooting

### Email Not Sending

**Issue**: SMTP authentication error

**Solution**:
1. Verify Gmail app password is correct
2. Ensure 2-Factor Authentication is enabled
3. Check that SMTP credentials are in config.yaml or environment variables
4. Test SMTP connection:
   ```bash
   python -c "import smtplib; s = smtplib.SMTP('smtp.gmail.com', 587); s.starttls(); s.login('email@gmail.com', 'password'); print('Success')"
   ```

### No Changes Detected

**Issue**: Monitor runs but finds no changes

**Solution**:
1. Check that indices are enabled in config.yaml
2. Verify press release feeds are accessible
3. Check logs: `tail -f logs/monitor.log`
4. Run with debug logging: Update `logging.level` to `DEBUG` in config.yaml

### Database Locked

**Issue**: SQLite database is locked

**Solution**:
1. Ensure no other instances are running
2. Delete lock file: `rm data/changes.db-wal`
3. Verify database integrity: `sqlite3 data/changes.db "PRAGMA integrity_check;"`

### GitHub Actions Workflow Not Running

**Issue**: Workflow doesn't execute on schedule

**Solution**:
1. Verify secrets are set (Settings → Secrets and variables)
2. Check workflow file syntax: `.github/workflows/monitor.yml`
3. Ensure workflow is not disabled (Actions tab)
4. GitHub Actions requires at least one commit in past 60 days to run scheduled workflows

## Architecture

### Components

1. **Scrapers**: Extract index changes from official press releases
   - `SPScraper`: S&P Dow Jones Indices
   - `RussellScraper`: FTSE Russell
   - `NasdaqScraper`: Nasdaq Global Indexes

2. **Enricher**: Adds company metadata
   - SEC EDGAR lookup (CIK codes)
   - Yahoo Finance lookup (GICS classification)
   - Caching to reduce API calls

3. **Database**: State management and audit trail
   - SQLite for local persistence
   - Deduplication logic
   - Change tracking

4. **Email Client**: Notification delivery
   - HTML formatting
   - SMTP delivery
   - Error handling and retry

5. **Orchestrator**: Main execution flow
   - Coordinates all components
   - Handles errors and logging
   - Manages state transitions

### Data Flow

```
Press Releases → Scraper → Parser → Enricher → Database → Email
                                                    ↓
                                            GitHub Commit
```

## Performance

- **Scrape Time**: ~30 seconds per index provider
- **Enrichment Time**: ~2 minutes for 10 changes
- **Email Delivery**: ~1 minute
- **Total Execution**: ~5 minutes per run
- **Notification Latency**: < 2 hours from press release publication

## Limitations

1. **Press Release Parsing**: Relies on consistent formatting from index providers
2. **Enrichment Coverage**: Some companies may not have GICS classification
3. **Rate Limiting**: SEC EDGAR and Yahoo Finance have rate limits
4. **Historical Data**: Only tracks changes going forward from first run

## Future Enhancements

- Slack notifications as alternative to email
- Dashboard for viewing historical changes
- Webhook support for external integrations
- Change impact analysis (sector/market cap distribution)
- Predictive reconstitution alerts
- Database backup to cloud storage
- Multi-language support

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

MIT License - see LICENSE file for details

## Support

For issues, questions, or suggestions:

1. Check existing GitHub Issues
2. Review troubleshooting section above
3. Create a new GitHub Issue with:
   - Description of problem
   - Steps to reproduce
   - Relevant logs (sanitized for sensitive data)
   - Environment details (Python version, OS, etc.)

## Disclaimer

This tool is provided as-is for informational purposes. Index changes are official announcements from index providers. Always verify information from official sources before making investment decisions. The authors are not responsible for any financial decisions made based on this tool's output.

## References

- [S&P Dow Jones Indices](https://www.spglobal.com/spdji/en/)
- [FTSE Russell](https://www.lseg.com/en/ftse-russell/)
- [Nasdaq Global Indexes](https://indexes.nasdaq.com/)
- [SEC EDGAR](https://www.sec.gov/edgar/)
- [GICS Classification](https://www.msci.com/gics)
