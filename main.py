"""
Red Day DCA Alerter
====================
Automated price monitoring and alert system for Lewis's DCA strategy.

Monitors BTC price and triggers buy alerts when:
- Intraday: Price drops ≥4.7% below yesterday's close
- OR Close-to-close: Price closes ≥3.3% down from prior close
- OR 3 consecutive daily closes each ≥1% red
- Price level triggers: BTC crosses down through key levels

All triggers require BTC to be below $69,000.

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
import psycopg2
from psycopg2.extras import Json

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
# Tiered intraday: each level fires independently within a single day
INTRADAY_THRESHOLDS = [-4.7, -7.0, -9.5, -12.0]
CLOSE_TO_CLOSE_THRESHOLD = -3.3  # Percentage drop close-to-close

# Consecutive red days trigger
CONSECUTIVE_RED_DAYS = 3  # Number of consecutive red closes required
CONSECUTIVE_RED_THRESHOLD = (
    -1.0
)  # Each day must be at least this % red (close-to-close)

# Global price floor - ALL triggers require BTC to be below this price
TRIGGER_PRICE_CEILING = 69000  # USD - no triggers fire above this

# Special price level triggers (can fire same day as other triggers, once per day each)
# Triggers when BTC drops DOWN through these levels
PRICE_LEVEL_TRIGGERS = [52000, 51000, 50000, 40000]  # USD - must be in descending order

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
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("dca_alerter.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# =============================================================================
# STATE MANAGEMENT (PostgreSQL-backed, falls back to JSON file if no DB URL)
# =============================================================================

DATABASE_URL = os.environ.get("DATABASE_URL")

DEFAULT_STATE = {
    "trigger_count": 0,
    "last_trigger_date": None,
    "yesterday_close": None,
    "yesterday_close_date": None,
    "trigger_history": [],
    "last_price": None,
    "price_levels_triggered_today": [],
    "price_levels_date": None,
    "intraday_levels_triggered_today": [],
    "intraday_levels_date": None,
    "daily_closes": [],
    "consecutive_red_triggered_date": None,
}


def get_db_conn():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    """Create state table and seed from dca_state.json if empty."""
    if not DATABASE_URL:
        logger.warning("No DATABASE_URL — using local JSON file for state")
        return

    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS dca_state (
                        id INTEGER PRIMARY KEY DEFAULT 1,
                        state JSONB NOT NULL
                    )
                """)
                # Seed from local JSON file if table is empty
                cur.execute("SELECT COUNT(*) FROM dca_state")
                if cur.fetchone()[0] == 0:
                    seed = dict(DEFAULT_STATE)
                    if STATE_FILE.exists():
                        try:
                            with open(STATE_FILE) as f:
                                file_state = json.load(f)
                            for key in DEFAULT_STATE:
                                if key in file_state:
                                    seed[key] = file_state[key]
                            logger.info("Seeded DB state from dca_state.json")
                        except Exception as e:
                            logger.warning(
                                f"Could not read state file for seeding: {e}"
                            )
                    cur.execute(
                        "INSERT INTO dca_state (id, state) VALUES (1, %s)",
                        (Json(seed),),
                    )
                conn.commit()
        logger.info("DB initialised")
    except Exception as e:
        logger.error(f"DB init failed: {e}")
        raise


def load_state():
    """Load state from DB (or JSON file if no DB)."""
    if not DATABASE_URL:
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE) as f:
                    state = json.load(f)
                for key in DEFAULT_STATE:
                    if key not in state:
                        state[key] = DEFAULT_STATE[key]
                return state
            except Exception as e:
                logger.error(f"Error loading state file: {e}")
        return dict(DEFAULT_STATE)

    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT state FROM dca_state WHERE id = 1")
                row = cur.fetchone()
                if row:
                    state = row[0]
                    for key in DEFAULT_STATE:
                        if key not in state:
                            state[key] = DEFAULT_STATE[key]
                    return state
    except Exception as e:
        logger.error(f"Error loading state from DB: {e}")

    return dict(DEFAULT_STATE)


def save_state(state):
    """Persist state to DB (or JSON file if no DB)."""
    if not DATABASE_URL:
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving state file: {e}")
        return

    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE dca_state SET state = %s WHERE id = 1", (Json(state),)
                )
            conn.commit()
    except Exception as e:
        logger.error(f"Error saving state to DB: {e}")


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
        params = {"symbol": "BTCUSDT", "interval": "1d", "limit": days_ago + 1}
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
        params = {"symbol": "BTCUSDT", "interval": "1d", "limit": 1}
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


def generate_broker_email(
    trigger_number, current_price, yesterday_close, drop_pct, trigger_type
):
    """Generate email content for Jake at Caleb & Brown."""

    # Determine if this is a 3rd trigger (includes spec assets)
    is_third_trigger = trigger_number % 3 == 0

    # Build asset list
    assets = dict(CORE_CRYPTO_ALLOCATIONS)
    if is_third_trigger:
        assets.update(SPEC_CRYPTO_ALLOCATIONS)

    total_amount = sum(assets.values())

    # Build simple asset list for email
    asset_lines_html = ""
    asset_lines_text = ""
    for asset, amount in assets.items():
        asset_lines_html += f"<li>£{amount:,.2f} of {asset}</li>\n"
        asset_lines_text += f"- £{amount:,.2f} of {asset}\n"

    subject = "Buy Order"

    body_html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <p>Hi Jake,</p>

        <p>I'd like to place the following buy order:</p>

        <ul>
{asset_lines_html}
        </ul>

        <p>Please use available USDT, fiat USD, or fiat GBP to execute.</p>

        <p>Please confirm once complete.</p>

        <p>Thanks,<br>Lewis</p>
    </body>
    </html>
    """

    body_text = f"""Hi Jake,

I'd like to place the following buy order:

{asset_lines_text}
Please use available USDT, fiat USD, or fiat GBP to execute.

Please confirm once complete.

Thanks,
Lewis
"""

    return subject, body_html, body_text


def generate_personal_email(
    trigger_number, current_price, yesterday_close, drop_pct, trigger_type
):
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

    # Get current price first (needed for price level checks)
    current_price = get_binance_btc_price()
    if current_price is None:
        logger.error("Could not fetch current price. Skipping check.")
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
        logger.info(
            f"Updated yesterday's close: ${yesterday_close:,.2f} ({yesterday_date})"
        )

    # Calculate intraday drop percentage
    drop_pct = ((current_price - yesterday_close) / yesterday_close) * 100

    logger.info(
        f"BTC: ${current_price:,.2f} | Yesterday: ${yesterday_close:,.2f} | Change: {drop_pct:+.2f}%"
    )

    # =========================================================================
    # GLOBAL PRICE CEILING CHECK - no triggers above this price
    # =========================================================================
    if current_price >= TRIGGER_PRICE_CEILING:
        logger.info(
            f"BTC ${current_price:,.2f} is above ${TRIGGER_PRICE_CEILING:,} ceiling. No triggers allowed."
        )
        # Still update last_price for downward cross detection
        state["last_price"] = current_price
        save_state(state)
        return

    # Get current date
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # =========================================================================
    # RESET DAILY TRIGGERS IF NEW DAY
    # =========================================================================
    if state.get("price_levels_date") != today:
        state["price_levels_triggered_today"] = []
        state["price_levels_date"] = today
        save_state(state)
        logger.info(f"New day - reset price level triggers")

    if state.get("intraday_levels_date") != today:
        state["intraday_levels_triggered_today"] = []
        state["intraday_levels_date"] = today
        save_state(state)
        logger.info(f"New day - reset intraday tier triggers")

    # =========================================================================
    # CHECK SPECIAL PRICE LEVEL TRIGGERS (once per day each, on downward cross)
    # =========================================================================
    last_price = state.get("last_price")

    # Update last_price for next check (do this before checking triggers)
    state["last_price"] = current_price
    save_state(state)

    # Only check for downward crosses if we have a previous price
    if last_price is not None:
        for price_level in PRICE_LEVEL_TRIGGERS:
            # Check if we crossed DOWN through this level
            # (last price was above, current price is at or below)
            crossed_down = last_price > price_level and current_price <= price_level
            not_triggered_today = price_level not in state.get(
                "price_levels_triggered_today", []
            )

            if crossed_down and not_triggered_today:
                logger.info(
                    f"🔔 PRICE LEVEL TRIGGER! BTC crossed down through ${price_level:,} (${last_price:,.2f} → ${current_price:,.2f})"
                )
                trigger_type = f"Price level (${price_level:,})"

                # Execute trigger (this will increment count and send emails)
                execute_trigger(
                    state,
                    current_price,
                    yesterday_close,
                    drop_pct,
                    trigger_type,
                    is_price_level=True,
                )

                # Mark this price level as triggered today
                state = load_state()  # Reload as execute_trigger modified it
                if "price_levels_triggered_today" not in state:
                    state["price_levels_triggered_today"] = []
                state["price_levels_triggered_today"].append(price_level)
                save_state(state)

                # Check if max triggers reached after this one
                if state["trigger_count"] >= MAX_TRIGGERS:
                    return

    # =========================================================================
    # CHECK TIERED INTRADAY TRIGGERS (each level fires independently per day)
    # =========================================================================
    for threshold in INTRADAY_THRESHOLDS:
        if drop_pct <= threshold and threshold not in state.get(
            "intraday_levels_triggered_today", []
        ):
            trigger_type = f"Intraday tier {threshold}% (drop: {drop_pct:.2f}%)"
            logger.info(
                f"🔔 INTRADAY TIER TRIGGER! {threshold}% breached. Drop: {drop_pct:.2f}%"
            )

            execute_trigger(
                state,
                current_price,
                yesterday_close,
                drop_pct,
                trigger_type,
                is_price_level=True,
            )

            state = load_state()
            state["intraday_levels_triggered_today"].append(threshold)
            save_state(state)

            if state["trigger_count"] >= MAX_TRIGGERS:
                return


def check_daily_close():
    """Check at end of day for close-to-close trigger and consecutive red days."""
    state = load_state()

    # Check if we've already hit max triggers
    if state["trigger_count"] >= MAX_TRIGGERS:
        return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Get today's close and yesterday's close
    today_close = get_today_close()
    yesterday_close, _ = get_binance_daily_close(days_ago=1)

    if today_close is None or yesterday_close is None:
        return

    # Calculate close-to-close change
    drop_pct = ((today_close - yesterday_close) / yesterday_close) * 100

    # =========================================================================
    # TRACK DAILY CLOSES FOR CONSECUTIVE RED DAY DETECTION
    # =========================================================================
    daily_closes = state.get("daily_closes", [])

    # Only add if we haven't already recorded today
    if not daily_closes or daily_closes[-1].get("date") != today:
        daily_closes.append(
            {"date": today, "close": today_close, "change_pct": drop_pct}
        )
        # Keep only the last N days we need
        state["daily_closes"] = daily_closes[-(CONSECUTIVE_RED_DAYS + 1) :]
        save_state(state)
        logger.info(f"Recorded daily close: ${today_close:,.2f} ({drop_pct:+.2f}%)")

    # =========================================================================
    # PRICE CEILING CHECK
    # =========================================================================
    if today_close >= TRIGGER_PRICE_CEILING:
        logger.info(
            f"BTC close ${today_close:,.2f} is above ${TRIGGER_PRICE_CEILING:,} ceiling. No triggers."
        )
        return

    # =========================================================================
    # CHECK CONSECUTIVE RED DAYS TRIGGER
    # =========================================================================
    if (
        len(state["daily_closes"]) >= CONSECUTIVE_RED_DAYS
        and state.get("consecutive_red_triggered_date") != today
        and state["last_trigger_date"] != today
    ):
        recent = state["daily_closes"][-CONSECUTIVE_RED_DAYS:]
        all_red = all(d["change_pct"] <= CONSECUTIVE_RED_THRESHOLD for d in recent)

        if all_red:
            dates_str = ", ".join(
                f"{d['date']} ({d['change_pct']:+.2f}%)" for d in recent
            )
            trigger_type = f"Consecutive {CONSECUTIVE_RED_DAYS} red days ≤{CONSECUTIVE_RED_THRESHOLD}% each: {dates_str}"
            logger.info(f"🔔 CONSECUTIVE RED DAYS TRIGGER! {dates_str}")

            state["consecutive_red_triggered_date"] = today
            save_state(state)

            execute_trigger(state, today_close, yesterday_close, drop_pct, trigger_type)

            # Reload state after trigger
            state = load_state()
            if state["trigger_count"] >= MAX_TRIGGERS:
                return

    # =========================================================================
    # CHECK CLOSE-TO-CLOSE TRIGGER
    # =========================================================================
    if state["last_trigger_date"] == today:
        return

    if drop_pct <= CLOSE_TO_CLOSE_THRESHOLD:
        trigger_type = f"Close-to-close ({drop_pct:.2f}% ≤ {CLOSE_TO_CLOSE_THRESHOLD}%)"
        logger.info(f"🔔 CLOSE-TO-CLOSE TRIGGER FIRED! Drop: {drop_pct:.2f}%")
        execute_trigger(state, today_close, yesterday_close, drop_pct, trigger_type)


def execute_trigger(
    state, current_price, yesterday_close, drop_pct, trigger_type, is_price_level=False
):
    """Execute the trigger: increment count, send emails.

    Price level triggers don't consume the daily regular trigger slot,
    so they won't block intraday/close-to-close/consecutive red triggers.
    """

    # Increment trigger count
    state["trigger_count"] += 1
    trigger_number = state["trigger_count"]

    # Only set last_trigger_date for non-price-level triggers
    # Price level triggers can co-exist with one regular trigger per day
    if not is_price_level:
        state["last_trigger_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Log trigger
    trigger_record = {
        "number": trigger_number,
        "date": state["last_trigger_date"],
        "time": datetime.now(timezone.utc).isoformat(),
        "price": current_price,
        "yesterday_close": yesterday_close,
        "drop_pct": drop_pct,
        "type": trigger_type,
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

    init_db()
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
