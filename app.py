from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import sqlite3
import os
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import logging
import pytz

app = Flask(__name__)
app.secret_key = 'supersecretkey'  # For flash messages
DATABASE = 'tokens.db'
TELEGRAM_BOT_TOKEN = "8066450400:AAENAonrvuB7lNXnGqZbe5jdEXxF5zYiP5g"
TELEGRAM_USER_ID = "5249408527"
RAYDIUM_API = "https://api.raydium.io/v2/main/price"

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_db():
    """Initialize SQLite database."""
    if not os.path.exists(DATABASE):
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('''CREATE TABLE tokens
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      mint_address TEXT NOT NULL,
                      initial_price REAL NOT NULL,
                      upper_bound_pct REAL NOT NULL,
                      lower_bound_pct REAL NOT NULL,
                      alarm_upper REAL NOT NULL,
                      alarm_lower REAL NOT NULL,
                      last_alert TEXT)''')
        conn.commit()
        conn.close()

def get_db_connection():
    """Get database connection."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def get_token_price(mint_address):
    """Fetch token price from Raydium API using mint address."""
    try:
        response = requests.get(RAYDIUM_API)
        response.raise_for_status()
        prices = response.json()
        return prices.get(mint_address)
    except requests.RequestException as e:
        logger.error(f"Error fetching price for mint address {mint_address}: {e}")
        return None

def   _telegram_message(message):
    """Send message via Telegram bot."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_USER_ID,
        "text": message
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        logger.info("Telegram message sent successfully")
    except requests.RequestException as e:
        logger.error(f"Error sending Telegram message: {e}")

def check_prices():
    """Background task to check prices and send alerts."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM tokens")
    tokens = c.fetchall()

    for token in tokens:
        mint_address = token['mint_address']
        initial_price = token['initial_price']
        upper_bound_pct = token['upper_bound_pct']
        lower_bound_pct = token['lower_bound_pct']
        alarm_upper = token['alarm_upper']
        alarm_lower = token['alarm_lower']

        current_price = get_token_price(mint_address)
        if current_price is None:
            continue

        upper_bound = initial_price * (1 + upper_bound_pct / 100)
        lower_bound = initial_price * (1 - lower_bound_pct / 100)

        # Check if price exceeds alarm bounds
        if current_price >= alarm_upper and token['last_alert'] != 'upper':
            message = (f"🚨 ALERT: Token {mint_address[:6]}... price (${current_price:.2f}) "
                      f"exceeded upper alarm bound (${alarm_upper:.2f})")
            send_telegram_message(message)
            c.execute("UPDATE tokens SET last_alert = ? WHERE id = ?", ('upper', token['id']))
        elif current_price <= alarm_lower and token['last_alert'] != 'lower':
            message = (f"🚨 ALERT: Token {mint_address[:6]}... price (${current_price:.2f}) "
                      f"dropped below lower alarm bound (${alarm_lower:.2f})")
            send_telegram_message(message)
            c.execute("UPDATE tokens SET last_alert = ? WHERE id = ?", ('lower', token['id']))
        elif lower_bound <= current_price <= upper_bound:
            # Reset alert if price returns to normal range
            c.execute("UPDATE tokens SET last_alert = NULL WHERE id = ?", (token['id'],))

        conn.commit()
    conn.close()

@app.route('/')
def index():
    """Display form and list of tracked tokens."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM tokens")
    tokens = c.fetchall()
    conn.close()
    return render_template('index.html', tokens=tokens)

@app.route('/add', methods=['POST'])
def add_token():
    """Add a new token to track."""
    try:
        mint_address = request.form['mint_address']
        use_auto_price = 'auto_price' in request.form
        initial_price = float(request.form['initial_price']) if not use_auto_price else None
        upper_bound_pct = float(request.form['upper_bound_pct'])
        lower_bound_pct = float(request.form['lower_bound_pct'])
        alarm_upper = float(request.form['alarm_upper'])
        alarm_lower = float(request.form['alarm_lower'])

        if use_auto_price:
            initial_price = get_token_price(mint_address)
            if initial_price is None:
                flash(f"Could not fetch price for mint address {mint_address}. Please enter manually.")
                return redirect(url_for('index'))

        if alarm_lower >= initial_price or alarm_upper <= initial_price:
            flash("Alarm bounds must be outside initial price range.")
            return redirect(url_for('index'))

        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''INSERT INTO tokens (mint_address, initial_price, upper_bound_pct, lower_bound_pct,
                     alarm_upper, alarm_lower)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                     (mint_address, initial_price, upper_bound_pct, lower_bound_pct, alarm_upper, alarm_lower))
        conn.commit()
        conn.close()
        flash(f"Token with mint address {mint_address[:6]}... added successfully!")
        return redirect(url_for('index'))
    except KeyError as e:
        logger.error(f"Form field missing: {e}")
        flash(f"Error: Missing form field {e}. Please check the form and try again.")
        return redirect(url_for('index'))
    except ValueError as e:
        logger.error(f"Invalid form data: {e}")
        flash("Error: Invalid input data. Please ensure all fields are valid numbers.")
        return redirect(url_for('index'))

@app.route('/delete/<int:id>')
def delete_token(id):
    """Delete a token from tracking."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM tokens WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    flash("Token deleted successfully!")
    return redirect(url_for('index'))

@app.route('/get_prices', methods=['GET'])
def get_prices():
    """Return current prices for all tracked tokens."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, mint_address FROM tokens")
    tokens = c.fetchall()
    conn.close()

    prices = {}
    for token in tokens:
        price = get_token_price(token['mint_address'])
        prices[token['id']] = price if price is not None else "N/A"

    return jsonify(prices)

# Start background scheduler with UTC timezone
init_db()
scheduler = BackgroundScheduler(timezone=pytz.UTC)
scheduler.add_job(check_prices, 'interval', seconds=60)
scheduler.start()

# if __name__ == '__main__':
#     init_db()
#     app.run(debug=True)
