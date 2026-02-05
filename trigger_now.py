"""
Manual Trigger Script - Run once to fire Trigger #1 immediately
"""

import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from pathlib import Path
import requests

# =============================================================================
# CONFIGURATION (same as main.py)
# =============================================================================

SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "lewis@jackson.ventures")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD", "")

BROKER_EMAIL = "jake@calebandbrown.com"
PERSONAL_EMAIL = "lewis@jackson.ventures"

STATE_FILE = Path("dca_state.json")

CORE_CRYPTO_ALLOCATIONS = {
    "LINK": 666.67,
    "ONDO": 533.33,
    "TAO": 533.33,
    "RENDER": 533.33,
    "TRAC": 333.33,
}

SPEC_CRYPTO_ALLOCATIONS = {
    "BANANA": 100.00,
    "BONK": 100.00,
}

ETORO_ALLOCATIONS = {
    "COIN": 233.33,
    "NVDA": 200.00,
    "PLTR": 166.67,
}

MAX_TRIGGERS = 15

# =============================================================================
# FUNCTIONS
# =============================================================================

def get_btc_price():
    try:
        url = "https://api.binance.com/api/v3/ticker/price"
        response = requests.get(url, params={"symbol": "BTCUSDT"}, timeout=10)
        return float(response.json()["price"])
    except:
        return 97000.00  # Fallback

def load_state():
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
                return json.load(f)
        except:
            pass
    return default_state

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def send_email(to_email, subject, body_html, body_text=None):
    if not SENDER_PASSWORD:
        print(f"ERROR: No SENDER_PASSWORD set")
        print(f"Would send to {to_email}: {subject}")
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

        print(f"✅ Email sent to {to_email}")
        return True
    except Exception as e:
        print(f"❌ Email error: {e}")
        return False

def generate_broker_email(trigger_number, current_price):
    is_third_trigger = trigger_number % 3 == 0
    assets = dict(CORE_CRYPTO_ALLOCATIONS)
    if is_third_trigger:
        assets.update(SPEC_CRYPTO_ALLOCATIONS)

    total_amount = sum(assets.values())
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    subject = f"BUY ORDER - Red Day DCA Trigger #{trigger_number} of {MAX_TRIGGERS}"

    asset_rows = ""
    for asset, amount in assets.items():
        asset_rows += f"<tr><td style='padding: 8px; border: 1px solid #ddd;'>{asset}</td><td style='padding: 8px; border: 1px solid #ddd;'>£{amount:,.2f}</td></tr>\n"

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
                <li><strong>Trigger Type:</strong> Manual trigger (strategy initiation)</li>
                <li><strong>BTC Price:</strong> ${current_price:,.2f}</li>
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

        <p>Please confirm execution once complete.</p>
        <p>Best regards,<br>Lewis</p>

        <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">
        <p style="font-size: 12px; color: #888;">This is an automated message from Lewis's Red Day DCA Alert System.</p>
    </body>
    </html>
    """

    body_text = f"BUY ORDER - Trigger #{trigger_number}\n\nHi Jake,\n\nPlease process with immediate effect:\n\n"
    for asset, amount in assets.items():
        body_text += f"- {asset}: £{amount:,.2f}\n"
    body_text += f"\nTotal: £{total_amount:,.2f}\n\nBest regards,\nLewis"

    return subject, body_html, body_text

def generate_personal_email(trigger_number, current_price):
    total_etoro = sum(ETORO_ALLOCATIONS.values())
    is_third_trigger = trigger_number % 3 == 0
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    subject = f"🔔 ACTION REQUIRED: eToro Purchase - Trigger #{trigger_number}"

    etoro_rows = ""
    for asset, amount in ETORO_ALLOCATIONS.items():
        etoro_rows += f"<tr><td style='padding: 8px; border: 1px solid #ddd;'>{asset}</td><td style='padding: 8px; border: 1px solid #ddd;'>£{amount:,.2f}</td></tr>\n"

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
            <p><strong>Manual trigger</strong> (strategy initiation)</p>
            <p>BTC Price: ${current_price:,.2f}</p>
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

        <div style="background-color: #f0f0f0; padding: 15px; border-radius: 5px; margin-top: 30px;">
            <h4 style="margin-top: 0;">Progress</h4>
            <p>Triggers completed: <strong>{trigger_number} of {MAX_TRIGGERS}</strong></p>
            <p>Remaining: <strong>{MAX_TRIGGERS - trigger_number}</strong></p>
        </div>

        <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">
        <p style="font-size: 12px; color: #888;">Red Day DCA Alert System</p>
    </body>
    </html>
    """

    body_text = f"TRIGGER #{trigger_number} - eToro Action Required\n\n"
    for asset, amount in ETORO_ALLOCATIONS.items():
        body_text += f"- {asset}: £{amount:,.2f}\n"

    return subject, body_html, body_text

# =============================================================================
# MAIN - FIRE TRIGGER #1
# =============================================================================

if __name__ == "__main__":
    print("=" * 50)
    print("MANUAL TRIGGER - RED DAY DCA")
    print("=" * 50)

    state = load_state()
    current_trigger = state["trigger_count"] + 1

    print(f"Current trigger count: {state['trigger_count']}")
    print(f"Firing trigger #{current_trigger}...")

    # Get current BTC price
    btc_price = get_btc_price()
    print(f"BTC Price: ${btc_price:,.2f}")

    # Send broker email
    print("\nSending broker email to Jake...")
    subject, body_html, body_text = generate_broker_email(current_trigger, btc_price)
    send_email(BROKER_EMAIL, subject, body_html, body_text)

    # Send personal email
    print("\nSending personal email...")
    subject, body_html, body_text = generate_personal_email(current_trigger, btc_price)
    send_email(PERSONAL_EMAIL, subject, body_html, body_text)

    # Update state
    state["trigger_count"] = current_trigger
    state["last_trigger_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    state["trigger_history"].append({
        "number": current_trigger,
        "date": state["last_trigger_date"],
        "time": datetime.now(timezone.utc).isoformat(),
        "price": btc_price,
        "type": "Manual trigger"
    })
    save_state(state)

    print("\n" + "=" * 50)
    print(f"✅ TRIGGER #{current_trigger} COMPLETE")
    print(f"Remaining triggers: {MAX_TRIGGERS - current_trigger}")
    print("=" * 50)
