# from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
# import sqlite3
# import os
# import requests
# from apscheduler.schedulers.background import BackgroundScheduler
# from datetime import datetime
# import logging
# import pytz
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import sqlite3
import requests
from apscheduler.schedulers.background import BackgroundScheduler
import logging

app = Flask(__name__)
app.secret_key = 'supersecretkey'
RAYDIUM_API = "https://api.raydium.io/v2/main/price"

# Telegram Bot Config
TELEGRAM_BOT_TOKEN = "8066450400:AAENAonrvuB7lNXnGqZbe5jdEXxF5zYiP5g"
TELEGRAM_CHAT_ID =  "5249408527"


# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------- Database -------------------

def get_db_connection():
    conn = sqlite3.connect('tokens.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mint_address TEXT NOT NULL,
                output_mint TEXT,
                initial_price REAL,
                upper_bound_pct REAL NOT NULL,
                lower_bound_pct REAL NOT NULL,
                alarm_upper REAL NOT NULL,
                alarm_lower REAL NOT NULL
            );
        ''')
    logger.info("Database initialized.")

# ------------------- Helper: Price Fetching -------------------

def fetch_price(mint_address, output_mint=None):
    try:
        if output_mint:
            url = f"https://quote-api.jup.ag/v6/quote?inputMint={mint_address}&outputMint={output_mint}&amount=1000000"
            res = requests.get(url)
            res.raise_for_status()
            data = res.json()
            return float(data['data'][0]['outAmount']) / 1000000
        else:
            url = f"https://api.radium.to/token/price/{mint_address}"
            res = requests.get(url)
            res.raise_for_status()
            data = res.json()
            return float(data['priceUi'])
    except Exception as e:
        logger.error(f"Price fetch error for {mint_address} (output: {output_mint}): {e}")
        return None

# ------------------- Helper: Telegram -------------------

def send_telegram_alert(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message}
        res = requests.post(url, data=payload)
        res.raise_for_status()
        logger.info(f"Telegram alert sent: {message}")
    except Exception as e:
        logger.error(f"Failed to send Telegram alert: {e}")

# ------------------- Scheduler -------------------

def check_token_prices():
    while True:
        conn = get_db_connection()
        tokens = conn.execute('SELECT * FROM tokens').fetchall()
        conn.close()

        for token in tokens:
            price = fetch_price(token['mint_address'], token['output_mint'])
            if price is None:
                continue

            if price >= token['alarm_upper']:
                msg = f"🚨 {token['mint_address']} price ABOVE upper alarm limit: {price:.6f} ≥ {token['alarm_upper']}"
                send_telegram_alert(msg)

            elif price <= token['alarm_lower']:
                msg = f"⚠️ {token['mint_address']} price BELOW lower alarm limit: {price:.6f} ≤ {token['alarm_lower']}"
                send_telegram_alert(msg)

        time.sleep(60)  # check every 60 seconds

# ------------------- Routes -------------------

@app.route('/')
def index():
    conn = get_db_connection()
    tokens = conn.execute('SELECT * FROM tokens').fetchall()
    conn.close()
    return render_template('index.html', tokens=tokens, edit_token=None)

@app.route('/add', methods=['POST'])
def add_token():
    mint_address = request.form['mint_address']
    output_mint = request.form.get('output_mint', '')
    auto_price = 'auto_price' in request.form
    initial_price = request.form.get('initial_price', 0)

    if auto_price:
        initial_price = fetch_price(mint_address, output_mint)
        if initial_price is None:
            flash("Failed to fetch initial price.")
            return redirect(url_for('index'))
        logger.info(f"Fetched initial price for {mint_address}: {initial_price}")
    else:
        initial_price = float(initial_price)

    conn = get_db_connection()
    conn.execute('''
        INSERT INTO tokens (mint_address, output_mint, initial_price, upper_bound_pct, lower_bound_pct, alarm_upper, alarm_lower)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        mint_address,
        output_mint,
        initial_price,
        float(request.form['upper_bound_pct']),
        float(request.form['lower_bound_pct']),
        float(request.form['alarm_upper']),
        float(request.form['alarm_lower'])
    ))
    conn.commit()
    conn.close()
    flash("Token added successfully.")
    return redirect(url_for('index'))

@app.route('/edit/<int:id>')
def edit_token(id):
    conn = get_db_connection()
    token = conn.execute('SELECT * FROM tokens WHERE id = ?', (id,)).fetchone()
    tokens = conn.execute('SELECT * FROM tokens').fetchall()
    conn.close()
    return render_template('index.html', edit_token=token, tokens=tokens)

@app.route('/update/<int:id>', methods=['POST'])
def update_token(id):
    mint_address = request.form['mint_address']
    output_mint = request.form.get('output_mint', '')
    auto_price = 'auto_price' in request.form
    initial_price = request.form.get('initial_price', 0)

    if auto_price:
        initial_price = fetch_price(mint_address, output_mint)
        if initial_price is None:
            flash("Failed to fetch price.")
            return redirect(url_for('index'))
        logger.info(f"Fetched updated price for {mint_address}: {initial_price}")
    else:
        initial_price = float(initial_price)

    conn = get_db_connection()
    conn.execute('''
        UPDATE tokens SET
            mint_address = ?, output_mint = ?, initial_price = ?, upper_bound_pct = ?,
            lower_bound_pct = ?, alarm_upper = ?, alarm_lower = ?
        WHERE id = ?
    ''', (
        mint_address,
        output_mint,
        initial_price,
        float(request.form['upper_bound_pct']),
        float(request.form['lower_bound_pct']),
        float(request.form['alarm_upper']),
        float(request.form['alarm_lower']),
        id
    ))
    conn.commit()
    conn.close()
    flash("Token updated successfully.")
    return redirect(url_for('index'))

@app.route('/delete/<int:id>')
def delete_token(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM tokens WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    flash("Token deleted.")
    return redirect(url_for('index'))

@app.route('/get_prices')
def get_prices():
    conn = get_db_connection()
    tokens = conn.execute('SELECT id, mint_address, output_mint FROM tokens').fetchall()
    conn.close()
    prices = {}

    try:
        # Fetch all prices from Raydium once
        raydium_response = requests.get("https://api.raydium.io/v2/main/price")
        raydium_prices = raydium_response.json()
    except Exception as e:
        raydium_prices = {}
        logger.error(f"Failed to fetch Raydium prices: {e}")

    for token in tokens:
        try:
            token_id = str(token['id'])
            mint_address = token['mint_address']
            output_mint = token['output_mint']

            if output_mint:
                # Use Jupiter API if output_mint is specified
                url = f"https://quote-api.jup.ag/v6/quote?inputMint={mint_address}&outputMint={output_mint}&amount=1000000"
                res = requests.get(url)
                data = res.json()
                price = float(data['data'][0]['outAmount']) / 1000000
            else:
                # Use Raydium prices if output_mint is not provided
                if mint_address in raydium_prices:
                    price = float(raydium_prices[mint_address]['price'])
                else:
                    raise ValueError("Mint address not found in Raydium price list")

            prices[token_id] = round(price, 6)
            logger.info(f"Price for token {token_id} fetched: {price}")
        except Exception as e:
            prices[token_id] = "N/A"
            logger.error(f"Error fetching price for token {token_id}: {e}")

    return jsonify(prices)


# ------------------- Start -------------------

init_db()
scheduler = BackgroundScheduler()
scheduler.add_job(check_token_prices, 'interval', minutes=1)
scheduler.start()
# try:
#     logger.info("Starting Flask app...")
#     app.run(debug=True, use_reloader=False)
# except (KeyboardInterrupt, SystemExit):
#     logger.info("Shutting down scheduler...")
    # scheduler.shutdown()
