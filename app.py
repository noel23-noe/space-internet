from flask import Flask, request, jsonify, render_template
import requests
import base64
from datetime import datetime
import sqlite3
import os

app = Flask(__name__)

# ====== SAFARICOM SANDBOX CREDENTIALS ======
CONSUMER_KEY = "d1bG9RteayS7h0cFBOdeArlJB5c7wAzaObWCMEG1zD07IkTP"
CONSUMER_SECRET = "J3vAkuTNzXScAO6xssBoFhZg6vLjVCzCSiVvo10JibvVauxYYQ3GIoGncUSe0vAF"
SHORTCODE = "174379"  # Sandbox shortcode
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"

TOKEN_URL = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
STK_PUSH_URL = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"

DB_FILE = "bundles.db"

# ====== DATABASE INIT ======
def init_db():
    if os.path.exists(DB_FILE):
        try:
            conn = sqlite3.connect(DB_FILE)
            conn.execute("SELECT name FROM sqlite_master;")
            conn.close()
        except sqlite3.DatabaseError:
            os.remove(DB_FILE)

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bundle_plan TEXT,
            amount INTEGER,
            bundle_phone TEXT,
            payment_method TEXT,
            payment_phone TEXT,
            status TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ====== GET ACCESS TOKEN ======
def get_access_token():
    r = requests.get(TOKEN_URL, auth=(CONSUMER_KEY, CONSUMER_SECRET))
    r.raise_for_status()
    return r.json().get("access_token")

# ====== HOME ======
@app.route("/")
def home():
    return render_template("index.html")

# ====== PAYMENT ROUTE ======
@app.route("/pay_bundle", methods=["POST"])
def pay_bundle():
    data = request.json
    bundle_plan = data.get("bundle_plan")
    amount = data.get("amount")
    bundle_phone = data.get("bundle_phone")
    payment_method = data.get("payment_method")
    payment_phone = data.get("payment_phone")

    if not all([bundle_plan, amount, bundle_phone, payment_method, payment_phone]):
        return jsonify({"status": "error", "message": "All fields required"}), 400

    # Save to DB as pending
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        INSERT INTO purchases (bundle_plan, amount, bundle_phone, payment_method, payment_phone, status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (bundle_plan, amount, bundle_phone, payment_method, payment_phone, "pending"))
    conn.commit()
    conn.close()

    # STK PUSH
    try:
        access_token = get_access_token()
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        password = base64.b64encode((SHORTCODE + PASSKEY + timestamp).encode()).decode()

        payload = {
            "BusinessShortCode": SHORTCODE,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": amount,
            "PartyA": payment_phone,
            "PartyB": SHORTCODE,
            "PhoneNumber": payment_phone,
            "CallBackURL": "https://yourdomain.com/callback",
            "AccountReference": "SpaceInternet",
            "TransactionDesc": f"{bundle_plan} purchase"
        }

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        response = requests.post(STK_PUSH_URL, json=payload, headers=headers)
        return jsonify({"status": "success", "response": response.json()})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ====== CALLBACK ======
@app.route("/callback", methods=["POST"])
def callback():
    data = request.json

    try:
        items = data["Body"]["stkCallback"]["CallbackMetadata"]["Item"]
        phone = next(i["Value"] for i in items if i["Name"] == "PhoneNumber")

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("""
            UPDATE purchases
            SET status = ?
            WHERE payment_phone = ? AND status = 'pending'
        """, ("completed", phone))
        conn.commit()
        conn.close()

        print(f"Bundle delivered to {phone}")

    except Exception as e:
        print("Callback error:", e)

    return jsonify({"ResultCode": 0, "ResultDesc": "Success"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)