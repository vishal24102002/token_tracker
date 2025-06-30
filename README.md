# 🪙 Token Tracker

Track Solana token prices and receive Telegram alerts when specific thresholds are met.

---

📌 <span style="color:goldenrod"><strong>Tech Stack:</strong></span>  
Python · Flask · MySQL · CoinGecko API · Telegram Bot API · Render Deployment

📈 <span style="color:lightseagreen"><strong>Key Features:</strong></span>
- Live Solana token price monitoring
- User-defined alert thresholds
- Telegram notification system
- Deployed on Render with MySQL integration

---

[![🚀 Open Project](https://img.shields.io/badge/🚀%20Open%20Project-blue?style=for-the-badge&logo=appveyor)](https://github.com/vishal24102002/token_tracker)

## Screenshot
<img src="/tracker.jpg" style="max-width: 100%; height: 300px; margin-bottom: 40px;">

<a href="https://token-tracker-lwpy.onrender.com/"><b> Token-tracker Live link </b></a> 

---

⚠️ <span style="color:orangered"><strong>Note:</strong></span>  
This project currently uses **SQLite** as the default database, which is suitable for testing or local use only. However:

- SQLite **resets on Render** every time the site restarts, which means your data will not persist.
- For production use, it is **highly recommended** to:
  - 🔧 Use your **own hosted database** (e.g., MySQL or PostgreSQL).
  - 🖥️ Run the project **locally** with a persistent database setup.

You can update the `SQLALCHEMY_DATABASE_URI` in `app.py` to connect to your own database.

Example:
```python
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://username:password@hostname/database'

