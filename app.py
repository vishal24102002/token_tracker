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
import json 
from apscheduler.schedulers.background import BackgroundScheduler
import logging
import time


app = Flask(__name__)
app.secret_key = 'supersecretkey'
RAYDIUM_API = "https://api.raydium.io/v2/main/price"

# Telegram Bot Config
TELEGRAM_BOT_TOKEN = "8066450400:AAENAonrvuB7lNXnGqZbe5jdEXxF5zYiP5g"
TELEGRAM_CHAT_ID =  "884001334"
# TELEGRAM_CHAT_ID =  "5249408527"



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
                in_token_name TEXT,
                out_token_name TEXT,
                mint_address TEXT NOT NULL,
                output_mint TEXT,
                initial_price REAL,
                upper_bound_pct REAL NOT NULL,
                lower_bound_pct REAL NOT NULL,
                alarm_upper REAL NOT NULL,
                alarm_lower REAL NOT NULL
            );
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_name TEXT NOT NULL,
                mint_address TEXT NOT NULL,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS token_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                symbol TEXT,
                address TEXT UNIQUE,
                decimal INTEGER
            )
        ''')
    logger.info("Database initialized.")

# ------------------- Helper: Price Fetching -------------------

def fetch_price(mint_address, output_mint=None):
    try:
        if output_mint:
            try:
                url = f"https://quote-api.jup.ag/v6/quote?inputMint={mint_address}&outputMint={output_mint}&amount=1000000"
                res = requests.get(url)
                res.raise_for_status()
                data = res.json()
                return float(data['data'][0]['outAmount']) / 1000000
            except:
                i=float(upreq(mint_address))
                o=float(upreq(output_mint))
                return float(i/o)
                
        else:
            url = f"https://api.raydium.io/v2/main/price"
            res = requests.get(url)
            res=res.json()
            return res[mint_address]
    except Exception as e:
        logger.error(f"Price fetch error for {mint_address} (output: {output_mint}): {e}")
        return None

# ------------------- Helper: Telegram -------------------

def send_telegram_alert(message,delete_button):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message,
            "reply_markup": delete_button
        }
        res = requests.post(url, json=payload)
        res.raise_for_status()
        logger.info(f"Telegram alert sent: {message}")
        flash("Alert send to telegram sucessfully")
    except Exception as e:
        logger.error(f"Failed to send Telegram alert: {e}")

# ------------------- Scheduler -------------------

def check_token_prices():
    while True:
        conn = get_db_connection()
        tokens = conn.execute('SELECT * FROM tokens').fetchall()
        tokens_detail = conn.execute('SELECT * FROM history').fetchall()
        conn.close()

        for token in tokens:
            delete_button = {
                "inline_keyboard": [[
                    {"text": "🗑️ Delete Token", "callback_data": f"delete:{token['id']}"}
                ]]
            }
            conn = get_db_connection()
            tokens_detail_in = conn.execute(f"SELECT * FROM history where mint_address = ?",(token['mint_address'],)).fetchall()
            tokens_detail_out = conn.execute(f"SELECT * FROM history where mint_address = ?",(token['output_mint'],)).fetchall()
            conn.close()
            price = fetch_price(token['mint_address'], token['output_mint'])
            if price is None:
                continue
            # print(f"total price after bound {(token['alarm_upper']/100)*(token["upper_bound_pct"])}")
            # print(f"total price after bound {(token['alarm_lower']/100)*(token["lower_bound_pct"])}")
            
            if price >= (token['alarm_upper']):
                try:
                    msg = f"🚨 input token : {tokens_detail_in[0]['token_name']}\n output token : {tokens_detail_out[0]['token_name']}\n price limit : {token['lower_bound_pct']}-{token['upper_bound_pct']}\n price ABOVE upper alarm limit\n Current price : {price:.6f}"
                except:
                    msg = f"🚨 input token : {tokens_detail_in[0]['token_name']}\n price limit : {token['lower_bound_pct']}-{token['upper_bound_pct']}\n price ABOVE upper alarm limit\n Current price : {price:.6f}"
                
                send_telegram_alert(msg,delete_button)

            elif price <= (token['alarm_lower']):
                try:
                    msg = f"⚠️  input token : {tokens_detail_in[0]['token_name']}\n output token : {tokens_detail_out[0]['token_name']}\n price limit : {token['lower_bound_pct']}-{token['upper_bound_pct']}\n price BELOW lower alarm limit\n Current price : {price:.6f}"
                except:
                    msg = f"⚠️  input token : {tokens_detail_in[0]['token_name']}\n price limit : {token['lower_bound_pct']}-{token['upper_bound_pct']}\n price BELOW lower alarm limit\n Current price : {price:.6f}"                   
                send_telegram_alert(msg,delete_button)

        time.sleep(60)  # check every 60 seconds

def get_token_name_price(contractor: str):
    # If not in cache, fetch from API
    url = f"https://crimson-ancient-market.solana-mainnet.quiknode.pro/7b1dfa5a6af169b6c5b4146aa362be45238935b5/addon/912/networks/solana/tokens/{contractor}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        # summary = data.get('summary', {})
        name = data.get("symbol", "Unknown")
        return name
    except:
        pass

def save_token_history(token_name, mint_address):
    conn = get_db_connection()
    conn.execute('''
    INSERT INTO history (token_name, mint_address)
    VALUES (?, ?)
    ''', (token_name, mint_address))
    conn.commit()

def get_or_store_token_details(mint_address):
    conn = sqlite3.connect('tokens.db')
    cursor = conn.cursor()

    raydium_response = requests.get("https://api.raydium.io/v2/main/price").json()
    try:
        price=raydium_response[mint_address]
    except:
        url = "https://lite-api.jup.ag/price/v2?ids=KMNo3nJsBXfcpJTVhZcXLW7RmTwTt4GVFE7suUBo9sS"
        payload = {}
        headers = {
          'Accept': 'application/json'
        }
        
        response = requests.request("GET", url, headers=headers, data=payload).json()
        
        price=response.get("data",{}).get(mint_address,{}).get("price","N/A")
    
    # Check if token already exists
    cursor.execute("SELECT name, symbol, address, decimal FROM token_details WHERE address = ?", (mint_address,))
    row = cursor.fetchone()

    if row:
        # Token found in DB
        name, symbol, address, decimal = row
        result = {
            "name": name,
            "symbol": symbol,
            "id": address,
            "decimals": decimal,
            "price": price
        }
    else:
        # Token not found, fetch from API
        url = f"https://crimson-ancient-market.solana-mainnet.quiknode.pro/7b1dfa5a6af169b6c5b4146aa362be45238935b5/addon/912/networks/solana/tokens/{mint_address}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json() 

        save_token_history(data['name'], mint_address)

        result = {
            "name": data['name'],
            "symbol": data["symbol"],
            "id": data["id"],
            "decimals": data["decimals"],
            "price": data.get("summary",{}).get("price_usd","")
        }
        

        # Store in DB
        cursor.execute('''
            INSERT OR IGNORE INTO token_details (name, symbol, address, decimal)
            VALUES (?, ?, ?, ?)
        ''', (result["name"], result["symbol"], result["id"], result["decimals"]))
        conn.commit()

    conn.close()
    return result


# ------------------- Routes -------------------

# Step 4: Flask API endpoint
@app.route('/api/token', methods=['POST'])
def handle_token_request():
    data = request.get_json()
    mint = data.get("mint")

    if not mint:
        return jsonify({"error": "Mint address is required"}), 400

    token_info = get_or_store_token_details(mint)
    return jsonify(token_info)


@app.route('/')
def index():
    conn = get_db_connection()
    tokens = conn.execute('SELECT * FROM tokens').fetchall()
    data = conn.execute('SELECT token_name, mint_address FROM history').fetchall()
    conn.close()
    return render_template('index.html', tokens=tokens, edit_token=None, tokens_history=data)

@app.route('/add', methods=['POST'])
def add_token():
    mint_address = request.form['mint_address']
    output_mint = request.form.get('output_mint', '')
    auto_price = 'auto_price' in request.form
    alarm_u=float(request.form['alarm_upper'])
    alarm_l=float(request.form['alarm_lower'])
    u_bound=float(request.form.get("upper_bound_pct",""))
    l_bound=float(request.form.get("lower_bound_pct",""))

    if auto_price:
        initial_price = fetch_price(mint_address, output_mint)
        if initial_price is None:
            flash("Failed to fetch initial price.")
            return redirect(url_for('index'))
        logger.info(f"Fetched initial price for {mint_address}: {initial_price}")
    else:
        initial_price = float(request.form.get('initial_price', 0))

    token_names=get_token_name_price(mint_address)
    token_name_out=get_token_name_price(output_mint)

    conn = get_db_connection()
    if l_bound<=initial_price and u_bound>=initial_price:
        conn.execute('''
            INSERT INTO tokens (in_token_name, out_token_name, mint_address, output_mint, initial_price, upper_bound_pct, lower_bound_pct, alarm_upper, alarm_lower)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            token_names,
            token_name_out,
            mint_address,
            output_mint,
            initial_price,
            float(request.form['upper_bound_pct']),
            float(request.form['lower_bound_pct']),
            float(alarm_u),
            float(alarm_l)
        ))
        conn.commit()
        conn.close()
        flash("Token added successfully.")
    else:
        flash(f"{l_bound} limit should be in less then the {initial_price} & {u_bound} limit should be more than {initial_price}")
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


def delete_telegram_token(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM tokens WHERE id = ?', (id,))
    conn.commit()
    conn.close()

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
                try:
                    i=raydium_prices[mint_address]
                    o=raydium_prices[output_mint]
                    price = float(i/o)
                except:
                    i=float(upreq(mint_address))
                    o=float(upreq(output_mint))
                    price = float(i/o)
            else:
                # Use Raydium prices if output_mint is not provided
                if mint_address in raydium_prices:
                    price = float(raydium_prices[mint_address])
                else:
                    raise ValueError("Mint address not found in Raydium price list")
            prices[token_id] = round(price, 6)
        except Exception as e:
            prices[token_id] = "N/A"
            logger.error(f"Error fetching price for token {token_id}: {e}")

    return jsonify(prices)

def upreq(mint):
    url = f"https://lite-api.jup.ag/price/v2?ids={mint}"

    payload = {}
    headers = {
      'Accept': 'application/json'
    }

    response = requests.request("GET", url, headers=headers, data=payload)
    response=response.json()
    return response['data'][mint]['price']


#-------------------------weebhook for bot token data handling---------------------------
def send_message_with_delete_button(chat_id, token_id):
    button = {
        "inline_keyboard": [[
            {"text": "🗑️ Delete Token", "callback_data": f"delete:{token_id}"}
        ]]
    }

    requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={
        "chat_id": chat_id,
        "text": f"🚀 Sol Token Alert Bot is your real-time assistant for tracking and managing tokens on the Solana \n blockchain. Instantly get alerts for price changes, volume spikes, and suspicious activity — all directly\n in your Telegram."
    })


@app.route(f"/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    try:
        update = request.get_json()
        print("Update received:", update)

        # Handle message (simulate sending token)
        if "message" in update:
            chat_id = update["message"]["chat"]["id"]
            send_message_with_delete_button(chat_id, token_id=123)

        # Handle callback_query (button press)
        elif "callback_query" in update:
            query = update["callback_query"]
            callback_data = query.get("data", "")
            chat_id = query["message"]["chat"]["id"]
            message_id = query["message"]["message_id"]
            callback_id = query["id"]

            print("Callback data:", callback_data)

            if callback_data.startswith("delete:"):
                try:
                    token_id = int(callback_data.split(":")[1])
                    success = delete_telegram_token(token_id)
                    status = "✅ Deleted!" if success else "⚠️ Not found."
                except Exception as e:
                    status = f"⚠️ Error: {e}"

                # Edit original message
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText", json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": f"Token {token_id}: {status}"
                })

            # Always answer callback to prevent timeout spinner
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery", json={
                "callback_query_id": callback_id
            })

    except Exception as e:
        logging.error(f"Webhook Error: {e}", exc_info=True)

    return jsonify({"ok": True})

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
