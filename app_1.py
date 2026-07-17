
import os, sqlite3
from flask import Flask, request, jsonify, render_template, g

app = Flask(__name__)
TOKEN = "biolinh2hand_2026"
DB_FILE = "khachhang.db"

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

@app.route("/")
def index():
    if not os.path.exists(DB_FILE):
        return "<h3>Chưa có khachhang.db trên cloud. Hãy chạy auto_sync.py để đẩy lên.</h3>"
    conn = get_db()
    # Lấy tất cả đơn đang dồn
    rows = conn.execute("SELECT order_id, nickname, username FROM tonghopdon ORDER BY order_id DESC").fetchall()
    conn.close()
    data = [(r["order_id"], r["nickname"], r["username"]) for r in rows]
    return render_template("donhang.html", data=data)

@app.route("/order-details/<path:order_id>")
def order_details(order_id):
    conn = get_db()
    order = conn.execute("SELECT * FROM tonghopdon WHERE order_id = ?", (order_id,)).fetchone()
    if not order:
        conn.close()
        return jsonify({"error": "not found"}), 404

    details = conn.execute("SELECT price FROM chitietdon WHERE order_id = ? ORDER BY id", (order_id,)).fetchall()
    prices = [[str(d["price"])] for d in details]

    # Nếu không có chi tiết, lấy total_price làm 1 dòng
    if not prices:
        prices = [[str(order["total_price"] or 0)]]

    result = {
        "order_id": order["order_id"],
        "nickname": order["nickname"],
        "username": order["username"],
        "total_items": len(prices),
        "total_price": str(order["total_price"] or 0),
        "prices": prices,
        "phone": order["phone"],
        "address": order["address"]
    }
    conn.close()
    return jsonify(result)

@app.route("/sync/<ten_db>", methods=["POST"])
def sync(ten_db):
    if request.headers.get("X-TOKEN") != TOKEN:
        return "Sai token", 403
    if ten_db not in ["khachhang.db", "database.db"]:
        return "Ten file khong hop le", 400
    tmp = ten_db + ".tmp"
    request.files['file'].save(tmp)
    os.replace(tmp, ten_db)
    print(f"[SYNC] {ten_db} {os.path.getsize(ten_db)} bytes")
    return "OK"

@app.route("/health")
def health():
    return "OK"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
