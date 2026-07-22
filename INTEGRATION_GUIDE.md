# Index Monitor Integration Guide

This guide provides step-by-step instructions to complete the integration of the Index Monitor into your MahaKing86 repository.

## 📋 Integration Checklist

- [x] Directory structure created
- [x] Python modules copied
- [x] Configuration file created
- [x] GitHub Actions workflow created
- [ ] Push code to repository (YOU DO THIS)
- [ ] Verify GitHub Secrets
- [ ] Enable GitHub Actions
- [ ] Trigger first run
- [ ] Verify email notifications

## 🔄 Step-by-Step Push Instructions

### Step 1: Configure Git (First Time Only)

```bash
cd /tmp/MahaKing86

# Configure git with your identity
git config user.email "maharajasm2186@gmail.com"
git config user.name "Maharaja"
```

### Step 2: Stage All Files

```bash
# Add all files to staging
git add -A

# Verify files are staged
git status
```

**Expected Output:**
```
On branch main
Changes to be committed:
  new file:   README.md
  new file:   .github/workflows/index-monitor.yml
  new file:   index-monitor/src/main.py
  new file:   index-monitor/src/config.py
  ... (many more files)
```

### Step 3: Create Initial Commit

```bash
git commit -m "🎯 Add Index Monitor - Stock Index Change Detection

- Automated monitoring of S&P, Russell, Nasdaq-100, and Dow indices
- Real-time email notifications to maharajasm2186@gmail.com
- Enriched data with CIK codes and GICS classification
- GitHub Actions workflow for 6-hourly execution
- SQLite database for audit trail and state management

Features:
- Monitors 9 major US stock indices
- Detects added/removed companies automatically
- Sends formatted HTML email notifications
- Maintains complete change history
- Runs every 6 hours via GitHub Actions

Configuration:
- Email credentials from GitHub Secrets
- Customizable index selection
- Configurable enrichment options
- Detailed logging and error handling"
```

### Step 4: Push to GitHub

```bash
# Push to main branch
git push -u origin main

# Verify push was successful
git log --oneline -5
```

**Expected Output:**
```
a1b2c3d (HEAD -> main, origin/main) 🎯 Add Index Monitor - Stock Index Change Detection
```

## ✅ Post-Push Verification

### Step 1: Verify Repository on GitHub

1. Go to https://github.com/maharajasm2186-debug/MahaKing86
2. Verify you see:
   - ✓ README.md file
   - ✓ index-monitor/ folder
   - ✓ .github/workflows/ folder

### Step 2: Verify GitHub Secrets

1. Click **Settings** → **Secrets and variables** → **Actions**
2. Verify these secrets exist:
   - ✓ `SMTP_SENDER_EMAIL`
   - ✓ `SMTP_PASSWORD`

If secrets are missing, add them:

1. Click **New repository secret**
2. **Name**: `SMTP_SENDER_EMAIL`
3. **Value**: Your Gmail address
4. Click **Add secret**

Repeat for `SMTP_PASSWORD` with your Gmail app password.

### Step 3: Enable GitHub Actions

1. Go to **Actions** tab
2. If you see "Workflows aren't being run on this forked repository", click **Enable GitHub Actions**
3. You should see "Index Monitor - Stock Index Changes" workflow

### Step 4: Verify Workflow File

1. Go to **Actions** tab
2. Click **Index Monitor - Stock Index Changes**
3. You should see the workflow is ready to run

## 🚀 Trigger First Run

### Option 1: Manual Trigger (Recommended)

1. Go to **Actions** tab
2. Click **Index Monitor - Stock Index Changes**
3. Click **Run workflow**
4. Select **main** branch
5. Click **Run workflow**
6. Wait for execution to complete (should take 3-5 minutes)

### Option 2: Wait for Scheduled Run

The workflow runs automatically every 6 hours at:
- 00:00 UTC
- 06:00 UTC
- 12:00 UTC
- 18:00 UTC

## 📊 Monitor First Execution

### Check Workflow Status

1. Go to **Actions** tab
2. Click the latest run
3. Watch the steps execute in real-time
4. Look for green checkmarks (✓) for successful steps

### View Detailed Logs

1. Click on any step to expand it
2. Review the output for any errors
3. Check for "✓ Email sent successfully" message

### Check for Email Notification

1. Open your email (maharajasm2186@gmail.com)
2. Look for email from GitHub Actions
3. Subject should be: "📊 Index Constituent Changes"

If no email received:
- Check spam/junk folder
- Verify SMTP credentials in GitHub Secrets
- Check workflow logs for SMTP errors

## 🔍 Verify Database Creation

After first run:

1. Go to **Actions** tab
2. Click the completed run
3. Scroll to **Artifacts** section
4. Download `index-monitor-database-*` file
5. Extract and verify changes.db exists

Or check via Git:

```bash
cd /tmp/MahaKing86
git pull
ls -lh index-monitor/data/changes.db
```

## 📝 Configuration Customization

### Enable/Disable Indices

Edit `index-monitor/config.yaml`:

```yaml
indices:
  sp100: true      # Enable S&P 100
  sp500: true      # Enable S&P 500
  nasdaq100: false # Disable Nasdaq-100
  # ... others
```

Then commit and push:

```bash
cd /tmp/MahaKing86
git add index-monitor/config.yaml
git commit -m "⚙️ Update: Configure index monitoring preferences"
git push
```

### Change Email Recipient

Edit `index-monitor/config.yaml`:

```yaml
email:
  recipient: your-new-email@example.com
```

Then commit and push:

```bash
git add index-monitor/config.yaml
git commit -m "⚙️ Update: Change email recipient"
git push
```

### Adjust Logging Level

Edit `index-monitor/config.yaml`:

```yaml
logging:
  level: DEBUG  # Change from INFO to DEBUG for more details
```

## 🐛 Troubleshooting Integration

### Issue: "Permission denied" when pushing

**Solution**:
1. Verify you have push access to the repository
2. Check GitHub authentication:
   ```bash
   git remote -v
   ```
3. If using HTTPS, you may need a Personal Access Token (PAT)

### Issue: Workflow not appearing in Actions tab

**Solution**:
1. Verify `.github/workflows/index-monitor.yml` exists
2. Check workflow file syntax (YAML must be valid)
3. Try refreshing the page
4. Wait a few minutes for GitHub to recognize the workflow

### Issue: Workflow runs but no email received

**Solution**:
1. Check GitHub Secrets are set correctly
2. Verify SMTP credentials in workflow logs
3. Check spam/junk folder
4. Try manual test email via Python:
   ```bash
   cd index-monitor
   python -c "
   import smtplib
   from email.mime.text import MIMEText
   msg = MIMEText('Test')
   msg['Subject'] = 'Test'
   msg['From'] = 'your-email@gmail.com'
   msg['To'] = 'maharajasm2186@gmail.com'
   with smtplib.SMTP('smtp.gmail.com', 587) as s:
       s.starttls()
       s.login('your-email@gmail.com', 'your-app-password')
       s.send_message(msg)
   print('✓ Test email sent')
   "
   ```

### Issue: "No changes found" but changes exist

**Solution**:
1. Enable DEBUG logging in config.yaml
2. Check press release feeds are accessible
3. Review logs for parsing errors
4. Verify indices are enabled in config.yaml

## 📚 Next Steps

1. **Monitor Execution**: Watch the first few runs to verify everything works
2. **Review Emails**: Check email format and content
3. **Customize**: Adjust configuration as needed
4. **Set Alerts**: Create GitHub Issues for important changes
5. **Backup**: Regularly backup the database

## 📞 Support

If you encounter issues:

1. Check the troubleshooting section above
2. Review workflow logs in Actions tab
3. Check application logs in `index-monitor/logs/`
4. Create a GitHub Issue with error details

## ✨ Success Indicators

You'll know the integration is successful when:

- ✅ Workflow appears in Actions tab
- ✅ Workflow runs without errors (green checkmarks)
- ✅ Email notifications arrive at maharajasm2186@gmail.com
- ✅ Database file is created and populated
- ✅ GitHub Issues are created for changes/errors

## 🎉 Congratulations!

Your Index Monitor is now integrated and running! The system will automatically:

- Check for index changes every 6 hours
- Send email notifications when changes are detected
- Maintain a complete audit trail in the database
- Create GitHub Issues for tracking changes
- Upload logs and database snapshots as artifacts

Enjoy automated stock index monitoring! 📊
