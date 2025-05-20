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
                      output_mint TEXT,
                      initial_price REAL NOT NULL,
                      upper_bound_pct REAL NOT NULL,
                      lower_bound_pct REAL NOT NULL,
                      alarm_upper REAL NOT NULL,
                      alarm_lower REAL NOT NULL,\
                      use_aggregator INTEGER DEFAULT 0,
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

def send_telegram_message(message):
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

@app.route('/get_jupiter_price')
def get_jupiter_price():
    input_mint = request.args.get('inputMint')
    output_mint = request.args.get('outputMint')
    amount = request.args.get('amount', '1000000')

    url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount}"

    try:
        response = requests.get(url, headers={'User-Agent': 'TokenPriceTracker/1.0'})
        return jsonify(response.json())
    except Exception as e:
        return jsonify({'error': str(e)}), 500

import requests

def get_aggregator_price(input_mint, output_mint):
    """Fetch price from Jupiter Aggregator API."""
    amount = 1_000_000  # amount in lamports (e.g., 1 USDC = 10⁶)
    url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount}"
    try:
        response = requests.get(url)
        data = response.json()
        if 'data' in data and len(data['data']) > 0:
            out_amount = int(data['data'][0]['outAmount'])
            return out_amount / 1_000_000  # Convert lamports to actual token price
    except Exception as e:
        print(f"Aggregator API error: {e}")
    return None

def check_prices():
    """Background task to check prices and send alerts."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM tokens")
    tokens = c.fetchall()

    for token in tokens:
        mint_address = token['mint_address']
        output_mint = token['output_mint']  # New field for Jupiter output token
        use_aggregator = token['use_aggregator']  # 1 if aggregator checkbox was ticked
        initial_price = token['initial_price']
        upper_bound_pct = token['upper_bound_pct']
        lower_bound_pct = token['lower_bound_pct']
        alarm_upper = token['alarm_upper']
        alarm_lower = token['alarm_lower']

        if use_aggregator:
            current_price = get_aggregator_price(mint_address, output_mint)
        else:
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
            print("message sent")
            c.execute("UPDATE tokens SET last_alert = ? WHERE id = ?", ('upper', token['id']))
        elif current_price <= alarm_lower and token['last_alert'] != 'lower':
            message = (f"🚨 ALERT: Token {mint_address[:6]}... price (${current_price:.2f}) "
                      f"dropped below lower alarm bound (${alarm_lower:.2f})")
            send_telegram_message(message)
            print("message sent")
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

    edit_id = request.args.get('edit')
    edit_token = None
    if edit_id:
        c.execute("SELECT * FROM tokens WHERE id = ?", (edit_id,))
        edit_token = c.fetchone()

    conn.close()
    return render_template('index.html', tokens=tokens, edit_token=edit_token)

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_token(id):
    conn = get_db_connection()
    c = conn.cursor()
    try:
        if request.method == 'POST':
            mint_address = request.form['mint_address']
            output_mint = request.form.get('output_mint', '')
            initial_price = float(request.form['initial_price'])
            upper_bound_pct = float(request.form['upper_bound_pct'])
            lower_bound_pct = float(request.form['lower_bound_pct'])
            use_aggregator = 1 if 'use_aggregator' in request.form else 0
    
            # Recalculate alarm thresholds
            alarm_upper = initial_price * (1 + upper_bound_pct / 100)
            alarm_lower = initial_price * (1 - lower_bound_pct / 100)
    
            # Update the token in the database
            c.execute('''UPDATE tokens
                         SET mint_address = ?, output_mint = ?, initial_price = ?, upper_bound_pct = ?, 
                             lower_bound_pct = ?, alarm_upper = ?, alarm_lower = ?, use_aggregator = ?
                         WHERE id = ?''',
                      (mint_address, output_mint, initial_price, upper_bound_pct,
                       lower_bound_pct, alarm_upper, alarm_lower, use_aggregator, id))
            conn.commit()
            conn.close()
            return redirect(url_for('index'))
    
        # GET request — show form with current data
        c.execute("SELECT * FROM tokens WHERE id = ?", (id,))
        token = c.fetchone()
        conn.close()
        flash(f"Token with mint address {mint_address[:6]}... updated successfully!")
        return redirect(url_for('index'))
    except Exception as e:
        logger.error(f"Error updating token: {e}")
        flash("Error: Could not update token. Please check the form and try again.")
        return redirect(url_for('index', edit=id))


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
        output_mint = request.form.get('output_mint', '')
        use_aggregator = 1 if 'use_aggregator' in request.form else 0
        ...
        c.execute('''INSERT INTO tokens (mint_address, output_mint, initial_price, upper_bound_pct, lower_bound_pct,
                     alarm_upper, alarm_lower, use_aggregator)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                  (mint_address, output_mint, initial_price, upper_bound_pct, lower_bound_pct,
                   alarm_upper, alarm_lower, use_aggregator))
        # c.execute('''INSERT INTO tokens (mint_address, initial_price, upper_bound_pct, lower_bound_pct,
        #              alarm_upper, alarm_lower)
        #              VALUES (?, ?, ?, ?, ?, ?)''',
        #              (mint_address, initial_price, upper_bound_pct, lower_bound_pct, alarm_upper, alarm_lower))
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
    c.execute("SELECT id, mint_address, output_mint, use_aggregator FROM tokens")
    tokens = c.fetchall()
    conn.close()

    prices = {}
    for token in tokens:
        if token['use_aggregator']:
            price = get_aggregator_price(token['mint_address'], token['output_mint'])
        else:
            price = get_token_price(token['mint_address'])
        prices[token['id']] = price

    return jsonify(prices)
    
# Start background scheduler with UTC timezone
init_db()
scheduler = BackgroundScheduler(timezone=pytz.UTC)
scheduler.add_job(check_prices, 'interval', seconds=20)
scheduler.start()

# if __name__ == '__main__':
#     init_db()
#     app.run(debug=True)
