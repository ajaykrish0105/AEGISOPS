"""Isolated demo backend for AegisOps crash/recovery testing."""
import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'runtime'
DATA.mkdir(exist_ok=True)
DB = DATA / 'orders.sqlite3'
LOG = DATA / 'backend.log'
PORT = 8200

logging.basicConfig(filename=LOG, level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
app = Flask(__name__)


def db():
    connection = sqlite3.connect(DB, timeout=5)
    connection.execute('CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, customer TEXT NOT NULL, amount REAL NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL)')
    connection.commit()
    return connection


@app.get('/health')
def health():
    with db() as connection:
        connection.execute('SELECT 1').fetchone()
    return jsonify(status='healthy', service='aegisops-demo-backend', database='connected'), 200


@app.get('/api/orders')
def orders():
    with db() as connection:
        rows = connection.execute('SELECT id, customer, amount, status, created_at FROM orders ORDER BY id DESC LIMIT 50').fetchall()
    return jsonify(orders=[dict(zip(('id','customer','amount','status','created_at'), row)) for row in rows])


@app.post('/api/orders')
def create_order():
    payload = request.get_json(silent=True) or {}
    customer = payload.get('customer')
    amount = payload.get('amount')
    if not isinstance(customer, str) or not customer.strip() or len(customer) > 100 or isinstance(amount, bool) or not isinstance(amount, (int, float)) or not 0 < amount <= 1000000:
        return jsonify(error='Provide customer (string) and amount (positive number <= 1000000)'), 400
    with db() as connection:
        cursor = connection.execute('INSERT INTO orders (customer, amount, status, created_at) VALUES (?, ?, ?, ?)', (customer.strip(), float(amount), 'accepted', datetime.now(timezone.utc).isoformat()))
        connection.commit()
        order_id = cursor.lastrowid
    logging.info('ORDER_CREATED id=%s', order_id)
    return jsonify(order_id=order_id, status='accepted'), 201


@app.post('/test/crash')
def crash():
    # Bound to loopback only. An explicit local test secret is required.
    supplied = request.headers.get('X-Demo-Crash-Token', '')
    expected = os.environ.get('AEGISOPS_DEMO_CRASH_TOKEN', '')
    import hmac
    if not expected or not hmac.compare_digest(supplied, expected):
        return jsonify(error='Not authorized'), 403
    logging.error('SIMULATED_PROCESS_CRASH: authorized test requested')
    logging.shutdown()
    threading.Timer(0.2, lambda: os._exit(42)).start()
    return jsonify(status='crashing', reason='SIMULATED_PROCESS_CRASH'), 202


if __name__ == '__main__':
    db().close()
    print('Demo backend: http://127.0.0.1:8200/health', flush=True)
    app.run(host='127.0.0.1', port=PORT, debug=False, use_reloader=False, threaded=True)
