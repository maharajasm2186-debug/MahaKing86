# Index Monitor - Setup Guide

This guide provides step-by-step instructions for setting up and deploying the Index Monitor.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Gmail Configuration](#gmail-configuration)
3. [GitHub Repository Setup](#github-repository-setup)
4. [Local Deployment](#local-deployment)
5. [GitHub Actions Deployment](#github-actions-deployment)
6. [Verification](#verification)

## Quick Start

### 5-Minute Setup

```bash
# 1. Clone repository
git clone https://github.com/yourusername/index-monitor.git
cd index-monitor

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure (see Gmail Configuration below)
cp config.example.yaml config.yaml
# Edit config.yaml with your Gmail credentials

# 5. Test run
python -m src.main

# 6. Check database
sqlite3 data/changes.db "SELECT COUNT(*) FROM index_changes;"
```

## Gmail Configuration

### Step 1: Enable 2-Factor Authentication

1. Go to https://myaccount.google.com/security
2. Find "2-Step Verification"
3. Click "Get started"
4. Follow the prompts to enable 2FA
5. Confirm with your phone

### Step 2: Generate App Password

1. Go to https://myaccount.google.com/apppasswords
2. Select:
   - **App**: Mail
   - **Device**: Windows Computer (or your device type)
3. Click "Generate"
4. Google will display a 16-character password
5. **Copy this password** - you'll need it for config

### Step 3: Update Configuration

Edit `config.yaml`:

```yaml
email:
  smtp_server: smtp.gmail.com
  smtp_port: 587
  sender_email: your-email@gmail.com           # Your Gmail address
  sender_password: xxxx xxxx xxxx xxxx          # 16-char app password (spaces included)
  recipient: maharajasm2186@gmail.com
```

### Step 4: Test Email Delivery

```bash
python << 'EOF'
import smtplib
from email.mime.text import MIMEText

sender = "your-email@gmail.com"
password = "xxxx xxxx xxxx xxxx"
recipient = "maharajasm2186@gmail.com"

msg = MIMEText("Test email from Index Monitor")
msg['Subject'] = "Test"
msg['From'] = sender
msg['To'] = recipient

try:
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)
    print("✓ Email sent successfully!")
except Exception as e:
    print(f"✗ Error: {e}")
EOF
```

## GitHub Repository Setup

### Step 1: Create GitHub Repository

1. Go to https://github.com/new
2. **Repository name**: `index-monitor`
3. **Description**: "Stock index constituent change monitor"
4. **Visibility**: Public or Private (your choice)
5. **Initialize**: Leave unchecked (we'll push existing code)
6. Click "Create repository"

### Step 2: Push Code to GitHub

```bash
cd index-monitor

# Initialize git (if not already done)
git init
git add .
git commit -m "Initial commit: Index Monitor"

# Add remote and push
git remote add origin https://github.com/yourusername/index-monitor.git
git branch -M main
git push -u origin main
```

### Step 3: Add GitHub Secrets

1. Go to your repository on GitHub
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Add secret 1:
   - **Name**: `SMTP_SENDER_EMAIL`
   - **Value**: `your-email@gmail.com`
5. Click **Add secret**
6. Add secret 2:
   - **Name**: `SMTP_PASSWORD`
   - **Value**: `xxxx xxxx xxxx xxxx` (your 16-char app password)
7. Click **Add secret**

### Step 4: Enable GitHub Actions

1. Go to **Actions** tab
2. Click **I understand my workflows, go ahead and enable them**
3. Verify "Index Monitor" workflow appears

## Local Deployment

### Option 1: Manual Cron (Linux/macOS)

1. **Create log directory**:
   ```bash
   mkdir -p ~/index-monitor/logs
   ```

2. **Edit crontab**:
   ```bash
   crontab -e
   ```

3. **Add this line** (runs every 6 hours):
   ```cron
   0 0,6,12,18 * * * cd ~/index-monitor && /usr/bin/python3 -m src.main >> logs/cron.log 2>&1
   ```

4. **Verify cron job**:
   ```bash
   crontab -l
   ```

5. **Monitor logs**:
   ```bash
   tail -f ~/index-monitor/logs/cron.log
   ```

### Option 2: Windows Task Scheduler

1. **Open Task Scheduler**:
   - Press `Win + R`
   - Type `taskschd.msc`
   - Press Enter

2. **Create Basic Task**:
   - Right-click "Task Scheduler Library"
   - Select "Create Basic Task"
   - **Name**: `Index Monitor`
   - **Description**: `Monitor stock index changes`
   - Click **Next**

3. **Set Trigger**:
   - Select "Daily"
   - Set time to 12:00 AM
   - Check "Repeat task every: 6 hours"
   - Click **Next**

4. **Set Action**:
   - Select "Start a program"
   - **Program**: `C:\Python311\python.exe` (your Python path)
   - **Arguments**: `-m src.main`
   - **Start in**: `C:\Users\YourUser\index-monitor`
   - Click **Next**

5. **Finish**:
   - Check "Open the Properties dialog for this task when I click Finish"
   - Click **Finish**

6. **Configure Advanced Settings**:
   - Go to **General** tab
   - Check "Run with highest privileges"
   - Go to **Settings** tab
   - Check "Allow task to be run on demand"
   - Click **OK**

7. **Test**:
   - Right-click the task
   - Select "Run"
   - Check logs/monitor.log for output

## GitHub Actions Deployment

### Automatic Setup

The GitHub Actions workflow is already configured in `.github/workflows/monitor.yml`. It will:

- Run every 6 hours automatically
- Detect index changes
- Send email notifications
- Commit results to repository
- Create issues on errors

### Manual Trigger

To run the workflow manually:

1. Go to **Actions** tab
2. Click **Index Monitor** workflow
3. Click **Run workflow**
4. Select **main** branch
5. Click **Run workflow**

### Monitor Workflow Runs

1. Go to **Actions** tab
2. Click **Index Monitor**
3. View recent runs with status (✓ or ✗)
4. Click run to see detailed logs

## Verification

### Test 1: Local Execution

```bash
cd index-monitor
python -m src.main
```

**Expected output**:
```
================================================================================
Starting Index Monitor run at 2024-01-15T10:30:00.000000
================================================================================
Scraping S&P 500...
No changes found for S&P 500
...
================================================================================
Index Monitor run completed at 2024-01-15T10:35:00.000000
================================================================================
```

### Test 2: Database Creation

```bash
ls -lh data/changes.db
sqlite3 data/changes.db ".tables"
```

**Expected output**:
```
index_changes  notification_log
```

### Test 3: Email Delivery

Add a test change to trigger email:

```bash
sqlite3 data/changes.db << 'EOF'
INSERT INTO index_changes (
  ticker, company_name, cik_code, gics_sector, gics_industry,
  action, index_name, effective_date, announcement_date,
  press_release_url, created_at, updated_at
) VALUES (
  'TEST', 'Test Company Inc', '0000000001', 'Technology', 'Software',
  'ADD', 'S&P 500', '2024-01-15', '2024-01-15',
  'https://example.com', datetime('now'), datetime('now')
);
EOF
```

Then run:
```bash
python -m src.main
```

Check your email for notification.

### Test 4: GitHub Actions

1. Go to **Actions** tab
2. Click **Index Monitor** workflow
3. Click **Run workflow**
4. Select **main** branch
5. Click **Run workflow**
6. Wait for workflow to complete
7. Check email for notification
8. Verify repository has new commits

## Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'src'"

**Solution**:
```bash
# Make sure you're in the repository root
cd index-monitor

# Reinstall dependencies
pip install -r requirements.txt

# Run with python -m
python -m src.main
```

### Issue: "SMTP authentication failed"

**Solution**:
1. Verify Gmail app password (not regular password)
2. Verify 2-Factor Authentication is enabled
3. Check for spaces in app password
4. Test with:
   ```bash
   python -c "import smtplib; s = smtplib.SMTP('smtp.gmail.com', 587); s.starttls(); s.login('email@gmail.com', 'password')"
   ```

### Issue: "No changes found" but changes exist

**Solution**:
1. Check press release feeds are accessible:
   ```bash
   curl -I https://www.prnewswire.com/news/s%26p-dow-jones-indices/
   ```
2. Enable debug logging in config.yaml:
   ```yaml
   logging:
     level: DEBUG
   ```
3. Check logs for parsing errors:
   ```bash
   tail -f logs/monitor.log
   ```

### Issue: GitHub Actions workflow not running

**Solution**:
1. Verify secrets are set (Settings → Secrets)
2. Check workflow file is valid:
   ```bash
   python -m yaml .github/workflows/monitor.yml
   ```
3. Ensure at least one commit in past 60 days
4. Try manual trigger (Actions → Run workflow)

### Issue: Database locked error

**Solution**:
```bash
# Remove lock files
rm data/changes.db-wal data/changes.db-shm

# Verify database integrity
sqlite3 data/changes.db "PRAGMA integrity_check;"
```

## Next Steps

1. **Monitor logs**: `tail -f logs/monitor.log`
2. **Check database**: `sqlite3 data/changes.db "SELECT * FROM index_changes;"`
3. **Review emails**: Check maharajasm2186@gmail.com for notifications
4. **Customize indices**: Edit config.yaml to enable/disable specific indices
5. **Set up alerts**: Configure GitHub Actions to create issues on errors

## Support

For issues or questions:

1. Check README.md troubleshooting section
2. Review logs in `logs/monitor.log`
3. Create GitHub Issue with error details
4. Include: Python version, OS, error message, and relevant logs

## Security Notes

- **Never commit credentials** to repository
- Use GitHub Secrets for sensitive data
- Use environment variables for local development
- Regularly rotate Gmail app passwords
- Review GitHub Actions logs for sensitive data leaks
- Keep dependencies updated: `pip install --upgrade -r requirements.txt`
