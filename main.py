"""
Red Day DCA Alerter
====================
Automated price monitoring and alert system for Lewis's DCA strategy.

Monitors BTC price and triggers buy alerts when:
- Intraday: Price drops ≥4.7% below yesterday's close
- OR Close-to-close: Price closes ≥3.3% down from prior close

Sends emails to:
1. Broker (Jake at Caleb & Brown) with crypto buy orders
2. Lewis with eToro equity purchase instructions
"""

import os
import json
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests
import time
import schedule

# =============================================================================
# CONFIGURATION
# =============================================================================

# Email Configuration (set these as environment variables)
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "lewis@jackson.ventures")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD", "")  # Gmail App Password

# Recipients
BROKER_EMAIL = "jake@calebandbrown.com"
PERSONAL_EMAIL = "lewis@jackson.ventures"

# Trigger Thresholds
INTRADAY_DIP_THRESHOLD = -4.7  # Percentage drop from yesterday's close (intraday)
CLOSE_TO_CLOSE_THRESHOLD = -3.3  # Percentage drop close-to-close

# Maximum triggers
MAX_TRIGGERS = 15

# Check interval (seconds) - how often to check price during market hours
CHECK_INTERVAL_SECONDS = 60  # Every minute

# State file to persist trigger count across restarts
STATE_FILE = Path("dca_state.json")

# =============================================================================
# PORTFOLIO CONFIGURATION
# =============================================================================

# Crypto allocations per trigger (£2,600 core assets on all triggers)
CORE_CRYPTO_ALLOCATIONS = {
    "LINK": 666.67,
    "ONDO": 533.33,
    "TAO": 533.33,
    "RENDER": 533.33,
    "TRAC": 333.33,
}

# Spec allocations - ONLY on every 3rd trigger (£100 each)
SPEC_CRYPTO_ALLOCATIONS = {
    "BANANA": 100.00,
    "BONK": 100.00,
}

# eToro equity allocations per trigger (£600 total)
ETORO_ALLOCATIONS = {
    "COIN": 233.33,
    "NVDA": 200.00,
    "PLTR": 166.67,
}

# =============================================================================
# LOGGING SETUP
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('dca_alerter.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# =============================================================================
# STATE MANAGEMENT
# =============================================================================

def load_state():
    """Load persisted state from file."""
    default_state = {
        "trigger_count": 0,
        "last_trigger_date": None,
        "yesterday_close": None,
        "yesterday_close_date": None,
        "trigger_history": []
    }

    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
                # Merge with defaults for any missing keys
                for key in default_state:
                    if key not in state:
                        state[key] = default_state[key]
                return state
        except Exception as e:
            logger.error(f"Error loading state: {e}")

    return default_state


def save_state(state):
    """Persist state to file."""
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving state: {e}")


# =============================================================================
# PRICE DATA FUNCTIONS
# =============================================================================

def get_binance_btc_price():
    """Get current BTC/USDT price from Binance."""
    try:
        url = "https://api.binance.com/api/v3/ticker/price"
        params = {"symbol": "BTCUSDT"}
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        return float(data["price"])
    except Exception as e:
        logger.error(f"Error fetching Binance price: {e}")
        return None


def get_binance_daily_close(days_ago=1):
    """Get BTC daily close from Binance klines."""
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {
            "symbol": "BTCUSDT",
            "interval": "1d",
            "limit": days_ago + 1
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if len(data) >= days_ago + 1:
            # Kline format: [open_time, open, high, low, close, volume, ...]
            # Get the close of N days ago
            candle = data[-(days_ago + 1)]
            close_price = float(candle[4])
            close_time = datetime.fromtimestamp(candle[0] / 1000, tz=timezone.utc)
            return close_price, close_time.strftime("%Y-%m-%d")
        return None, None
    except Exception as e:
        logger.error(f"Error fetching daily close: {e}")
        return None, None


def get_today_close():
    """Get today's closing price (if the day has ended in UTC)."""
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {
            "symbol": "BTCUSDT",
            "interval": "1d",
            "limit": 1
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data:
            candle = data[0]
            close_time_ms = candle[6]  # Close time
            current_time_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

            # If close time has passed, this candle is complete
            if current_time_ms > close_time_ms:
                return float(candle[4])  # Close price
        return None
    except Exception as e:
        logger.error(f"Error fetching today's close: {e}")
        return None


# =============================================================================
# EMAIL FUNCTIONS
# =============================================================================

def send_email(to_email, subject, body_html, body_text=None):
    """Send an email using SMTP."""
    if not SENDER_PASSWORD:
        logger.error("SENDER_PASSWORD not set - cannot send email")
        logger.info(f"Would have sent to {to_email}:\n{body_text or body_html}")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SENDER_EMAIL
        msg["To"] = to_email

        if body_text:
            msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, to_email, msg.as_string())

        logger.info(f"Email sent successfully to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Error sending email to {to_email}: {e}")
        return False


def generate_broker_email(trigger_number, current_price, yesterday_close, drop_pct, trigger_type):
    """Generate email content for Jake at Caleb & Brown."""

    # Determine if this is a 3rd trigger (includes spec assets)
    is_third_trigger = trigger_number % 3 == 0

    # Build asset list
    assets = dict(CORE_CRYPTO_ALLOCATIONS)
    if is_third_trigger:
        assets.update(SPEC_CRYPTO_ALLOCATIONS)

    total_amount = sum(assets.values())

    # Build asset table
    asset_rows = ""
    for asset, amount in assets.items():
        asset_rows += f"<tr><td style='padding: 8px; border: 1px solid #ddd;'>{asset}</td><td style='padding: 8px; border: 1px solid #ddd;'>£{amount:,.2f}</td></tr>\n"

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    subject = f"BUY ORDER - Red Day DCA Trigger #{trigger_number} of {MAX_TRIGGERS}"

    body_html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <h2 style="color: #1a5f7a;">Buy Order Request</h2>

        <p>Hi Jake,</p>

        <p>This is an automated buy order from Lewis's Red Day DCA strategy.</p>

        <div style="background-color: #f5f5f5; padding: 15px; border-radius: 5px; margin: 20px 0;">
            <h3 style="margin-top: 0; color: #1a5f7a;">Trigger Details</h3>
            <ul style="list-style: none; padding: 0;">
                <li><strong>Trigger Number:</strong> {trigger_number} of {MAX_TRIGGERS}</li>
                <li><strong>Trigger Type:</strong> {trigger_type}</li>
                <li><strong>BTC Price:</strong> ${current_price:,.2f}</li>
                <li><strong>Yesterday's Close:</strong> ${yesterday_close:,.2f}</li>
                <li><strong>Drop:</strong> {drop_pct:.2f}%</li>
                <li><strong>Timestamp:</strong> {timestamp}</li>
            </ul>
        </div>

        <h3 style="color: #1a5f7a;">Buy Order (Total: £{total_amount:,.2f})</h3>

        <p><strong>Please process this order with immediate effect.</strong> Use available USDT or fiat USD balance to execute.</p>

        <table style="border-collapse: collapse; width: 100%; max-width: 400px;">
            <tr style="background-color: #1a5f7a; color: white;">
                <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">Asset</th>
                <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">Amount (GBP)</th>
            </tr>
            {asset_rows}
            <tr style="background-color: #e8f4f8; font-weight: bold;">
                <td style="padding: 8px; border: 1px solid #ddd;">TOTAL</td>
                <td style="padding: 8px; border: 1px solid #ddd;">£{total_amount:,.2f}</td>
            </tr>
        </table>

        {"<p style='color: #d35400; font-weight: bold;'>⚠️ Note: This is trigger #{trigger_number} (every 3rd trigger) - includes additional BANANA and BONK purchases.</p>" if is_third_trigger else ""}

        <p>Please confirm execution once complete.</p>

        <p>Best regards,<br>Lewis</p>

        <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">
        <p style="font-size: 12px; color: #888;">This is an automated message from Lewis's Red Day DCA Alert System.</p>
    </body>
    </html>
    """

    body_text = f"""
BUY ORDER - Red Day DCA Trigger #{trigger_number} of {MAX_TRIGGERS}

Hi Jake,

This is an automated buy order from Lewis's Red Day DCA strategy.

TRIGGER DETAILS:
- Trigger Number: {trigger_number} of {MAX_TRIGGERS}
- Trigger Type: {trigger_type}
- BTC Price: ${current_price:,.2f}
- Yesterday's Close: ${yesterday_close:,.2f}
- Drop: {drop_pct:.2f}%
- Timestamp: {timestamp}

BUY ORDER (Total: £{total_amount:,.2f})
Please process this order with immediate effect. Use available USDT or fiat USD balance.

"""
    for asset, amount in assets.items():
        body_text += f"- {asset}: £{amount:,.2f}\n"

    if is_third_trigger:
        body_text += f"\n⚠️ Note: This is trigger #{trigger_number} (every 3rd trigger) - includes additional BANANA and BONK purchases.\n"

    body_text += """
Please confirm execution once complete.

Best regards,
Lewis

---
This is an automated message from Lewis's Red Day DCA Alert System.
"""

    return subject, body_html, body_text


def generate_personal_email(trigger_number, current_price, yesterday_close, drop_pct, trigger_type):
    """Generate email content for Lewis (eToro notification)."""

    total_etoro = sum(ETORO_ALLOCATIONS.values())
    is_third_trigger = trigger_number % 3 == 0

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    subject = f"🔔 ACTION REQUIRED: eToro Purchase - Trigger #{trigger_number}"

    # Build eToro table
    etoro_rows = ""
    for asset, amount in ETORO_ALLOCATIONS.items():
        etoro_rows += f"<tr><td style='padding: 8px; border: 1px solid #ddd;'>{asset}</td><td style='padding: 8px; border: 1px solid #ddd;'>£{amount:,.2f}</td></tr>\n"

    # Build crypto table for reference
    crypto_assets = dict(CORE_CRYPTO_ALLOCATIONS)
    if is_third_trigger:
        crypto_assets.update(SPEC_CRYPTO_ALLOCATIONS)

    crypto_rows = ""
    for asset, amount in crypto_assets.items():
        crypto_rows += f"<tr><td style='padding: 8px; border: 1px solid #ddd;'>{asset}</td><td style='padding: 8px; border: 1px solid #ddd;'>£{amount:,.2f}</td></tr>\n"

    body_html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <h2 style="color: #c0392b;">🔔 Red Day DCA Alert - Action Required</h2>

        <div style="background-color: #fdf2f2; padding: 15px; border-radius: 5px; border-left: 4px solid #c0392b; margin: 20px 0;">
            <h3 style="margin-top: 0;">Trigger #{trigger_number} of {MAX_TRIGGERS} Fired!</h3>
            <p><strong>BTC dropped {drop_pct:.2f}%</strong> ({trigger_type})</p>
            <p>Current: ${current_price:,.2f} | Yesterday's Close: ${yesterday_close:,.2f}</p>
            <p>Time: {timestamp}</p>
        </div>

        <h3 style="color: #c0392b;">📱 eToro Action Required</h3>
        <p>Please manually execute the following purchases on eToro:</p>

        <table style="border-collapse: collapse; width: 100%; max-width: 400px;">
            <tr style="background-color: #c0392b; color: white;">
                <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">Stock</th>
                <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">Amount (GBP)</th>
            </tr>
            {etoro_rows}
            <tr style="background-color: #fce4e4; font-weight: bold;">
                <td style="padding: 8px; border: 1px solid #ddd;">TOTAL</td>
                <td style="padding: 8px; border: 1px solid #ddd;">£{total_etoro:,.2f}</td>
            </tr>
        </table>

        <h3 style="color: #27ae60; margin-top: 30px;">✅ Broker Email Sent</h3>
        <p>An email has been sent to Jake at Caleb & Brown with the following crypto order:</p>

        <table style="border-collapse: collapse; width: 100%; max-width: 400px;">
            <tr style="background-color: #27ae60; color: white;">
                <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">Crypto</th>
                <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">Amount (GBP)</th>
            </tr>
            {crypto_rows}
            <tr style="background-color: #e8f8f0; font-weight: bold;">
                <td style="padding: 8px; border: 1px solid #ddd;">TOTAL</td>
                <td style="padding: 8px; border: 1px solid #ddd;">£{sum(crypto_assets.values()):,.2f}</td>
            </tr>
        </table>

        {"<p style='color: #d35400; font-weight: bold;'>⚠️ This is trigger #{} (every 3rd) - BANANA and BONK included in broker order.</p>".format(trigger_number) if is_third_trigger else ""}

        <div style="background-color: #f0f0f0; padding: 15px; border-radius: 5px; margin-top: 30px;">
            <h4 style="margin-top: 0;">Progress</h4>
            <p>Triggers completed: <strong>{trigger_number} of {MAX_TRIGGERS}</strong></p>
            <p>Remaining: <strong>{MAX_TRIGGERS - trigger_number}</strong></p>
            <div style="background-color: #ddd; border-radius: 10px; height: 20px; width: 100%;">
                <div style="background-color: #27ae60; border-radius: 10px; height: 20px; width: {(trigger_number/MAX_TRIGGERS)*100}%;"></div>
            </div>
        </div>

        <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">
        <p style="font-size: 12px; color: #888;">Red Day DCA Alert System</p>
    </body>
    </html>
    """

    body_text = f"""
🔔 RED DAY DCA ALERT - ACTION REQUIRED

Trigger #{trigger_number} of {MAX_TRIGGERS} Fired!
BTC dropped {drop_pct:.2f}% ({trigger_type})
Current: ${current_price:,.2f} | Yesterday's Close: ${yesterday_close:,.2f}
Time: {timestamp}

📱 eTORO ACTION REQUIRED
Please manually execute the following purchases on eToro:

"""
    for asset, amount in ETORO_ALLOCATIONS.items():
        body_text += f"- {asset}: £{amount:,.2f}\n"
    body_text += f"TOTAL: £{total_etoro:,.2f}\n"

    body_text += """
✅ BROKER EMAIL SENT
An email has been sent to Jake at Caleb & Brown with the crypto order:

"""
    for asset, amount in crypto_assets.items():
        body_text += f"- {asset}: £{amount:,.2f}\n"

    if is_third_trigger:
        body_text += f"\n⚠️ This is trigger #{trigger_number} (every 3rd) - BANANA and BONK included.\n"

    body_text += f"""
PROGRESS
Triggers completed: {trigger_number} of {MAX_TRIGGERS}
Remaining: {MAX_TRIGGERS - trigger_number}

---
Red Day DCA Alert System
"""

    return subject, body_html, body_text


# =============================================================================
# TRIGGER LOGIC
# =============================================================================

def check_and_trigger():
    """Main function to check price and potentially trigger alerts."""
    state = load_state()

    # Check if we've already hit max triggers
    if state["trigger_count"] >= MAX_TRIGGERS:
        logger.info(f"Max triggers ({MAX_TRIGGERS}) already reached. System complete.")
        return

    # Get current date
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Check if already triggered today
    if state["last_trigger_date"] == today:
        logger.debug(f"Already triggered today ({today}). Skipping.")
        return

    # Get yesterday's close
    yesterday_close, yesterday_date = get_binance_daily_close(days_ago=1)
    if yesterday_close is None:
        logger.error("Could not fetch yesterday's close. Skipping check.")
        return

    # Update stored yesterday close if date changed
    if state["yesterday_close_date"] != yesterday_date:
        state["yesterday_close"] = yesterday_close
        state["yesterday_close_date"] = yesterday_date
        save_state(state)
        logger.info(f"Updated yesterday's close: ${yesterday_close:,.2f} ({yesterday_date})")

    # Get current price
    current_price = get_binance_btc_price()
    if current_price is None:
        logger.error("Could not fetch current price. Skipping check.")
        return

    # Calculate intraday drop percentage
    drop_pct = ((current_price - yesterday_close) / yesterday_close) * 100

    logger.info(f"BTC: ${current_price:,.2f} | Yesterday: ${yesterday_close:,.2f} | Change: {drop_pct:+.2f}%")

    # Check intraday trigger
    triggered = False
    trigger_type = None

    if drop_pct <= INTRADAY_DIP_THRESHOLD:
        triggered = True
        trigger_type = f"Intraday dip ({drop_pct:.2f}% ≤ {INTRADAY_DIP_THRESHOLD}%)"
        logger.info(f"🔔 INTRADAY TRIGGER FIRED! Drop: {drop_pct:.2f}%")

    if triggered:
        execute_trigger(state, current_price, yesterday_close, drop_pct, trigger_type)


def check_daily_close():
    """Check at end of day for close-to-close trigger."""
    state = load_state()

    # Check if we've already hit max triggers
    if state["trigger_count"] >= MAX_TRIGGERS:
        return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Check if already triggered today
    if state["last_trigger_date"] == today:
        return

    # Get today's close and yesterday's close
    today_close = get_today_close()
    yesterday_close, _ = get_binance_daily_close(days_ago=1)

    if today_close is None or yesterday_close is None:
        return

    # Calculate close-to-close change
    drop_pct = ((today_close - yesterday_close) / yesterday_close) * 100

    if drop_pct <= CLOSE_TO_CLOSE_THRESHOLD:
        trigger_type = f"Close-to-close ({drop_pct:.2f}% ≤ {CLOSE_TO_CLOSE_THRESHOLD}%)"
        logger.info(f"🔔 CLOSE-TO-CLOSE TRIGGER FIRED! Drop: {drop_pct:.2f}%")
        execute_trigger(state, today_close, yesterday_close, drop_pct, trigger_type)


def execute_trigger(state, current_price, yesterday_close, drop_pct, trigger_type):
    """Execute the trigger: increment count, send emails."""

    # Increment trigger count
    state["trigger_count"] += 1
    trigger_number = state["trigger_count"]
    state["last_trigger_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Log trigger
    trigger_record = {
        "number": trigger_number,
        "date": state["last_trigger_date"],
        "time": datetime.now(timezone.utc).isoformat(),
        "price": current_price,
        "yesterday_close": yesterday_close,
        "drop_pct": drop_pct,
        "type": trigger_type
    }
    state["trigger_history"].append(trigger_record)

    # Save state immediately
    save_state(state)

    logger.info(f"=" * 60)
    logger.info(f"TRIGGER #{trigger_number} OF {MAX_TRIGGERS} EXECUTED")
    logger.info(f"Type: {trigger_type}")
    logger.info(f"BTC: ${current_price:,.2f} | Drop: {drop_pct:.2f}%")
    logger.info(f"=" * 60)

    # Send broker email
    subject, body_html, body_text = generate_broker_email(
        trigger_number, current_price, yesterday_close, drop_pct, trigger_type
    )
    broker_sent = send_email(BROKER_EMAIL, subject, body_html, body_text)

    # Send personal email
    subject, body_html, body_text = generate_personal_email(
        trigger_number, current_price, yesterday_close, drop_pct, trigger_type
    )
    personal_sent = send_email(PERSONAL_EMAIL, subject, body_html, body_text)

    if trigger_number >= MAX_TRIGGERS:
        logger.info("🎉 ALL 15 TRIGGERS COMPLETE! DCA strategy fully executed.")
        # Send completion notification
        send_completion_email()


def send_completion_email():
    """Send a completion summary email."""
    state = load_state()

    subject = "🎉 Red Day DCA Complete - All 15 Triggers Executed"

    # Build trigger history table
    history_rows = ""
    for t in state["trigger_history"]:
        history_rows += f"""
        <tr>
            <td style='padding: 8px; border: 1px solid #ddd;'>{t['number']}</td>
            <td style='padding: 8px; border: 1px solid #ddd;'>{t['date']}</td>
            <td style='padding: 8px; border: 1px solid #ddd;'>${t['price']:,.2f}</td>
            <td style='padding: 8px; border: 1px solid #ddd;'>{t['drop_pct']:.2f}%</td>
        </tr>
        """

    body_html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <h2 style="color: #27ae60;">🎉 Red Day DCA Strategy Complete!</h2>

        <p>Congratulations! All 15 triggers have been executed.</p>

        <h3>Trigger History</h3>
        <table style="border-collapse: collapse; width: 100%;">
            <tr style="background-color: #27ae60; color: white;">
                <th style="padding: 10px; border: 1px solid #ddd;">#</th>
                <th style="padding: 10px; border: 1px solid #ddd;">Date</th>
                <th style="padding: 10px; border: 1px solid #ddd;">BTC Price</th>
                <th style="padding: 10px; border: 1px solid #ddd;">Drop %</th>
            </tr>
            {history_rows}
        </table>

        <h3>Total Deployed</h3>
        <ul>
            <li>Crypto (via Caleb & Brown): £{sum(CORE_CRYPTO_ALLOCATIONS.values()) * 15 + sum(SPEC_CRYPTO_ALLOCATIONS.values()) * 5:,.2f}</li>
            <li>Equities (via eToro): £{sum(ETORO_ALLOCATIONS.values()) * 15:,.2f}</li>
        </ul>

        <p>The monitoring system will now stop checking for triggers.</p>
    </body>
    </html>
    """

    send_email(PERSONAL_EMAIL, subject, body_html)


# =============================================================================
# MAIN SCHEDULER
# =============================================================================

def main():
    """Main entry point - runs the monitoring loop."""
    logger.info("=" * 60)
    logger.info("RED DAY DCA ALERTER STARTING")
    logger.info("=" * 60)

    state = load_state()
    logger.info(f"Current trigger count: {state['trigger_count']} of {MAX_TRIGGERS}")

    if state["trigger_count"] >= MAX_TRIGGERS:
        logger.info("All triggers already completed. Exiting.")
        return

    # Initial check
    check_and_trigger()

    # Schedule regular checks (every minute for intraday)
    schedule.every(CHECK_INTERVAL_SECONDS).seconds.do(check_and_trigger)

    # Schedule daily close check at 00:05 UTC (just after daily candle closes)
    schedule.every().day.at("00:05").do(check_daily_close)

    logger.info(f"Scheduled checks every {CHECK_INTERVAL_SECONDS} seconds")
    logger.info("Daily close check scheduled at 00:05 UTC")
    logger.info("Press Ctrl+C to stop")

    try:
        while True:
            schedule.run_pending()
            time.sleep(1)

            # Re-check if we've completed all triggers
            state = load_state()
            if state["trigger_count"] >= MAX_TRIGGERS:
                logger.info("All triggers complete. Shutting down.")
                break
    except KeyboardInterrupt:
        logger.info("Shutting down...")


if __name__ == "__main__":
    main()
