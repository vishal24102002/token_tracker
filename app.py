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


# Logger setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Telegram Bot Config
TELEGRAM_BOT_TOKEN = "8066450400:AAENAonrvuB7lNXnGqZbe5jdEXxF5zYiP5g"
TELEGRAM_CHAT_ID =  "5249408527"

def get_db_connection():
    return sqlite3.connect('tokens.db', detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)

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

@app.route('/')
def index():
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        tokens = conn.execute('SELECT * FROM tokens').fetchall()
    return render_template('index.html', tokens=tokens, edit_token=None)

@app.route('/add', methods=['POST'])
def add_token():
    try:
        mint_address = request.form['mint_address']
        output_mint = request.form.get('output_mint', '')
        auto_price = 'auto_price' in request.form
        initial_price = request.form.get('initial_price', 0)

        if auto_price:
            url = f"https://quote-api.jup.ag/v6/quote?inputMint={mint_address}&outputMint={output_mint}&amount=1000000"
            res = requests.get(url)
            data = res.json()
            initial_price = float(data['data'][0]['outAmount']) / 1000000
            logger.info(f"Auto-fetched price for {mint_address}: {initial_price}")
        else:
            initial_price = float(initial_price)

        with get_db_connection() as conn:
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

        logger.info(f"Token added: {mint_address}")
        flash("Token added successfully.")
    except Exception as e:
        logger.error(f"Error adding token: {e}")
        flash("Failed to add token.")
    return redirect(url_for('index'))

@app.route('/edit/<int:id>')
def edit_token(id):
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        token = conn.execute('SELECT * FROM tokens WHERE id = ?', (id,)).fetchone()
        tokens = conn.execute('SELECT * FROM tokens').fetchall()
    return render_template('index.html', edit_token=token, tokens=tokens)

@app.route('/update/<int:id>', methods=['POST'])
def update_token(id):
    try:
        mint_address = request.form['mint_address']
        output_mint = request.form.get('output_mint', '')
        auto_price = 'auto_price' in request.form
        initial_price = request.form.get('initial_price', 0)

        if auto_price:
            url = f"https://quote-api.jup.ag/v6/quote?inputMint={mint_address}&outputMint={output_mint}&amount=1000000"
            res = requests.get(url)
            data = res.json()
            initial_price = float(data['data'][0]['outAmount']) / 1000000
            logger.info(f"Auto-updated price for {mint_address}: {initial_price}")
        else:
            initial_price = float(initial_price)

        with get_db_connection() as conn:
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

        logger.info(f"Token updated: ID {id} - {mint_address}")
        flash("Token updated successfully.")
    except Exception as e:
        logger.error(f"Error updating token: {e}")
        flash("Failed to update token.")
    return redirect(url_for('index'))

@app.route('/delete/<int:id>')
def delete_token(id):
    try:
        with get_db_connection() as conn:
            conn.execute('DELETE FROM tokens WHERE id = ?', (id,))
            conn.commit()
        logger.info(f"Token deleted: ID {id}")
        flash("Token deleted.")
    except Exception as e:
        logger.error(f"Error deleting token ID {id}: {e}")
        flash("Failed to delete token.")
    return redirect(url_for('index'))

@app.route('/get_prices')
def get_prices():
    prices = {}
    try:
        with get_db_connection() as conn:
            conn.row_factory = sqlite3.Row
            tokens = conn.execute('SELECT id, mint_address, output_mint FROM tokens').fetchall()

        for token in tokens:
            try:
                url = f"https://quote-api.jup.ag/v6/quote?inputMint={token['mint_address']}&outputMint={token['output_mint']}&amount=1000000"
                res = requests.get(url)
                data = res.json()
                price = float(data['data'][0]['outAmount']) / 1000000
                prices[str(token['id'])] = round(price, 6)
            except Exception as e:
                prices[str(token['id'])] = "N/A"
                logger.warning(f"Could not fetch price for {token['mint_address']}: {e}")
    except Exception as e:
        logger.error(f"Error retrieving prices: {e}")
    return jsonify(prices)

def check_token_prices():
    try:
        with get_db_connection() as conn:
            conn.row_factory = sqlite3.Row
            tokens = conn.execute('SELECT * FROM tokens').fetchall()

        for token in tokens:
            try:
                url = f"https://quote-api.jup.ag/v6/quote?inputMint={token['mint_address']}&outputMint={token['output_mint']}&amount=1000000"
                res = requests.get(url)
                data = res.json()
                price = float(data['data'][0]['outAmount']) / 1000000

                if price < token['alarm_lower']:
                    msg = f"🔻 Price Alert\nToken: {token['mint_address']}\nPrice: {price}\nBelow lower limit: {token['alarm_lower']}"
                    send_telegram_message(msg)
                    logger.info(f"Sent lower alert: {msg}")
                elif price > token['alarm_upper']:
                    msg = f"🔺 Price Alert\nToken: {token['mint_address']}\nPrice: {price}\nAbove upper limit: {token['alarm_upper']}"
                    send_telegram_message(msg)
                    logger.info(f"Sent upper alert: {msg}")
            except Exception as e:
                logger.warning(f"Price check error for {token['mint_address']}: {e}")
    except Exception as e:
        logger.error(f"Error in scheduled price check: {e}")

def send_telegram_message(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message}
        res = requests.post(url, data=payload)
        if res.status_code != 200:
            logger.warning(f"Telegram error: {res.text}")
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")

if __name__ == '__main__':
    init_db()

    scheduler = BackgroundScheduler()
    scheduler.add_job(check_token_prices, 'interval', minutes=1)
    scheduler.start()

    try:
        logger.info("Starting Flask app...")
        app.run(debug=True, use_reloader=False)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down scheduler...")
        scheduler.shutdown()
