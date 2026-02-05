# Red Day DCA Alerter - Setup Guide

This automated system monitors BTC price and sends buy order emails when your DCA triggers fire.

## What This System Does

When BTC drops significantly:
1. **Emails Jake at Caleb & Brown** with your crypto buy order
2. **Emails you** with eToro equity purchase instructions
3. Tracks triggers (max 15) and handles the "every 3rd trigger" logic for BANANA/BONK

### Trigger Rules
- **Intraday**: BTC drops ≥4.7% below yesterday's close at any point
- **Close-to-close**: BTC closes ≥3.3% down from prior close
- Max 1 trigger per day, max 15 triggers total

### Per Trigger Purchases

**Crypto (sent to Caleb & Brown):**
| Asset | Amount |
|-------|--------|
| LINK | £666.67 |
| ONDO | £533.33 |
| TAO | £533.33 |
| RENDER | £533.33 |
| TRAC | £333.33 |
| **BANANA*** | £100.00 |
| **BONK*** | £100.00 |

*Only on triggers 3, 6, 9, 12, 15

**Equities (eToro - manual action required):**
| Stock | Amount |
|-------|--------|
| COIN | £233.33 |
| NVDA | £200.00 |
| PLTR | £166.67 |

---

## Setup Instructions

### Step 1: Create a Gmail App Password

Since you're using Gmail (lewis@jackson.ventures), you need an App Password:

1. Go to [Google Account Security](https://myaccount.google.com/security)
2. Enable 2-Factor Authentication if not already enabled
3. Go to [App Passwords](https://myaccount.google.com/apppasswords)
4. Select "Mail" and "Other (Custom name)"
5. Enter "Red Day DCA Alerter"
6. Click Generate
7. **Save the 16-character password** - you'll need it for deployment

### Step 2: Deploy to Railway (Recommended - Free Tier Available)

Railway is the simplest option for running this 24/7.

#### 2a. Create Railway Account
1. Go to [railway.app](https://railway.app)
2. Sign up with GitHub (recommended) or email

#### 2b. Create New Project
1. Click "New Project"
2. Select "Deploy from GitHub repo"
3. If you haven't uploaded the code to GitHub yet:
   - Create a new GitHub repository
   - Upload all files from the `red_day_dca_alerter` folder
   - Return to Railway and connect the repo

**Or use "Empty Project" + CLI:**
```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Create project
railway init

# Deploy
railway up
```

#### 2c. Set Environment Variables

In Railway dashboard, go to your project → Variables → Add these:

| Variable | Value |
|----------|-------|
| `SENDER_EMAIL` | `lewis@jackson.ventures` |
| `SENDER_PASSWORD` | `your-16-char-app-password` |
| `SMTP_SERVER` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |

#### 2d. Enable Persistent Storage (Important!)

The system saves state to track trigger count. To persist this:

1. In Railway, click "+ New" → "Database" → "Redis" or use a Volume
2. Or simply note that if the service restarts, you may need to manually set the trigger count

### Step 3: Alternative - Deploy to Render

If you prefer Render:

1. Go to [render.com](https://render.com)
2. Create account and connect GitHub
3. New → Background Worker
4. Connect your repository
5. Set environment variables (same as Railway)
6. Deploy

### Step 4: Test the System

Before going live, test with a modified threshold:

1. Temporarily change `INTRADAY_DIP_THRESHOLD = -0.1` in main.py (will trigger on any 0.1% drop)
2. Deploy and watch for test emails
3. Once confirmed working, revert to `-4.7`

---

## Monitoring & Logs

### View Logs on Railway
```bash
railway logs
```

Or in the Railway dashboard → your service → Logs

### Check Current State

The system creates a `dca_state.json` file with:
- Current trigger count
- Last trigger date
- Full trigger history

### Manual State Reset

If needed, you can reset the state by deleting `dca_state.json` or modifying it:

```json
{
  "trigger_count": 0,
  "last_trigger_date": null,
  "yesterday_close": null,
  "yesterday_close_date": null,
  "trigger_history": []
}
```

---

## Email Examples

### Broker Email (to Jake)
Subject: `BUY ORDER - Red Day DCA Trigger #3 of 15`

Contains:
- Trigger details (price, drop %, timestamp)
- Complete buy order table
- Request to process with immediate effect
- Note if it's a 3rd trigger (includes BANANA/BONK)

### Personal Email (to you)
Subject: `🔔 ACTION REQUIRED: eToro Purchase - Trigger #3`

Contains:
- Alert summary
- eToro purchase instructions (manual action needed)
- Confirmation that broker email was sent
- Progress bar showing triggers completed

---

## Troubleshooting

### Emails not sending
- Check SENDER_PASSWORD is the App Password (not your regular password)
- Verify 2FA is enabled on your Google account
- Check Railway/Render logs for errors

### Triggers not firing
- Verify the service is running (check logs)
- BTC may not have dropped enough - check current price vs threshold
- Already triggered today? Check `dca_state.json`

### Service keeps restarting
- Check for Python errors in logs
- Ensure all environment variables are set
- Verify requirements are installed

---

## Cost

- **Railway**: Free tier includes 500 hours/month (enough for this)
- **Render**: Free tier for background workers
- **Binance API**: Free (no API key needed for price data)

---

## Files Included

```
red_day_dca_alerter/
├── main.py           # Main monitoring script
├── requirements.txt  # Python dependencies
├── Procfile          # For Heroku/Railway
├── railway.json      # Railway config
└── SETUP.md          # This file
```

---

## Support

If triggers fire but you want to pause/stop:
1. Stop the service in Railway/Render dashboard
2. Or set `MAX_TRIGGERS = 0` temporarily

To resume: restart the service (state is preserved)
