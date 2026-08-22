
import os
import json
import requests
import re
import sqlite3
import hashlib
from datetime import datetime, date
from datetime import datetime as dt
from zoneinfo import ZoneInfo
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from flask import send_file

app = Flask(__name__)
app.secret_key = 'super_secret_key_attendance_system'
TOKEN = "biolinh2hand_2026"
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
ENV = os.environ.get("ENV", "local")
print(f">>> Đang chạy ở chế độ: {ENV}")
DONHANG_DB = 'khachhang.db'
DATABASE = 'nv.db'



def get_donhang_db():
    conn = sqlite3.connect(DONHANG_DB)
    conn.row_factory = sqlite3.Row
    return conn

def get_donhang_db_safe():
    for p in [DONHANG_DB, DONHANG_DB + '.txt', 'khachhang.db', 'khachhang.db.txt', '/mnt/data/khachhang_real.db']:
        if os.path.exists(p):
            conn = sqlite3.connect(p)
            conn.row_factory = sqlite3.Row
            return conn
    conn = sqlite3.connect(DONHANG_DB)
    conn.row_factory = sqlite3.Row
    return conn

def get_db():
    conn = sqlite3.connect(DATABASE, timeout=30, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
    except:
        pass
    return conn

def db_execute_with_retry(cur, sql, params=(), retries=5):
    for i in range(retries):
        try:
            cur.execute(sql, params)
            return True
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and i < retries-1:
                time.sleep(0.2 * (i+1))
                continue
            raise

def ensure_khachhang_tables():
    try:
        conn = get_donhang_db_safe()
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS business_profile (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, tax_id TEXT, address TEXT, career TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS tax_settings (id INTEGER PRIMARY KEY AUTOINCREMENT, group_name TEXT, min_revenue REAL, max_revenue REAL, vat_rate REAL, pit_rate REAL, note TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS log_nop_thue (id INTEGER PRIMARY KEY AUTOINCREMENT, nam INTEGER, ky TEXT, ngay_nop TEXT, doanh_thu REAL, doanh_thu_luy_ke REAL, doanh_thu_mien_thue REAL, thue_gtgt REAL, thue_tncn REAL, ghi_chu TEXT)""")
        conn.commit()
        conn.close()
    except Exception as e:
        print("ensure_khachhang_tables error:", e)

ensure_khachhang_tables()





# ============================================================
# ===== BẮT ĐẦU PHẦN ORDERS - GIỮ NGUYÊN 100% LOGIC TỪ FILE RIÊNG =====
# ============================================================
# Constants riêng cho orders
VTP_API_URL = "https://partner.viettelpost.vn/v2/categories"

def get_orders_db():
    """Kết nối tới khachhang.db - GIỮ NGUYÊN LOGIC get_db() của file riêng, nhưng dùng safe path của app tổng"""
    # Logic gốc của file riêng là kết nối tới khachhang.db cùng thư mục
    # Ở đây dùng get_donhang_db_safe() của app tổng để tương thích Render/local
    conn = get_donhang_db_safe()
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def get_shipping_fee(db, weight):
    """Truy vấn phí ship từ bảng vtp_giavanchuyen trong DB. Nhận thêm tham số kết nối 'db' - GIỮ NGUYÊN"""
    try:
        w = int(float(weight or 0))
        # Tìm khoảng giá chứa cân nặng w
        row = db.execute(
            "SELECT price FROM vtp_giavanchuyen WHERE [from] <= ? AND [to] >= ? LIMIT 1", 
            (w, w)
        ).fetchone()
        if row:
            return int(row["price"])
    except Exception as e:
        print(f"Lỗi get_shipping_fee từ DB: {e}")
    return 0

def recalculate_order(db, order_id):
    """Tính lại tổng đơn, phí ship, tổng thanh toán - GIỮ NGUYÊN LOGIC GỐC"""
    try:
        res = db.execute("SELECT SUM(price) FROM chitietdon WHERE order_id=?", (order_id,)).fetchone()
        total_price = res[0] or 0

        order = db.execute("SELECT weight, deposit FROM tonghopdon WHERE order_id=?", (order_id,)).fetchone()
        if not order:
            return

        shipping_cost = get_shipping_fee(db, order["weight"] or 0)
        total_payment = total_price - (order["deposit"] or 0) + shipping_cost

        db.execute("""
            UPDATE tonghopdon SET total_price=?, shipping_cost=?, total_payment=? WHERE order_id=?
        """, (total_price, shipping_cost, total_payment, order_id))
        db.commit()
    except Exception as e:
        print(f"recalculate_order error: {e}")

# --- API QUẢN LÝ ĐƠN HÀNG (COPY Y NGUYÊN TỪ FILE RIÊNG, CHỈ ĐỔI get_db() -> get_orders_db() để tránh xung đột với nv.db) ---

@app.route("/api/orders", methods=["GET"])
def api_get_orders():
    search = request.args.get("search", "").strip()
    status = request.args.get("status", "").strip()

    db = get_orders_db()
    try:
        query = "SELECT * FROM tonghopdon WHERE 1=1"
        params = []

        if search:
            query += " AND (order_id LIKE ? OR nickname LIKE ? OR phone LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY tgtaodon DESC"

        rows = db.execute(query, params).fetchall()
        return jsonify({"data": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"error": str(e), "data": []}), 500
    finally:
        db.close()

@app.route("/api/order_details/<order_id>")
def api_order_details(order_id):
    db = get_orders_db()
    try:
        items = db.execute("SELECT * FROM chitietdon WHERE order_id = ?", (order_id,)).fetchall()
        return jsonify({"items": [dict(i) for i in items]})
    finally:
        db.close()

@app.route("/api/order/<order_id>")
def get_order_full(order_id):
    db = get_orders_db()
    try:
        order = db.execute("SELECT * FROM tonghopdon WHERE order_id=?", (order_id,)).fetchone()
        if not order:
            return jsonify({"error": "not found"}), 404
        order_data = dict(order)

        # Lấy thông tin khách hàng từ bảng khachhang
        user = db.execute("SELECT phone, address, note FROM khachhang WHERE uniqueid=?", (order_data["username"],)).fetchone()
        if user:
            order_data["cus_phone"] = user["phone"] or order_data["phone"]
            order_data["cus_address"] = user["address"] or order_data["address"]
            order_data["cus_note"] = user["note"]
        else:
            order_data["cus_phone"] = order_data["phone"]
            order_data["cus_address"] = order_data["address"]
            order_data["cus_note"] = ""

        # --- LOGIC ĐỊA CHỈ CHUẨN TỪ BẢNG vtp_diachicap3 ---
        order_data["standard_address"] = ""
        raw_phone = str(order_data.get("cus_phone", "")).strip()
        
        if raw_phone:
            geo_row = db.execute(
                "SELECT province, district, ward FROM vtp_diachicap3 WHERE phone = ? OR phone = ?",
                (raw_phone, "0" + raw_phone if not raw_phone.startswith("0") else raw_phone)
            ).fetchone()
            
            if geo_row:
                ward = str(geo_row["ward"] or "").strip()
                district = str(geo_row["district"] or "").strip()
                province = str(geo_row["province"] or "").strip()
                if ward or district or province:
                    order_data["standard_address"] = f"{ward}, {district}, {province}"

        items = db.execute("SELECT id, price, kygui FROM chitietdon WHERE order_id=?", (order_id,)).fetchall()

        return jsonify({
            "order": order_data,
            "items": [dict(i) for i in items]
        })
    finally:
        db.close()

@app.route("/api/order/update", methods=["POST"])
def update_order_field():
    data = request.json
    order_id = data.get("order_id")
    field = data.get("field")
    value = data.get("value")

    if not order_id or not field:
        return jsonify({"error": "Thiếu dữ liệu"}), 400

    allowed_fields = ["weight", "deposit", "phone", "address", "status", "tracking_number", "nickname"]
    if field not in allowed_fields:
        return jsonify({"error": f"Field không cho phép: {field}"}), 400

    db = get_orders_db()
    try:
        order_info = db.execute("SELECT username FROM tonghopdon WHERE order_id=?", (order_id,)).fetchone()
        if not order_info:
            return jsonify({"error": "Không tìm thấy đơn hàng"}), 404
        target_username = order_info["username"]

        if field in ["weight", "deposit"]:
            db.execute(f"UPDATE tonghopdon SET {field}=? WHERE order_id=?", (float(value or 0), order_id))
        else:
            db.execute(f"UPDATE tonghopdon SET {field}=? WHERE order_id=?", (value, order_id))

        if field in ["phone", "address"]:
            customer_exists = db.execute("SELECT uniqueid FROM khachhang WHERE uniqueid=?", (target_username,)).fetchone()
            if customer_exists:
                db.execute(f"UPDATE khachhang SET {field}=? WHERE uniqueid=?", (value, target_username))
            else:
                if field == "phone":
                    db.execute("INSERT INTO khachhang (uniqueid, nickname, phone) VALUES (?, ?, ?)",
                            (target_username, target_username, value))
                elif field == "address":
                    db.execute("INSERT INTO khachhang (uniqueid, nickname, address) VALUES (?, ?, ?)",
                               (target_username, target_username, value))

        db.commit()
        recalculate_order(db, order_id)
        return jsonify({"ok": True})
    except Exception as e:
        print(f"Lỗi cập nhật: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

@app.route("/api/order/sync_customer", methods=["POST"])
def sync_customer_info():
    data = request.json
    order_id = data.get("order_id")
    phone = data.get("phone", "")
    address = data.get("address", "")

    db = get_orders_db()
    try:
        order_info = db.execute("SELECT username FROM tonghopdon WHERE order_id=?", (order_id,)).fetchone()
        if not order_info:
            return jsonify({"error": "Không tìm thấy đơn hàng"}), 404
        target_username = order_info["username"]

        db.execute("UPDATE tonghopdon SET phone=?, address=? WHERE order_id=?", (phone, address, order_id))
        db.execute("UPDATE khachhang SET phone=?, address=? WHERE uniqueid=?", (phone, address, target_username))

        db.commit()
        return jsonify({"ok": True})
    except Exception as e:
        print(f"Lỗi đồng bộ khách hàng: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

@app.route("/api/item/action", methods=["POST"])
def item_action():
    data = request.json
    action = data.get("action")
    item_id = data.get("item_id")

    db = get_orders_db()
    try:
        target_order_id = None

        if action == "add":
            target_order_id = data.get("order_id")
            db.execute("INSERT INTO chitietdon (order_id, nickname, username, price) VALUES (?, ?, ?, ?)",
                       (target_order_id, data["nickname"], data["username"], data["price"]))

        elif action == "update":
            item = db.execute("SELECT order_id FROM chitietdon WHERE id=?", (item_id,)).fetchone()
            if item:
                target_order_id = item["order_id"]
                db.execute("UPDATE chitietdon SET price=? WHERE id=?", (data["price"], item_id))

        elif action == "delete":
            item = db.execute("SELECT order_id FROM chitietdon WHERE id=?", (item_id,)).fetchone()
            if item:
                target_order_id = item["order_id"]
                db.execute("DELETE FROM chitietdon WHERE id=?", (item_id,))

        db.commit()

        if target_order_id:
            recalculate_order(db, target_order_id)

        return jsonify({"ok": True})
    except Exception as e:
        print(f"Lỗi khi thực hiện {action}: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

@app.route("/api/address/provinces")
def get_provinces():
    try:
        res = requests.get(f"{VTP_API_URL}/listProvince", timeout=10)
        return jsonify(res.json().get("data", []))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/address/districts/<int:province_id>")
def get_districts(province_id):
    try:
        res = requests.get(f"{VTP_API_URL}/listDistrict?provinceId={province_id}", timeout=10)
        return jsonify(res.json().get("data", []))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/address/wards/<int:district_id>")
def get_wards(district_id):
    try:
        res = requests.get(f"{VTP_API_URL}/listWards?districtId={district_id}", timeout=10)
        return jsonify(res.json().get("data", []))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/address/save", methods=["POST"])
def save_standard_address():
    data = request.json
    phone = str(data.get("phone", "")).strip()
    if not phone:
        return jsonify({"error": "Missing phone"}), 400

    db = get_orders_db()
    try:
        exist = db.execute("SELECT id FROM vtp_diachicap3 WHERE phone = ?", (phone,)).fetchone()
        
        if exist:
            db.execute("""
                UPDATE vtp_diachicap3 
                SET province=?, province_id=?, district=?, district_id=?, ward=?, ward_id=?
                WHERE phone=?
            """, (data["province_name"], data["province_id"], data["district_name"], 
                  data["district_id"], data["ward_name"], data["ward_id"], phone))
        else:
            db.execute("""
                INSERT INTO vtp_diachicap3 (phone, province, province_id, district, district_id, ward, ward_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (phone, data["province_name"], data["province_id"], data["district_name"], 
                  data["district_id"], data["ward_name"], data["ward_id"]))
        db.commit()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

@app.route("/api/orders/preview_merge", methods=["POST"])
def preview_merge():
    data = request.json
    order_ids = data.get("order_ids", [])

    if len(order_ids) < 2:
        return jsonify({"error": "Cần ít nhất 2 đơn để gộp"}), 400

    db = get_orders_db()
    try:
        placeholders = ','.join(['?'] * len(order_ids))
        orders = db.execute(f"SELECT * FROM tonghopdon WHERE order_id IN ({placeholders}) ORDER BY tgtaodon DESC", order_ids).fetchall()
        items = db.execute(f"SELECT price, kygui, order_id FROM chitietdon WHERE order_id IN ({placeholders})", order_ids).fetchall()

        new_weight = sum(float(o["weight"] or 0) for o in orders)
        new_total_price = sum(float(o["total_price"] or 0) for o in orders)
        new_deposit = sum(float(o["deposit"] or 0) for o in orders)

        new_shipping_cost = get_shipping_fee(db, new_weight)
        new_total_payment = new_total_price - new_deposit + new_shipping_cost

        return jsonify({
            "ok": True,
            "summary": {
                "new_weight": new_weight,
                "new_total_price": new_total_price,
                "new_deposit": new_deposit,
                "new_shipping_cost": new_shipping_cost,
                "new_total_payment": new_total_payment,
                "order_count": len(orders)
            },
            "items": [dict(i) for i in items]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

@app.route("/api/orders/execute_merge", methods=["POST"])
def execute_merge():
    data = request.json
    primary_id = str(data.get("primary_id"))
    all_ids = [str(i) for i in data.get("all_ids", [])]

    db = get_orders_db()
    try:
        db.row_factory = sqlite3.Row
        with db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS merge_logs (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    merge_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    old_order_id TEXT,
                    new_order_id TEXT,
                    original_data_json TEXT,
                    note TEXT
                );
            """)

            placeholders = ','.join(['?'] * len(all_ids))
            old_orders = [dict(r) for r in db.execute(f"SELECT * FROM tonghopdon WHERE order_id IN ({placeholders})", all_ids).fetchall()]
            old_items = [dict(r) for r in db.execute(f"SELECT * FROM chitietdon WHERE order_id IN ({placeholders})", all_ids).fetchall()]

            if not old_orders:
                raise Exception("Không tìm thấy dữ liệu các đơn cần gộp")

            log_json = json.dumps({"orders": old_orders, "items": old_items}, ensure_ascii=False)
            db.execute("INSERT INTO merge_logs (old_order_id, new_order_id, original_data_json, note) VALUES (?, ?, ?, ?)",
                       (", ".join(all_ids), primary_id, log_json, "Gộp đơn Web Standalone"))

            new_weight = sum(float(o["weight"] or 0) for o in old_orders)
            new_total_price = sum(float(o["total_price"] or 0) for o in old_orders)
            new_deposit = sum(float(o["deposit"] or 0) for o in old_orders)
            new_shipping = get_shipping_fee(db, new_weight)
            new_payment = new_total_price - new_deposit + new_shipping

            primary_info = next((o for o in old_orders if str(o["order_id"]) == primary_id), old_orders[0])

            db.execute(f"DELETE FROM chitietdon WHERE order_id IN ({placeholders})", all_ids)
            db.execute(f"DELETE FROM tonghopdon WHERE order_id IN ({placeholders})", all_ids)

            db.execute("""INSERT INTO tonghopdon (order_id, nickname, username, phone, address, weight, total_price, 
                          deposit, shipping_cost, total_payment, tracking_number, status, success) 
                          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (primary_id, primary_info["nickname"], primary_info["username"], primary_info["phone"],
                        primary_info["address"], new_weight, new_total_price, new_deposit, new_shipping,
                        new_payment, primary_info["tracking_number"], "Đang Dồn", primary_info["success"]))

            for item in old_items:
                db.execute("INSERT INTO chitietdon (order_id, nickname, username, price, kygui) VALUES (?,?,?,?,?)",
                           (primary_id, primary_info["nickname"], primary_info["username"], item["price"], item["kygui"]))

        return jsonify({"ok": True})
    except Exception as e:
        print(f"Lỗi gộp đơn: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

@app.route("/api/order/create_vtp", methods=["POST"])
def create_vtp_order():
    data = request.json
    order_id = data.get("order_id")

    db = get_orders_db()
    try:
        order = db.execute("SELECT * FROM tonghopdon WHERE order_id=?", (order_id,)).fetchone()
        if not order:
            raise Exception("Không tìm thấy đơn hàng")

        user_info = db.execute("SELECT phone, address FROM khachhang WHERE uniqueid=?", (order["username"],)).fetchone()
        receiver_phone = user_info["phone"] if (user_info and user_info["phone"]) else order["phone"]
        receiver_address = user_info["address"] if (user_info and user_info["address"]) else order["address"]
        receiver_phone = str(receiver_phone or "").strip()

        geo = db.execute(
            "SELECT * FROM vtp_diachicap3 WHERE phone = ? OR phone = ?",
            (receiver_phone, "0" + receiver_phone if not receiver_phone.startswith("0") else receiver_phone)
        ).fetchone()

        if not geo:
            raise Exception(f"SĐT {receiver_phone} chưa có địa chỉ chuẩn. Vui lòng cập nhật trên giao diện!")

        def login_vtp_to_db():
            acc_row = db.execute("SELECT username, password FROM vtp_account_token LIMIT 1").fetchone()
            if not acc_row or not acc_row["username"]:
                raise Exception("Chưa cấu hình tài khoản ViettelPost trong bảng vtp_account_token!")
                
            resp = requests.post("https://partner.viettelpost.vn/v2/user/Login", json={
                "USERNAME": acc_row["username"], "PASSWORD": acc_row["password"]
            }, timeout=10)
            
            if resp.status_code == 200 and resp.json().get("data"):
                new_token = resp.json()["data"]["token"]
                db.execute("UPDATE vtp_account_token SET token = ? WHERE username = ?", (new_token, acc_row["username"]))
                db.commit()
                return new_token
            raise Exception("Đăng nhập ViettelPost thất bại. Vui lòng kiểm tra tài khoản cấu hình.")

        token_row = db.execute("SELECT token FROM vtp_account_token LIMIT 1").fetchone()
        token = token_row["token"] if token_row else None
        
        if not token:
            token = login_vtp_to_db()

        def send_order(auth_token):
            inv_url = "https://partner.viettelpost.vn/v2/user/listInventory"
            groupaddress_id = 0
            cus_id = 0
            
            try:
                inv_res = requests.get(inv_url, headers={"Token": auth_token}, timeout=10)
                if inv_res.status_code == 200:
                    inv_json = inv_res.json()
                    inventories = inv_json.get("data")
                    if inventories and len(inventories) > 0:
                        kho_data = inventories[0]
                        groupaddress_id = kho_data.get("groupaddressId", 0)
                        cus_id = kho_data.get("cusId", 0)
            except Exception as inv_err:
                print(f"Cảnh báo lỗi khi lấy danh sách kho: {inv_err}. Sẽ thử dùng kho mặc định.")

            if groupaddress_id == 0:
                print("Không quét được kho cụ thể, hệ thống tự động gửi với ID mặc định (0) để VTP tự bốc kho chính.")

            url = "https://partner.viettelpost.vn/v2/order/createOrder"
            headers = {"Content-Type": "application/json", "Token": auth_token}

            list_item = [{
                "PRODUCT_NAME": "Quần áo",
                "PRODUCT_PRICE": int(order["total_price"] or 0),
                "PRODUCT_WEIGHT": int(order["weight"] or 0),
                "PRODUCT_QUANTITY": 1
            }]

            payload = {
                "ORDER_NUMBER": str(order["order_id"]),
                "GROUPADDRESS_ID": int(groupaddress_id),
                "CUS_ID": int(cus_id),
                "DELIVERY_DATE": dt.now().strftime("%d/%m/%Y %H:%M:%S"),
                "RECEIVER_FULLNAME": order["nickname"] or order["username"] or "Khách hàng",
                "RECEIVER_ADDRESS": receiver_address,
                "RECEIVER_PHONE": receiver_phone,
                "RECEIVER_PROVINCE": int(geo["province_id"]),
                "RECEIVER_DISTRICT": int(geo["district_id"]),
                "RECEIVER_WARDS": int(geo["ward_id"]),
                "PRODUCT_NAME": "Quần áo",
                "PRODUCT_WEIGHT": int(order["weight"] or 0),
                "PRODUCT_PRICE": int(order["total_price"] or 0),
                "MONEY_COLLECTION": int(order["total_payment"] or 0),
                "ORDER_PAYMENT": 3,  # 3 = thu hộ tiền hàng (khách thanh toán cả COD và phí ship)
                "ORDER_SERVICE": "VSL7",
                "PRODUCT_TYPE": "HH",
                "NATIONAL_TYPE": 1,
                "LIST_ITEM": list_item
            }
            return requests.post(url, headers=headers, json=payload, timeout=15)

        res = send_order(token)
        if res.status_code == 401 or (res.status_code == 200 and res.json().get("status") in [201, 208, 401]):
            print("Token trong DB hết hạn. Đang lấy token mới...")
            token = login_vtp_to_db()
            res = send_order(token)

        res_data = res.json()

        if res.status_code == 200 and res_data.get("status") == 200:
            tracking_code = res_data["data"]["ORDER_NUMBER"]
            db.execute("UPDATE tonghopdon SET tracking_number=?, status='Đã Đi Đơn' WHERE order_id=?",
                       (tracking_code, order_id))
            db.commit()
            return jsonify({"ok": True, "tracking_number": tracking_code})
        else:
            error_msg = res_data.get("message", "Lỗi không xác định từ VTP")
            return jsonify({"error": error_msg}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

@app.route("/api/customers")
def get_customers_api():
    search_query = request.args.get('q', '').strip()
    db = get_orders_db()
    try:
        if search_query:
            sql = """SELECT * FROM khachhang 
                     WHERE nickname LIKE ? OR uniqueid LIKE ? OR phone LIKE ? OR note LIKE ? 
                     ORDER BY STT DESC"""
            params = [f"%{search_query}%"] * 4
            rows = db.execute(sql, params).fetchall()
        else:
            rows = db.execute("SELECT * FROM khachhang ORDER BY STT DESC").fetchall()

        customers = [dict(row) for row in rows]

        for c in customers:
            c["standard_address"] = ""
            raw_phone = str(c.get("phone") or "").strip()
            if raw_phone:
                geo_row = db.execute(
                    "SELECT province, district, ward FROM vtp_diachicap3 WHERE phone = ? OR phone = ?",
                    (raw_phone, "0" + raw_phone if not raw_phone.startswith("0") else raw_phone)
                ).fetchone()
                if geo_row:
                    ward = str(geo_row["ward"] or "").strip()
                    district = str(geo_row["district"] or "").strip()
                    province = str(geo_row["province"] or "").strip()
                    if ward or district or province:
                        c["standard_address"] = f"{ward}, {district}, {province}"

        return jsonify(customers)
    finally:
        db.close()

@app.route("/api/customers/update", methods=["POST"])
def update_customer_api():
    data = request.json
    uniqueid = data.get("uniqueid")
    if not uniqueid:
        return jsonify({"error": "Thiếu UniqueID"}), 400

    db = get_orders_db()
    try:
        db.execute("""
            UPDATE khachhang 
            SET note = ?, phone = ?, address = ? 
            WHERE uniqueid = ?
        """, (data.get("note"), data.get("phone"), data.get("address"), uniqueid))
        db.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

# ===== KẾT THÚC PHẦN ORDERS =====
# ============================================================


def ensure_bangke_table():
    try:
        conn = get_donhang_db_safe()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bangke_muahang (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ngay_mua TEXT,
                ten_nguoi_ban TEXT,
                dia_chi TEXT,
                cccd TEXT,
                dien_thoai TEXT,
                ten_hang_hoa TEXT,
                so_luong REAL,
                don_gia REAL,
                thanh_toan REAL,
                ghi_chu TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print("ensure_bangke_table error", e)

ensure_bangke_table()



def clean_float(v):
    if v is None: return 0.0
    try:
        if isinstance(v, (int,float)): return float(v)
        s=str(v).strip()
        if not s: return 0.0
        s=s.replace(' ','').replace(',','').replace('\u00a0','')
        return float(s)
    except:
        m=re.search(r'[\d.]+', str(v).replace(' ',''))
        if m:
            try: return float(m.group().replace(' ',''))
            except: return 0.0
        return 0.0

def parse_doisoat_date(s):
    if not s: return None
    s=str(s).strip().replace('/','-').replace('.','-')
    for fmt in ('%d-%m-%Y','%Y-%m-%d','%d-%m-%y'):
        try: return datetime.strptime(s, fmt).date()
        except: continue
    return None

def get_available_years():
    years=set()
    try:
        conn=get_donhang_db_safe(); cur=conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='doisoat'")
        if cur.fetchone():
            for r in cur.execute("SELECT date FROM doisoat").fetchall():
                d=parse_doisoat_date(r['date'])
                if d: years.add(d.year)
        conn.close()
    except: pass
    return sorted(list(years)) if years else [2024,2025,2026]

def filter_doisoat_by_range(from_iso, to_iso):
    from_date=None; to_date=None
    try:
        if from_iso: from_date=datetime.strptime(from_iso, '%Y-%m-%d').date()
    except: pass
    try:
        if to_iso: to_date=datetime.strptime(to_iso, '%Y-%m-%d').date()
    except: pass
    res=[]
    try:
        conn=get_donhang_db_safe(); cur=conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='doisoat'")
        if not cur.fetchone():
            conn.close(); return []
        for r in cur.execute("SELECT * FROM doisoat").fetchall():
            rd=parse_doisoat_date(r['date'])
            if not rd: continue
            if from_date and rd<from_date: continue
            if to_date and rd>to_date: continue
            res.append(dict(r))
        conn.close()
    except Exception as e:
        print("filter error", e)
    return res

def get_all_doisoat_customers():
    customers_map = {}
    try:
        conn=get_donhang_db_safe(); cur=conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='doisoat'")
        if not cur.fetchone():
            conn.close()
            return []
        cols = [row[1] for row in cur.execute("PRAGMA table_info(doisoat)").fetchall()]

        # FIX: ép lấy revenue = tổng tiền hàng
        rev_col = 'revenue'

        for r in cur.execute("SELECT * FROM doisoat").fetchall():
            d = dict(r)
            nick = (d.get('nickname') or d.get('nick') or 'Ẩn danh')
            if not nick:
                nick = 'Ẩn danh'
            nick = str(nick).strip()
            username = str(d.get('username') or d.get('user') or '').strip()

            # FIX: chỉ lấy revenue
            rev = clean_float(d.get(rev_col) or 0)

            rd = parse_doisoat_date(d.get('date'))
            if nick not in customers_map:
                customers_map[nick] = {'nickname': nick, 'username': username, 'total_payment': 0.0, 'order_count': 0, 'last_date_str': '', 'last_date_obj': None}
            customers_map[nick]['total_payment'] += rev
            customers_map[nick]['order_count'] += 1
            if username:
                customers_map[nick]['username'] = username
            if rd:
                if customers_map[nick]['last_date_obj'] is None or rd > customers_map[nick]['last_date_obj']:
                    customers_map[nick]['last_date_obj'] = rd
                    customers_map[nick]['last_date_str'] = rd.strftime('%d-%m-%Y')
    except Exception as e:
        print("get_all_doisoat_customers error", e)
    result = []
    from datetime import date as date_cls
    for v in customers_map.values():
        days_inactive = None
        if v['last_date_obj']:
            days_inactive = (date_cls.today() - v['last_date_obj']).days
        result.append({'nickname': v['nickname'], 'username': v['username'] or v['nickname'], 'total_payment': v['total_payment'], 'order_count': v['order_count'], 'last_date': v['last_date_str'], 'days_inactive': days_inactive, 'last_date_obj': v['last_date_obj'].isoformat() if v['last_date_obj'] else ''})
    return sorted(result, key=lambda x: x['total_payment'], reverse=True)


def format_date_vn(date_str):
    """Chuyển đổi chuỗi ngày sang định dạng dd/mm/yyyy."""
    if not date_str:
        return ""
    date_str = str(date_str).strip()
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%d/%m/%Y")
        except ValueError:
            pass
    return date_str.replace("-", "/")

def clean_number(val):
    if val is None:
        return 0.0
    if isinstance(val, (int,float)):
        return float(val)
    cleaned = re.sub(r"[^\d.]", "", str(val))
    try:
        return float(cleaned) if cleaned else 0.0
    except:
        return 0.0

def sanitize_text_for_pdf(text):
    if not text:
        return ""
    return "".join(c for c in str(text) if ord(c) <= 0xFFFF)

def register_vietnamese_font():
    font_paths = [
        ("C:\\Windows\\Fonts\\arial.ttf", "C:\\Windows\\Fonts\\arialbd.ttf"),
        ("C:\\Windows\\Fonts\\segoeui.ttf", "C:\\Windows\\Fonts\\segoeuiB.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
    ]
    for regular, bold in font_paths:
        if os.path.exists(regular):
            try:
                pdfmetrics.registerFont(TTFont("VNFont", regular))
                pdfmetrics.registerFont(TTFont("VNFont-Bold", bold if os.path.exists(bold) else regular))
                return "VNFont", "VNFont-Bold"
            except:
                continue
    return "Helvetica", "Helvetica-Bold"

def load_s2a_data_new(from_iso=None, to_iso=None):
    """Load S2a ĐỒNG BỘ với báo cáo tổng kết - tính lũy kế để xác định nhóm thuế"""
    from datetime import date as date_type
    business = get_business_profile()
    if from_iso and to_iso:
        filtered = filter_doisoat_by_range(from_iso, to_iso)
    else:
        filtered = filter_doisoat_by_range(None, None)
    
    # 1. Tính lũy kế cả năm giống hệt api_reports_summary để biết đang ở nhóm nào
    today = datetime.now(VN_TZ).date()
    try:
        year_to_calc = today.year
        if from_iso:
            try: year_to_calc = datetime.strptime(from_iso, "%Y-%m-%d").date().year
            except: pass
        year_start = date_type(year_to_calc, 1, 1)
        year_end = today if year_to_calc==today.year else date_type(year_to_calc, 12, 31)
        year_filtered = filter_doisoat_by_range(year_start.isoformat(), year_end.isoformat())
        luy_ke = sum(clean_float(r.get('revenue')) for r in year_filtered)
    except:
        luy_ke = sum(clean_float(r.get('revenue')) for r in filtered)

    # 2. Xác định nhóm thuế từ bảng tax_settings theo lũy kế
    current_group = {"group_name":"Nhóm 1 - doanh thu dưới 1 tỷ - Miễn thuế","vat_rate":0.0,"pit_rate":0.0,"note":"Miễn thuế"}
    try:
        conn = get_donhang_db_safe()
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tax_settings'")
        if cur.fetchone():
            rows = cur.execute("SELECT * FROM tax_settings ORDER BY min_revenue ASC").fetchall()
            for g in rows:
                min_rev = clean_float(g['min_revenue'])
                max_rev = clean_float(g['max_revenue']) if g['max_revenue'] else float('inf')
                if luy_ke >= min_rev and luy_ke < max_rev:
                    current_group = {"group_name": g['group_name'], "vat_rate": clean_float(g['vat_rate'])/100.0, "pit_rate": clean_float(g['pit_rate'])/100.0, "note": g['note']}
                    break
            # Nếu vượt ngưỡng cuối thì lấy nhóm cuối
            if current_group['group_name'].startswith("Nhóm 1") and rows:
                last = rows[-1]
                if luy_ke >= clean_float(last['min_revenue']):
                    # kiểm tra lại, nếu luy_ke lớn hơn ngưỡng cuối thì vẫn ở nhóm cuối, nhưng nếu nhỏ hơn ngưỡng đầu thì vẫn là nhóm 1
                    pass
        conn.close()
    except Exception as e:
        print("load_s2a_data_new tax group error", e)

    orders = []
    tong = 0.0
    for r in filtered:
        amount = clean_float(r.get('revenue') or 0)
        tong += amount
        tracking = r.get('tracking_number') or r.get('order_id') or ""
        date_vn = format_date_vn(r.get('date') or "")
        nickname = (r.get('nickname') or "").strip()
        dien_giai = f"Bán hàng cho {nickname}".strip() if nickname else "Bán hàng"
        orders.append({"tracking_number": tracking, "date": date_vn, "nickname": nickname, "dien_giai": dien_giai, "total_payment": amount})

    vat_rate_pct = current_group['vat_rate']*100
    pit_rate_pct = current_group['pit_rate']*100
    thue_gtgt = tong * current_group['vat_rate']
    thue_tncn = tong * current_group['pit_rate']

    now = datetime.now(VN_TZ)
    return {
        "profile": business,
        "orders": orders,
        "tong_doanh_thu": tong,
        "pct_gtgt": vat_rate_pct,
        "pct_tncn": pit_rate_pct,
        "vat_rate": current_group['vat_rate'],
        "pit_rate": current_group['pit_rate'],
        "thue_gtgt": thue_gtgt,
        "thue_tncn": thue_tncn,
        "group_name": current_group['group_name'],
        "note": current_group['note'],
        "luy_ke": luy_ke,
        "ky_ke_khai": f"{format_date_vn(from_iso)} - {format_date_vn(to_iso)}" if from_iso else f"Tháng {now.month:02d}/{now.year}",
        "ngay_lap": f"{now.day:02d}",
        "thang_lap": f"{now.month:02d}",
        "nam_lap": f"{now.year}",
    }


def get_business_profile():
    default={"name":"Biolinh 2Hand - Cửa hàng thời trang secondhand","tax_id":"","address":"Thái Nguyên","career":"Bán lẻ quần áo cũ"}
    try:
        conn=get_donhang_db_safe(); cur=conn.cursor()
        row=cur.execute("SELECT name, tax_id, address, career FROM business_profile ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        if row:
            return {"name":row["name"] or default["name"],"tax_id":row["tax_id"] or default["tax_id"],"address":row["address"] or default["address"],"career":row["career"] or default["career"]}
    except Exception as e:
        print("get_business_profile error:", e)
    return default

def calculate_salary_details(emp, conn):
    emp_id = emp['id']
    cur = conn.cursor()
    
    # 1. Tính tổng khoản phát sinh (Thưởng/Phạt - Dùng chung)
    cur.execute("SELECT sotien, loai FROM chi_tiet_phat_sinh WHERE employee_id = ?", (emp_id,))
    phat_sinh_list = cur.fetchall()
    tong_phat_sinh = 0.0
    for ps in phat_sinh_list:
        if ps['loai'] == 'tang':
            tong_phat_sinh += ps['sotien']
        elif ps['loai'] == 'giam':
            tong_phat_sinh -= ps['sotien']

    # 2. Phân nhánh logic tính toán theo Chức danh
    if emp['chucdanh'] == 'parttime':
        # --- LOGIC PART-TIME ---
        luong_theo_gio = emp['luong_theo_gio'] or 0.0
        
        # Lấy tổng số phút từ bảng cham_cong_part_time (chỉ tính những lượt đã được duyệt hoặc tất cả tùy logic của bạn)
        cur.execute("""
            SELECT SUM(so_phut) 
            FROM cham_cong_part_time 
            WHERE employee_id = ?
        """, (emp_id,))
        row = cur.fetchone()
        tong_phut = row[0] if row and row[0] is not None else 0
        
        tong_gio = tong_phut / 60.0
        thu_nhap_uoc_tinh = tong_gio * luong_theo_gio
        thuc_nhan = thu_nhap_uoc_tinh + tong_phat_sinh

        return {
            'id': emp['id'],
            'username': emp['username'],
            'hovaten': emp['hovaten'],
            'chucdanh': emp['chucdanh'],
            'luong_theo_gio': luong_theo_gio,
            'tong_gio': tong_gio,
            'thu_nhap_uoc_tinh': thu_nhap_uoc_tinh,
            'tong_phat_sinh': tong_phat_sinh,
            'thuc_nhan': thuc_nhan
        }
        
    else:
        # --- LOGIC NHÂN VIÊN CHÍNH THỨC ---
        luong_thang = emp['luong'] or 0.0
        luong_ngay = luong_thang / 26.0 if luong_thang else 0.0
        
        # Đếm tổng buổi chấm công trong bảng attendance
        cur.execute("SELECT COUNT(*) FROM attendance WHERE employee_id = ?", (emp_id,))
        total_sessions = cur.fetchone()[0]
        tong_cong = total_sessions / 2.0
        
        thu_nhap_uoc_tinh = tong_cong * luong_ngay
        thuc_nhan = thu_nhap_uoc_tinh + tong_phat_sinh

        return {
            'id': emp['id'],
            'username': emp['username'],
            'hovaten': emp['hovaten'],
            'chucdanh': emp['chucdanh'],
            'luong': luong_thang,
            'luong_ngay': luong_ngay,
            'tong_cong': tong_cong,
            'thu_nhap_uoc_tinh': thu_nhap_uoc_tinh,
            'tong_phat_sinh': tong_phat_sinh,
            'thuc_nhan': thuc_nhan
        }

#----- truy vấn lịch sử thanh toán từ bảng payment_history-------------
@app.route('/admin/salary-management')
def salary_management():
    if session.get('role') != 'QTV': 
        return "Từ chối truy cập!", 403

    selected_month = request.args.get('month', datetime.now().strftime('%Y-%m')) # Format YYYY-MM
    
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Truy vấn danh sách lịch sử thanh toán kết hợp thông tin nhân viên
    cur.execute("""
        SELECT p.*, n.hovaten, n.username, n.chucdanh
        FROM payment_history p
        JOIN nv n ON p.employee_id = n.id
        WHERE strftime('%Y-%m', p.payment_date) = ?
        ORDER BY p.payment_date DESC, p.id DESC
    """, (selected_month,))
    payments = cur.fetchall()

    # Tính toán thống kê theo chuẩn bản chất quỹ lương chi trả
    total_paid = 0
    official_paid = 0
    parttime_paid = 0

    for p in payments:
        thu_nhap = float(p['thu_nhap_tinh'] or 0)
        phat_sinh = float(p['tong_phat_sinh'] or 0)
        
        # Nếu phát sinh > 0 (thưởng/phụ cấp): Doanh nghiệp chi trả = Thu nhập + Phát sinh
        # Nếu phát sinh <= 0 (phạt/tạm ứng): Doanh nghiệp đã ghi nhận chi trả đủ mức Thu nhập
        chi_tra_ban_ghi = thu_nhap + (phat_sinh if phat_sinh > 0 else 0)
        
        total_paid += chi_tra_ban_ghi
        
        if p['chucdanh'] == 'parttime':
            parttime_paid += chi_tra_ban_ghi
        else:
            official_paid += chi_tra_ban_ghi

    total_transactions = len(payments)

    conn.close()

    return render_template(
        'salary_management.html',
        payments=payments,
        selected_month=selected_month,
        total_paid=total_paid,
        official_paid=official_paid,
        parttime_paid=parttime_paid,
        total_transactions=total_transactions
    )

@app.route("/")
def home():
    tong=0
    if os.path.exists(DONHANG_DB):
        try:
            conn=get_donhang_db(); tong=conn.execute("SELECT COUNT(*) FROM tonghopdon").fetchone()[0]; conn.close()
        except: pass
    return render_template("home.html", tong_don=tong)

@app.route('/ql-donhang')
def ql_donhang():
    # Route mới dùng template đã ghép với admin_base
    tong=0
    try:
        conn=get_donhang_db_safe()
        tong=conn.execute("SELECT COUNT(*) FROM tonghopdon WHERE status='Đang Dồn'").fetchone()[0]
        conn.close()
    except:
        pass
    return render_template('orders.html', tong_don=tong)

@app.route('/admin/orders')
def admin_orders():
    # Alias cho sidebar admin_base
    return redirect(url_for('ql_donhang'))

@app.route("/donhang")
def donhang():
    # Chỉ hiển thị đơn Đang Dồn + tính balance để cảnh báo viền đỏ
    try:
        conn = get_donhang_db_safe()
    except Exception:
        return "<h3>Chua co khachhang.db</h3><a href='/'>Ve trang chu</a>"

    try:
        rows = conn.execute("""
            SELECT order_id, nickname, username, total_price, deposit
            FROM tonghopdon
            WHERE TRIM(status) = 'Đang Dồn'
            ORDER BY order_id DESC
            LIMIT 1000
        """).fetchall()

        bal_rows = conn.execute("""
            SELECT username,
                   SUM(COALESCE(total_price,0)) as sum_price,
                   SUM(COALESCE(deposit,0)) as sum_dep
            FROM tonghopdon
            WHERE TRIM(status) = 'Đang Dồn'
            GROUP BY username
        """).fetchall()

        balances = {}
        for r in bal_rows:
            if r["username"] is None: continue
            balances[r["username"]] = float(r["sum_price"] or 0) - float(r["sum_dep"] or 0)

    except Exception as e:
        print(f"donhang error: {e}")
        rows = []
        balances = {}
    finally:
        try: conn.close()
        except: pass

    data = []
    for r in rows:
        uname = r["username"]
        bal = balances.get(uname, 0)
        data.append({
            "order_id": r["order_id"],
            "nickname": r["nickname"],
            "username": uname,
            "price": float(r["total_price"] or 0),  # <- hiện cột này
            "balance": bal,                          # <- dùng ngầm để cảnh báo
            "is_warning": bal <= -19
        })

    return render_template("donhang.html", data=data)

@app.route("/order-details/<path:order_id>")
def order_details(order_id):
    conn=get_donhang_db_safe()
    order=conn.execute("SELECT * FROM tonghopdon WHERE order_id=?",(order_id,)).fetchone()
    if not order:
        conn.close(); return jsonify({"error":"not found"}),404
    details=conn.execute("SELECT price FROM chitietdon WHERE order_id=? ORDER BY id",(order_id,)).fetchall()
    prices=[[str(d["price"])] for d in details] or [[str(order["total_price"] or 0)]]
    result={"order_id":order["order_id"],"nickname":order["nickname"],"username":order["username"],"total_items":len(prices),"total_price":str(order["total_price"] or 0),"prices":prices}
    conn.close()
    return jsonify(result)

@app.route("/chamcong")
def chamcong_index():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    # Kiểm tra vai trò để điều hướng đến đúng trang dashboard
    role = session.get('role')
    if role == 'QTV':
        return redirect(url_for('admin_dashboard'))
    elif role in ['parttime', 'Part Time']:
        return redirect(url_for('part_time_dashboard'))
    
    return redirect(url_for('employee_dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username=request.form['username'].strip()
        password=request.form['password'].strip()
        conn=get_db(); cur=conn.cursor()
        cur.execute("SELECT * FROM nv WHERE username = ? AND password = ?", (username, password))
        user=cur.fetchone(); conn.close()
        if user:
            session['user_id']=user['id']; session['username']=user['username']; session['hovaten']=user['hovaten']; session['role']=user['chucdanh']
            flash('Đăng nhập thành công!', 'success')
            return redirect(url_for('chamcong_index'))
            
        else:
            flash('Tên đăng nhập hoặc mật khẩu không đúng.', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear(); flash('Đã đăng xuất tài khoản.', 'info'); return redirect(url_for('login'))

@app.route('/admin')
def admin_dashboard():
    if session.get('role') != 'QTV': return "Từ chối truy cập!", 403
    conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT * FROM nv WHERE chucdanh != 'QTV'")
    employees=cur.fetchall()
    emp_list=[]
    for emp in employees:
        details=calculate_salary_details(emp, conn); emp_list.append(details)
    conn.close()
    return render_template('admin_dashboard.html', employees=emp_list)

@app.route('/admin/add_employee', methods=['POST'])
def add_employee():
    if session.get('role') != 'QTV': return "Từ chối truy cập!", 403
    username=request.form['username'].strip(); password=request.form['password'].strip(); hovaten=request.form['hovaten'].strip(); chucdanh=request.form['chucdanh']; luong=float(request.form['luong'] or 0)
    luong_theo_gio=float(request.form.get('luong_theo_gio') or 0)
    
    conn=get_db(); cur=conn.cursor()
    try:
        cur.execute('INSERT INTO nv (username, password, hovaten, chucdanh, luong, luong_theo_gio) VALUES (?, ?, ?, ?, ?, ?)', (username, password, hovaten, chucdanh, luong, luong_theo_gio))
        conn.commit(); flash('Thêm nhân viên mới thành công!', 'success')
    except sqlite3.IntegrityError:
        flash('Tên đăng nhập đã tồn tại!', 'danger')
    finally: conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/edit_employee/<int:emp_id>', methods=['GET', 'POST'])
def edit_employee(emp_id):
    if session.get('role') != 'QTV': return "Từ chối truy cập!", 403
    conn=get_db(); cur=conn.cursor()
    if request.method == 'POST':
        hovaten=request.form['hovaten'].strip(); chucdanh=request.form['chucdanh']; luong=float(request.form['luong'] or 0); password=request.form['password'].strip()
        luong_theo_gio=float(request.form.get('luong_theo_gio') or 0)
        
        if password: cur.execute('UPDATE nv SET hovaten=?, chucdanh=?, luong=?, luong_theo_gio=?, password=? WHERE id=?', (hovaten, chucdanh, luong, luong_theo_gio, password, emp_id))
        else: cur.execute('UPDATE nv SET hovaten=?, chucdanh=?, luong=?, luong_theo_gio=? WHERE id=?', (hovaten, chucdanh, luong, luong_theo_gio, emp_id))
        conn.commit(); flash('Cập nhật thông tin nhân viên thành công!', 'success'); conn.close(); return redirect(url_for('admin_dashboard'))
    cur.execute("SELECT * FROM nv WHERE id = ?", (emp_id,)); emp=cur.fetchone()
    cur.execute("SELECT * FROM chi_tiet_phat_sinh WHERE employee_id = ? ORDER BY date DESC", (emp_id,)); phat_sinh=cur.fetchall()
    details=calculate_salary_details(emp, conn); conn.close()
    return render_template('edit_employee.html', emp=details, phat_sinh=phat_sinh)

@app.route('/admin/delete_employee/<int:emp_id>')
def delete_employee(emp_id):
    if session.get('role') != 'QTV': 
        return "Từ chối truy cập!", 403
        
    conn = get_db()
    cur = conn.cursor()
    
    # 1. Xóa các bản ghi liên quan ở bảng phụ thuộc trước
    cur.execute("DELETE FROM cham_cong_part_time WHERE employee_id = ?", (emp_id,))
    cur.execute("DELETE FROM chi_tiet_phat_sinh WHERE employee_id = ?", (emp_id,))
    # cur.execute("DELETE FROM cham_cong_chinh_thuc WHERE employee_id = ?", (emp_id,)) # Thêm nếu có

    # 2. Xóa nhân viên khỏi bảng chính
    cur.execute("DELETE FROM nv WHERE id = ?", (emp_id,))
    
    conn.commit()
    conn.close()
    
    flash('Đã xóa hoàn toàn nhân viên và dữ liệu liên quan khỏi hệ thống.', 'warning')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/add_phat_sinh/<int:emp_id>', methods=['POST'])
def add_phat_sinh(emp_id):
    if session.get('role') != 'QTV': return "Từ chối truy cập!", 403
    date_val = request.form['date']
    noidung = request.form['noidung'].strip()
    sotien = float(request.form['sotien'] or 0)
    loai = request.form['loai']
    
    conn = get_db()
    cur = conn.cursor()
    
    # Kiểm tra chức danh nhân viên để redirect chính xác
    cur.execute("SELECT chucdanh FROM nv WHERE id = ?", (emp_id,))
    emp = cur.fetchone()
    
    cur.execute('INSERT INTO chi_tiet_phat_sinh (employee_id, date, noidung, sotien, loai) VALUES (?, ?, ?, ?, ?)', 
                (emp_id, date_val, noidung, sotien, loai))
    conn.commit()
    conn.close()
    
    flash('Thêm khoản phát sinh thành công!', 'success')
    
    # Điều hướng thông minh dựa trên chucdanh
    if emp and emp['chucdanh'] == 'parttime':
        return redirect(url_for('edit_parttime', emp_id=emp_id))
    return redirect(url_for('edit_employee', emp_id=emp_id))

@app.route('/admin/delete_phat_sinh/<int:ps_id>/<int:emp_id>')
def delete_phat_sinh(ps_id, emp_id):
    if session.get('role') != 'QTV': return "Từ chối truy cập!", 403
    
    conn = get_db()
    cur = conn.cursor()
    
    # Lấy thông tin chức danh trước khi xóa
    cur.execute("SELECT chucdanh FROM nv WHERE id = ?", (emp_id,))
    emp = cur.fetchone()
    
    cur.execute("DELETE FROM chi_tiet_phat_sinh WHERE id = ?", (ps_id,))
    conn.commit()
    conn.close()
    
    flash('Đã xóa khoản phát sinh.', 'info')
    
    if emp and emp['chucdanh'] == 'parttime':
        return redirect(url_for('edit_parttime', emp_id=emp_id))
    return redirect(url_for('edit_employee', emp_id=emp_id))

@app.route('/admin/attendance_log/<int:emp_id>', methods=['GET', 'POST'])
def attendance_log(emp_id):
    if session.get('role') != 'QTV': 
        return "Từ chối truy cập!", 403
    conn = get_db()
    cur = conn.cursor()
    try:
        if request.method == 'POST' and 'add_attendance' in request.form:
            date_val = request.form.get('date')
            session_type = request.form.get('session')
            if not date_val or not session_type:
                flash('Thiếu ngày hoặc ca!', 'danger')
            else:
                try:
                    cur.execute("INSERT INTO attendance (employee_id, date, session) VALUES (?, ?, ?)", (emp_id, date_val, session_type))
                    conn.commit()
                    flash('Thêm công mới thành công!', 'success')
                except sqlite3.IntegrityError:
                    flash('Ca này đã được ghi rồi!', 'danger')
                except Exception as e:
                    import traceback
                    print(traceback.format_exc())
                    flash(f'Lỗi ghi DB: {e}', 'danger')

        cur.execute("SELECT * FROM nv WHERE id = ?", (emp_id,))
        emp = cur.fetchone()
        if not emp:
            flash(f'Nhân viên id={emp_id} không tồn tại trên Render! Hãy sync lại nv.db', 'danger')
            conn.close()
            return redirect(url_for('home'))

        cur.execute("SELECT * FROM attendance WHERE employee_id = ? ORDER BY date DESC, session DESC", (emp_id,))
        logs = cur.fetchall()
        details = calculate_salary_details(emp, conn)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[ATTENDANCE_LOG ERROR] {e}")
        flash(f'Lỗi hệ thống: {e}', 'danger')
        logs = []
        details = dict(emp) if emp else {}
    finally:
        try: conn.close()
        except: pass

    return render_template('attendance_log.html', emp=details, logs=logs)

@app.route('/admin/delete_attendance/<int:att_id>/<int:emp_id>')
def delete_attendance(att_id, emp_id):
    if session.get('role') != 'QTV': return "Từ chối truy cập!", 403
    conn=get_db(); cur=conn.cursor(); cur.execute("DELETE FROM attendance WHERE id = ?", (att_id,)); conn.commit(); conn.close()
    flash('Đã xóa chấm công đã chọn.', 'warning'); return redirect(url_for('attendance_log', emp_id=emp_id))

#------ hàm chốt công và thanh toán lương ---------------
@app.route('/admin/pay_salary/<int:emp_id>', methods=['POST'])
def pay_salary(emp_id):
    if session.get('role') != 'QTV': 
        return "Từ chối truy cập!", 403
        
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM nv WHERE id = ?", (emp_id,))
    emp = cur.fetchone()
    
    if not emp: 
        return "Nhân viên không tồn tại", 404

    # Tính toán chi tiết lương
    details = calculate_salary_details(emp, conn)
    today_str = datetime.now(VN_TZ).strftime('%Y-%m-%d %H:%M:%S')

    # 1. Truy vấn danh sách chi tiết phát sinh trước khi xóa
    cur.execute("""
        SELECT id, employee_id, date, noidung, sotien, loai 
        FROM chi_tiet_phat_sinh 
        WHERE employee_id = ?
    """, (emp_id,))
    rows_ps = cur.fetchall()
    
    # 2. Chuyển đổi dữ liệu phát sinh thành danh sách dict và serialize sang JSON
    ds_phat_sinh = []
    for r in rows_ps:
        ds_phat_sinh.append({
            'id': r['id'] if isinstance(r, sqlite3.Row) else r[0],
            'employee_id': r['employee_id'] if isinstance(r, sqlite3.Row) else r[1],
            'date': r['date'] if isinstance(r, sqlite3.Row) else r[2],
            'noidung': r['noidung'] if isinstance(r, sqlite3.Row) else r[3],
            'sotien': r['sotien'] if isinstance(r, sqlite3.Row) else r[4],
            'loai': r['loai'] if isinstance(r, sqlite3.Row) else r[5]
        })
    
    chi_tiet_ps_json = json.dumps(ds_phat_sinh, ensure_ascii=False)

    # 3. Phân nhánh theo chức danh và lưu lịch sử kèm cột chi_tiet_ps
    if emp['chucdanh'] == 'parttime':
        # Truyền thêm luong_co_ban=0 và tong_cong=0 để không vi phạm ràng buộc NOT NULL của SQLite
        cur.execute('''
            INSERT INTO payment_history (
                employee_id, payment_date, luong_co_ban, tong_cong,
                luong_theo_gio, gio_lam, thu_nhap_tinh, tong_phat_sinh, thuc_nhan, chi_tiet_ps
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            emp_id, 
            today_str, 
            0,                             # luong_co_ban = 0 (tránh lỗi NOT NULL)
            0,                             # tong_cong = 0 (tránh lỗi NOT NULL)
            emp['luong_theo_gio'],         # Mức lương/giờ
            details.get('tong_gio', 0),    # Tổng số giờ làm
            details['thu_nhap_uoc_tinh'], 
            details['tong_phat_sinh'], 
            details['thuc_nhan'],
            chi_tiet_ps_json
        ))
        
        cur.execute("DELETE FROM cham_cong_part_time WHERE employee_id = ?", (emp_id,))
    else:
        # Trường hợp Nhân viên Chính thức:
        # Lưu vào luong_co_ban và tong_cong trong payment_history
        cur.execute('''
            INSERT INTO payment_history (
                employee_id, payment_date, luong_co_ban, tong_cong, 
                thu_nhap_tinh, tong_phat_sinh, thuc_nhan, chi_tiet_ps
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            emp_id, 
            today_str, 
            details['luong'],              # Hoặc emp['luong']
            details['tong_cong'], 
            details['thu_nhap_uoc_tinh'], 
            details['tong_phat_sinh'], 
            details['thuc_nhan'],
            chi_tiet_ps_json
        ))
        
        # Xóa dữ liệu chấm công chu kỳ cũ của Nhân viên chính thức
        cur.execute("DELETE FROM attendance WHERE employee_id = ?", (emp_id,))

    # Xóa chi tiết phát sinh (Dùng chung cho cả 2 loại nhân viên)
    cur.execute("DELETE FROM chi_tiet_phat_sinh WHERE employee_id = ?", (emp_id,))
    
    conn.commit()
    conn.close()

    flash(f"Thanh toán lương thành công cho nhân viên {emp['hovaten']}. Hệ thống đã reset chu kỳ chấm công.", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/employee')
def employee_dashboard():
    if 'user_id' not in session or session.get('role') == 'QTV': return redirect(url_for('login'))
    emp_id=session['user_id']; conn=get_db(); cur=conn.cursor()
    cur.execute("SELECT * FROM nv WHERE id = ?", (emp_id,)); emp=cur.fetchone()
    details=calculate_salary_details(emp, conn)
    cur.execute("SELECT * FROM chi_tiet_phat_sinh WHERE employee_id = ? ORDER BY date DESC", (emp_id,)); phat_sinh=cur.fetchall()
    cur.execute("SELECT * FROM attendance WHERE employee_id = ? ORDER BY date DESC, session DESC", (emp_id,)); attendance_history=cur.fetchall()
    conn.close()
    now=datetime.now(VN_TZ); current_time=now.strftime('%H:%M')
    sang_available="07:30" <= current_time <= "11:30"; chieu_available="13:30" <= current_time <= "17:30"
    return render_template('employee_dashboard.html', emp=details, phat_sinh=phat_sinh, history=attendance_history, sang_available=sang_available, chieu_available=chieu_available, current_time=current_time)

@app.route('/employee/checkin', methods=['POST'])
def employee_checkin():
    if 'user_id' not in session: 
        return redirect(url_for('login'))
        
    emp_id = session['user_id']
    session_type = request.form['session_type']
    now = datetime.now(VN_TZ)
    current_time = now.strftime('%H:%M')
    today_str = now.strftime('%Y-%m-%d')
    
    # Kiểm tra khung giờ chấm công
    if session_type == 'sang' and not ("07:30" <= current_time <= "11:30"):
        flash("Ngoài khung giờ chấm công Ca Sáng (07:30 - 11:30)!", "danger")
        return redirect(url_for('employee_dashboard'))
    elif session_type == 'chieu' and not ("13:30" <= current_time <= "17:30"):
        flash("Ngoài khung giờ chấm công Ca Chiều (13:30 - 17:30)!", "danger")
        return redirect(url_for('employee_dashboard'))
    
    # Thực hiện ghi nhận chấm công kèm IP tự động qua hàm dùng chung
    try:
        save_attendance_log('attendance', emp_id, today_str, session_type)
        flash(f"Điểm danh thành công Ca {session_type.capitalize()} ngày {today_str}!", "success")
    except sqlite3.IntegrityError:
        flash(f"Bạn đã chấm công Ca {session_type.capitalize()} cho ngày hôm nay rồi!", "warning")
        
    return redirect(url_for('employee_dashboard'))

# ==========================================
# PHẦN CODE CHO NHÂN VIÊN PART-TIME
# ==========================================

from datetime import datetime, time
from zoneinfo import ZoneInfo
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# Route Dashboard dành cho Part Time - fix Render
@app.route('/part-time')
def part_time_dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if session.get('role') not in ['parttime', 'Part Time']:
        flash('Bạn không có quyền truy cập trang này!', 'danger')
        return redirect(url_for('login'))

    emp_id = session['user_id']
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM nv WHERE id =?", (emp_id,))
        emp = cur.fetchone()
        if not emp:
            flash('Nhân viên không tồn tại', 'danger')
            return redirect(url_for('login'))

        cur.execute("SELECT * FROM cham_cong_part_time WHERE employee_id=? AND trang_thai='da_duyet' ORDER BY date DESC", (emp_id,))
        approved_records = cur.fetchall()
        tong_phut = sum((r['so_phut'] or 0) for r in approved_records)
        tong_gio = round(tong_phut/60.0, 2)
        luong_theo_gio = emp['luong_theo_gio'] or 0

        cur.execute("SELECT * FROM chi_tiet_phat_sinh WHERE employee_id=? ORDER BY date DESC", (emp_id,))
        phat_sinh = cur.fetchall()
        tong_ps = sum(ps['sotien'] if ps['loai']=='tang' else -ps['sotien'] for ps in phat_sinh)

        cur.execute("SELECT * FROM cham_cong_part_time WHERE employee_id=? ORDER BY date DESC, id DESC", (emp_id,))
        history = cur.fetchall()

        # QUAN TRỌNG: dùng giờ VN
        today_str = datetime.now(VN_TZ).strftime('%Y-%m-%d')
        cur.execute("SELECT * FROM cham_cong_part_time WHERE employee_id=? AND date=?", (emp_id, today_str))
        today_records = {r['ca']: dict(r) for r in cur.fetchall()}

        emp_data = {
            'hovaten': emp['hovaten'],
            'chucdanh': emp['chucdanh'],
            'luong_theo_gio': luong_theo_gio,
            'tong_gio': tong_gio,
            'uoc_tinh_luong': tong_gio * luong_theo_gio,
            'tong_phat_sinh': tong_ps,
            'thuc_nhan': tong_gio * luong_theo_gio + tong_ps
        }
        return render_template('part_time.html', emp=emp_data, phat_sinh=phat_sinh, history=history, today=today_records)
    finally:
        try: conn.close()
        except: pass

# API Xử lý Chấm công - bản fix Render
@app.route('/part-time/checkin', methods=['POST'])
def parttime_checkin():
    if 'user_id' not in session or session.get('role') not in ['parttime', 'Part Time']:
        flash('Bạn không có quyền thực hiện thao tác này!', 'danger')
        return redirect(url_for('login'))

    ca = request.form.get('ca')
    action = request.form.get('action')

    # DÙNG GIỜ VN, không dùng giờ UTC của Render
    now = datetime.now(VN_TZ)
    current_time = now.time()
    today_str = now.strftime('%Y-%m-%d')
    time_str = now.strftime('%H:%M:%S')

    time_ranges = {
        'sang': (time(7, 0), time(12, 0)),
        'chieu': (time(13, 0), time(18, 30)),
        'toi': (time(18, 30), time(23, 59, 59))
    }
    if ca not in time_ranges:
        flash('Ca làm việc không hợp lệ!', 'danger')
        return redirect(url_for('part_time_dashboard'))

    start_valid, end_valid = time_ranges[ca]
    if not (start_valid <= current_time <= end_valid):
        flash(f'Không thể chấm công ngoài ca làm việc! Hiện tại {current_time.strftime("%H:%M")} VN, ca {ca} cho phép {start_valid.strftime("%H:%M")}-{end_valid.strftime("%H:%M")}', 'danger')
        return redirect(url_for('part_time_dashboard'))

    emp_id = session['user_id']
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM cham_cong_part_time WHERE employee_id=? AND date=? AND ca=?", (emp_id, today_str, ca))
        record = cur.fetchone()

        if action == 'check_in':
            if record and record['check_in']:
                flash(f'Bạn đã bắt đầu ca {ca} hôm nay rồi!', 'warning')
            else:
                if not record:
                    save_attendance_log('cham_cong_part_time', emp_id, today_str, ca, check_in_time=time_str)
                else:
                    ip_addr = get_client_ip()
                    cur.execute("UPDATE cham_cong_part_time SET check_in=?, ip_address=? WHERE id=?", (time_str, ip_addr, record['id']))
                    conn.commit()
                flash(f'Bắt đầu ca {ca.upper()} lúc {time_str} thành công!', 'success')

        elif action == 'check_out':
            if not record or not record['check_in']:
                flash('Bạn chưa bấm Bắt đầu ca này!', 'warning')
            elif record['check_out']:
                flash('Bạn đã bấm Kết thúc ca này rồi!', 'warning')
            else:
                # tính phút, chấp nhận cả HH:MM:SS
                try:
                    t_in = datetime.strptime(record['check_in'][:8], '%H:%M:%S')
                    t_out = datetime.strptime(time_str, '%H:%M:%S')
                    so_phut = int((t_out - t_in).total_seconds() // 60)
                    if so_phut < 0: so_phut = 0
                except:
                    so_phut = 0
                cur.execute("UPDATE cham_cong_part_time SET check_out=?, so_phut=? WHERE id=?", (time_str, so_phut, record['id']))
                conn.commit()
                flash(f'Kết thúc ca {ca.upper()} lúc {time_str}. Tổng {so_phut} phút.', 'success')
    except Exception as e:
        import traceback; traceback.print_exc()
        flash(f'Lỗi chấm công: {e}', 'danger')
    finally:
        try: conn.close()
        except: pass

    return redirect(url_for('part_time_dashboard'))

# ==========================================
# PHẦN CODE QUẢN LÝ NHÂN VIÊN PART-TIME
# ==========================================

# 1. Edit part-time - bản fix Render
@app.route('/admin/parttime/edit/<int:emp_id>', methods=['GET', 'POST'])
def edit_parttime(emp_id):
    if 'user_id' not in session or session.get('role') not in ['QTV', 'Admin']:
        flash('Bạn không có quyền truy cập trang này!', 'danger')
        return redirect(url_for('login'))
    conn = get_db()
    cur = conn.cursor()
    try:
        if request.method == 'POST':
            hovaten = request.form.get('hovaten','').strip()
            chucdanh = request.form.get('chucdanh','').strip()
            luong_raw = request.form.get('luong_theo_gio','0').replace(',','').strip()
            try:
                luong_theo_gio = float(luong_raw) if luong_raw else 0
            except:
                luong_theo_gio = 0
            password = request.form.get('password','').strip()
            if password:
                cur.execute("UPDATE nv SET hovaten=?, chucdanh=?, luong_theo_gio=?, password=? WHERE id=?",
                            (hovaten, chucdanh, luong_theo_gio, password, emp_id))
            else:
                cur.execute("UPDATE nv SET hovaten=?, chucdanh=?, luong_theo_gio=? WHERE id=?",
                            (hovaten, chucdanh, luong_theo_gio, emp_id))
            conn.commit()
            flash('Cập nhật Part-time thành công!', 'success')
            return redirect(url_for('edit_parttime', emp_id=emp_id))

        cur.execute("SELECT * FROM nv WHERE id = ?", (emp_id,))
        emp = cur.fetchone()
        if not emp:
            flash(f'Nhân viên {emp_id} không có trên Render', 'danger')
            return redirect(url_for('home'))

        cur.execute("SELECT * FROM cham_cong_part_time WHERE employee_id=? AND trang_thai='da_duyet'", (emp_id,))
        approved = cur.fetchall()
        tong_phut = sum((r['so_phut'] or 0) for r in approved)
        tong_gio = round(tong_phut/60.0, 2)
        uoc_tinh = tong_gio * (emp['luong_theo_gio'] or 0)

        cur.execute("SELECT * FROM chi_tiet_phat_sinh WHERE employee_id=? ORDER BY date DESC", (emp_id,))
        phat_sinh = cur.fetchall()
        tong_ps = sum(ps['sotien'] if ps['loai']=='tang' else -ps['sotien'] for ps in phat_sinh)

        emp_data = dict(emp)
        emp_data.update({'tong_gio': tong_gio, 'thu_nhap_uoc_tinh': uoc_tinh, 'tong_phat_sinh': tong_ps, 'thuc_nhan': uoc_tinh+tong_ps})
        return render_template('edit_parttime.html', emp=emp_data, phat_sinh=phat_sinh)
    except Exception as e:
        import traceback; traceback.print_exc()
        flash(f'Lỗi: {e}', 'danger')
        return redirect(url_for('home'))
    finally:
        try: conn.close()
        except: pass

# 2. Nhật ký chấm công part-time - fix datetime + None
@app.route('/admin/parttime/attendance/<int:emp_id>', methods=['GET', 'POST'])
def parttime_attendance_log(emp_id):
    if 'user_id' not in session or session.get('role') not in ['QTV', 'Admin']:
        flash('Bạn không có quyền!', 'danger')
        return redirect(url_for('login'))
    conn = get_db()
    cur = conn.cursor()
    try:
        if request.method == 'POST' and request.form.get('add_attendance'):
            date_str = request.form.get('date')
            ca = request.form.get('ca')
            check_in = request.form.get('check_in','').strip()
            check_out = request.form.get('check_out','').strip()
            so_phut = 0
            # chấp nhận cả HH:MM và HH:MM:SS
            def parse_hhmm(s):
                if not s: return None
                s = s.strip()[:5]
                return datetime.strptime(s, '%H:%M')
            if check_in and check_out:
                try:
                    t_in = parse_hhmm(check_in)
                    t_out = parse_hhmm(check_out)
                    so_phut = int((t_out - t_in).total_seconds()//60)
                    if so_phut < 0: so_phut = 0
                except Exception as e:
                    print(f"parse time error {e}")
                    so_phut = 0
                if len(check_in)==5: check_in+=":00"
                if len(check_out)==5: check_out+=":00"
            cur.execute("INSERT INTO cham_cong_part_time (employee_id, date, ca, check_in, check_out, so_phut, trang_thai) VALUES (?,?,?,?,?,?, 'da_duyet')",
                        (emp_id, date_str, ca, check_in, check_out, so_phut))
            conn.commit()
            flash('Thêm công thủ công thành công!', 'success')
            return redirect(url_for('parttime_attendance_log', emp_id=emp_id))

        cur.execute("SELECT * FROM nv WHERE id=?", (emp_id,))
        emp = cur.fetchone()
        if not emp:
            flash('Nhân viên không tồn tại trên Render', 'danger')
            return redirect(url_for('home'))

        cur.execute("SELECT * FROM cham_cong_part_time WHERE employee_id=? ORDER BY date DESC, id DESC", (emp_id,))
        logs = cur.fetchall()
        cur.execute("SELECT * FROM cham_cong_part_time WHERE employee_id=? AND trang_thai='da_duyet'", (emp_id,))
        approved = cur.fetchall()
        tong_phut = sum((r['so_phut'] or 0) for r in approved)
        tong_gio = round(tong_phut/60.0, 2)
        uoc_tinh = tong_gio * (emp['luong_theo_gio'] or 0)
        cur.execute("SELECT * FROM chi_tiet_phat_sinh WHERE employee_id=?", (emp_id,))
        ps = cur.fetchall()
        tong_ps = sum(p['sotien'] if p['loai']=='tang' else -p['sotien'] for p in ps)

        emp_data = dict(emp)
        emp_data.update({'tong_gio': tong_gio, 'tong_phat_sinh': tong_ps, 'thuc_nhan': uoc_tinh+tong_ps})
        return render_template('parttime_attendance_log.html', emp=emp_data, logs=logs)
    except Exception as e:
        import traceback; traceback.print_exc()
        flash(f'Lỗi: {e}', 'danger')
        return redirect(url_for('home'))
    finally:
        try: conn.close()
        except: pass


# API Cập nhật giờ làm & Xác nhận công Part-Time - bản fix Render
@app.route('/admin/parttime/update-log/<int:log_id>', methods=['POST'])
def update_parttime_log(log_id):
    if 'user_id' not in session or session.get('role') not in ['QTV', 'Admin']:
        flash('Bạn không có quyền thực hiện thao tác này!', 'danger')
        return redirect(url_for('login'))

    emp_id = request.form.get('emp_id')
    check_in = (request.form.get('check_in') or '').strip()
    check_out = (request.form.get('check_out') or '').strip()
    action = request.form.get('action')

    conn = get_db()
    cur = conn.cursor()
    try:
        so_phut = 0
        if check_in and check_out:
            try:
                # chấp nhận cả HH:MM và HH:MM:SS
                c_in_str = check_in[:5]
                c_out_str = check_out[:5]
                t_in = datetime.strptime(c_in_str, '%H:%M')
                t_out = datetime.strptime(c_out_str, '%H:%M')
                so_phut = int((t_out - t_in).total_seconds() // 60)
                if so_phut < 0:
                    so_phut = 0
            except Exception as e:
                print(f"[parse time error] {e}")
                so_phut = 0

            if len(check_in) == 5: check_in += ":00"
            if len(check_out) == 5: check_out += ":00"

        if action == 'confirm':
            cur.execute("""
                UPDATE cham_cong_part_time 
                SET check_in=?, check_out=?, so_phut=?, trang_thai='da_duyet' 
                WHERE id=?
            """, (check_in, check_out, so_phut, log_id))
            flash('Đã duyệt và xác nhận công!', 'success')
        else:
            cur.execute("""
                UPDATE cham_cong_part_time 
                SET check_in=?, check_out=?, so_phut=? 
                WHERE id=?
            """, (check_in, check_out, so_phut, log_id))
            flash('Đã cập nhật giờ ra vào!', 'success')
        conn.commit()
    except Exception as e:
        import traceback; traceback.print_exc()
        flash(f'Lỗi cập nhật: {e}', 'danger')
    finally:
        try: conn.close()
        except: pass

    # emp_id có thể None nếu form lỗi
    if not emp_id:
        return redirect(url_for('home'))
    return redirect(url_for('parttime_attendance_log', emp_id=emp_id))

# API Xóa lượt chấm công Part-Time - bản fix Render
@app.route('/admin/parttime/delete-log/<int:log_id>/<int:emp_id>')
def delete_parttime_log(log_id, emp_id):
    if 'user_id' not in session or session.get('role') not in ['QTV', 'Admin']:
        flash('Bạn không có quyền thực hiện thao tác này!', 'danger')
        return redirect(url_for('login'))

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM cham_cong_part_time WHERE id=?", (log_id,))
        conn.commit()
        flash('Đã xóa lượt chấm công thành công!', 'success')
    except Exception as e:
        import traceback; traceback.print_exc()
        flash(f'Lỗi xóa: {e}', 'danger')
    finally:
        try: conn.close()
        except: pass

    return redirect(url_for('parttime_attendance_log', emp_id=emp_id))

# ==============================================================================
# PHẦN CODE LẤY ĐỊA CHỈ IP KHI CHẤM CÔNG CỦA NHÂN VIÊN + PART-TIME
# ==============================================================================
from flask import request

def get_client_ip():
    """Lấy IP chính xác của client (kể cả khi qua Proxy/Cloudflare)"""
    if request.headers.get('X-Forwarded-For'):
        # Trường hợp qua proxy, IP thật nằm ở đầu danh sách
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr

def save_attendance_log(table_name, emp_id, date_str, session_or_ca, check_in_time=None, trang_thai='cho_duyet'):
    ip_addr = get_client_ip()
    conn = get_db()
    cur = conn.cursor()
    try:
        if table_name == 'attendance':
            db_execute_with_retry(cur, """
                INSERT INTO attendance (employee_id, date, session, ip_address) 
                VALUES (?, ?, ?, ?)
            """, (emp_id, date_str, session_or_ca, ip_addr))
        elif table_name == 'cham_cong_part_time':
            db_execute_with_retry(cur, """
                INSERT INTO cham_cong_part_time (employee_id, date, ca, check_in, trang_thai, ip_address)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (emp_id, date_str, session_or_ca, check_in_time, trang_thai, ip_addr))
        conn.commit()
    except sqlite3.IntegrityError:
        raise  # để route ngoài bắt "đã chấm rồi"
    except Exception as e:
        print(f"[DB LOCK] {e}")
        raise
    finally:
        try: conn.close()
        except: pass








# ==================== SYNC API - PHẦN QUAN TRỌNG CHO GUI ====================

@app.route("/sync/<ten_db>", methods=["POST"])
def sync_db(ten_db):
    if request.headers.get("X-TOKEN") != TOKEN:
        return "Sai token",403
    if ten_db not in ["khachhang.db","nv.db"]:
        return "Ten file khong hop le",400
    tmp=ten_db+".tmp"
    request.files['file'].save(tmp)
    os.replace(tmp, ten_db)
    return f"OK {ten_db}"

# ---- THÊM MỚI 2 API NÀY ĐỂ GUI HOẠT ĐỘNG ----
def _calc_md5(file_path):
    h = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()

@app.route("/md5/<ten_db>", methods=["GET"])
@app.route("/sync/md5/<ten_db>", methods=["GET"])  # alias cho GUI
def get_md5_api(ten_db):
    if request.headers.get("X-TOKEN") != TOKEN:
        return "Sai token",403
    if ten_db not in ["khachhang.db","nv.db"]:
        return "Ten file khong hop le",400
    if not os.path.exists(ten_db):
        return jsonify({"error": "File not found"}), 404
    try:
        md5 = _calc_md5(ten_db)
        return jsonify({"md5": md5})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/download/<ten_db>", methods=["GET"])
@app.route("/sync/download/<ten_db>", methods=["GET"])  # alias cho GUI
def download_api(ten_db):
    if request.headers.get("X-TOKEN") != TOKEN:
        return "Sai token",403
    if ten_db not in ["khachhang.db","nv.db"]:
        return "Ten file khong hop le",400
    if not os.path.exists(ten_db):
        return "File not found", 404
    # dùng send_file để GUI tải về
    return send_file(ten_db, as_attachment=True, download_name=ten_db)

@app.route("/health")
def health():
    return "OK"

@app.route("/admin/cai-dat")
def cai_dat():
    if session.get("role") != "QTV": return "Từ chối truy cập!", 403
    conn=get_donhang_db_safe(); cur=conn.cursor()
    business_row=cur.execute("SELECT * FROM business_profile ORDER BY id DESC LIMIT 1").fetchone()
    business=dict(business_row) if business_row else {"name":"Biolinh 2Hand - Cửa hàng thời trang secondhand","tax_id":"","address":"Thái Nguyên","career":"Bán lẻ quần áo cũ"}
    tax_rows=cur.execute("SELECT * FROM tax_settings ORDER BY min_revenue ASC").fetchall()
    tax_settings=[dict(row) for row in tax_rows]; conn.close()
    return render_template("cai_dat.html", business=business, tax_settings=tax_settings)

@app.route("/api/business_profile", methods=["GET"])
def api_get_business_profile():
    if session.get('role') != 'QTV': return jsonify({"error": "unauthorized"}), 403
    return jsonify(get_business_profile())

@app.route("/api/business_profile/update", methods=["POST"])
def api_business_update():
    if session.get('role') != 'QTV': return jsonify({"status": "error", "error": "Không có quyền truy cập"}), 403
    data=request.get_json() or {}
    name=data.get("name","").strip(); tax_id=data.get("tax_id","").strip(); address=data.get("address","").strip(); career=data.get("career","").strip()
    if not name or not tax_id or not address or not career:
        return jsonify({"status": "error", "error": "Vui lòng nhập đầy đủ thông tin!"}), 400
    try:
        conn=get_donhang_db_safe(); cur=conn.cursor(); cur.execute("DELETE FROM business_profile"); cur.execute("INSERT INTO business_profile (name, tax_id, address, career) VALUES (?, ?, ?, ?)", (name, tax_id, address, career)); conn.commit(); conn.close()
        return jsonify({"status": "success", "message": "Đã cập nhật hồ sơ hộ kinh doanh thành công!"})
    except Exception as e:
        print("Error api_business_update:", e); return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/api/taxes/settings")
def api_taxes_settings():
    try:
        conn=get_donhang_db_safe(); tax_rows=conn.execute("SELECT * FROM tax_settings ORDER BY min_revenue ASC").fetchall(); conn.close()
        return jsonify([dict(row) for row in tax_rows])
    except Exception as e:
        print("Error api_taxes_settings:", e); return jsonify([])

@app.route("/api/taxes/settings/update", methods=["POST"])
def api_taxes_update():
    if session.get('role') != 'QTV': return jsonify({"status": "error", "error": "Không có quyền truy cập"}), 403
    data=request.get_json()
    if not isinstance(data, list): return jsonify({"status": "error", "error": "Dữ liệu không hợp lệ"}), 400
    try:
        conn=get_donhang_db_safe(); cur=conn.cursor(); cur.execute("DELETE FROM tax_settings")
        for item in data:
            cur.execute("""INSERT INTO tax_settings (group_name, min_revenue, max_revenue, vat_rate, pit_rate, note) VALUES (?, ?, ?, ?, ?, ?)""", (item.get("group_name",""), float(item.get("min_revenue") or 0), float(item.get("max_revenue") or 0), float(item.get("vat_rate") or 0), float(item.get("pit_rate") or 0), item.get("note",""),))
        conn.commit(); conn.close()
        return jsonify({"status": "success", "message": "Đã cập nhật cấu hình thuế thành công!"})
    except Exception as e:
        print("Error api_taxes_update:", e); return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/admin/baocao")
def bao_cao_new():
    if session.get('role') != 'QTV': return "Từ chối truy cập!", 403
    years=get_available_years(); business=get_business_profile(); today=datetime.now(VN_TZ).date(); tong_don=0
    try:
        conn=get_donhang_db_safe(); cur=conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='doisoat'")
        if cur.fetchone(): tong_don=cur.execute("SELECT COUNT(*) FROM doisoat").fetchone()[0]
        conn.close()
    except: pass
    return render_template("baocao.html", available_years=years, business=business, current_year=today.year, current_month=today.month, today_ddmmyyyy=today.strftime('%d/%m/%Y'), stats={"tong_don": tong_don})

@app.route("/api/reports/summary")
def api_reports_summary():
    if session.get('role') != 'QTV': return jsonify({"error": "unauthorized"}), 403
    today=datetime.now(VN_TZ).date()
    from_iso=request.args.get('from') or today.replace(day=1).isoformat()
    to_iso=request.args.get('to') or today.isoformat()
    filtered=filter_doisoat_by_range(from_iso, to_iso)
    total_revenue=sum(clean_float(r.get('revenue')) for r in filtered)
    year_start=date(today.year, 1, 1)
    year_filtered=filter_doisoat_by_range(year_start.isoformat(), today.isoformat())
    luy_ke=sum(clean_float(r.get('revenue')) for r in year_filtered)
    current_group={"group_name":"Chưa cấu hình","note":"Chưa có cấu hình thuế, mặc định miễn thuế","vat_rate":0.0,"pit_rate":0.0,"min_rev":0,"max_rev":0}
    try:
        conn=get_donhang_db_safe(); cur=conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tax_settings'")
        if cur.fetchone():
            tax_rows=cur.execute("SELECT group_name, note, min_revenue, max_revenue, vat_rate, pit_rate FROM tax_settings ORDER BY min_revenue ASC").fetchall()
            for row in tax_rows:
                min_rev=float(row['min_revenue'] or 0); max_rev=float(row['max_revenue'] or 0)
                if (luy_ke >= min_rev) and (max_rev == 0 or luy_ke <= max_rev):
                    current_group={"group_name":row['group_name'],"note":row['note'] or "","vat_rate":float(row['vat_rate'] or 0)/100.0,"pit_rate":float(row['pit_rate'] or 0)/100.0,"min_rev":min_rev,"max_rev":max_rev}
                    break
        conn.close()
    except Exception as e: print("Lỗi đối chiếu tax_settings:", e)
    vat_rate=current_group['vat_rate']; pit_rate=current_group['pit_rate']; total_tax_rate=vat_rate+pit_rate; nguong_max=current_group['max_rev']
    if nguong_max and nguong_max>0:
        con_lai=max(0.0, nguong_max-luy_ke); phan_tram=min(100, int((luy_ke/nguong_max)*100)) if nguong_max else 0
    else:
        con_lai=0.0; phan_tram=100 if luy_ke>0 else 0
    s2a_list=[]; daily_map={}; cust_map={}
    for r in filtered:
        rev=clean_float(r.get('revenue')); rd=parse_doisoat_date(r.get('date'))
        if rd:
            key=rd.strftime('%d-%m-%Y'); daily_map[key]=daily_map.get(key,0.0)+rev
        nick=(r.get('nickname') or 'Ẩn danh').strip()
        if nick not in cust_map: cust_map[nick]={'count':0,'total':0.0}
        cust_map[nick]['count']+=1; cust_map[nick]['total']+=rev
        s2a_list.append({"date":r.get('date',''),"tracking_number":r.get('tracking_number','') or r.get('order_id',''),"nickname":nick,"revenue":rev,"vat_tax":round(rev*vat_rate),"pit_tax":round(rev*pit_rate),"vat":round(rev*vat_rate),"pit":round(rev*pit_rate)})
    total_count=len(filtered); vat_tax_total=round(total_revenue*vat_rate); pit_tax_total=round(total_revenue*pit_rate)
    tax_logs=[]
    try:
        conn=get_donhang_db_safe(); cur=conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='log_nop_thue'")
        if cur.fetchone():
            rows=cur.execute("SELECT * FROM log_nop_thue WHERE nam=? ORDER BY ngay_nop DESC", (today.year,)).fetchall()
            tax_logs=[dict(x) for x in rows]
        conn.close()
    except Exception as e: print("tax_logs error", e)
    kho_stats={"tong_sp":0,"tong_kygui":0,"tong_don":0}
    try:
        conn=get_donhang_db_safe(); cur=conn.cursor()
        for tbl,key in [("chitietdon","tong_sp"),("kygui","tong_kygui"),("tonghopdon","tong_don")]:
            cur.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{tbl}'")
            if cur.fetchone(): kho_stats[key]=cur.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        conn.close()
    except: pass
    return jsonify({
        "summary":{"revenue":total_revenue,"total_count":total_count,"avg_order":total_revenue/total_count if total_count else 0.0,"tax":total_revenue*total_tax_rate,"vat_tax":vat_tax_total,"pit_tax":pit_tax_total,"vat_rate":vat_rate,"pit_rate":pit_rate,"group_name":current_group['group_name'],"note":current_group['note']},
        "daily":[{"date":k,"revenue":v} for k,v in sorted(daily_map.items(), key=lambda x: datetime.strptime(x[0], '%d-%m-%Y'))],
        "customers":sorted([{"nickname":k,"count":v['count'],"total":v['total']} for k,v in cust_map.items()], key=lambda x: x['total'], reverse=True),
        "s2a":s2a_list,
        "year_progress":{"year":today.year,"luy_ke":luy_ke,"nguong_max":nguong_max,"con_lai":con_lai,"phan_tram":phan_tram,"group_name":current_group['group_name'],"note":current_group['note'],"today_ddmmyyyy":today.strftime('%d/%m/%Y')},
        "tax_logs":tax_logs,
        "kho":kho_stats
    })

@app.route("/api/reports/customers")
def api_reports_customers_new():
    if session.get('role') != 'QTV': return jsonify({"error":"unauthorized"}),403
    customers = get_all_doisoat_customers()
    q = request.args.get('q','').strip().lower()
    if q:
        customers = [c for c in customers if q in c['nickname'].lower() or q in c['username'].lower()]
    top20 = customers[:20]
    return jsonify({"customers": customers, "top20": top20, "all": customers})

@app.route("/api/reports/customers/inactive")
def api_reports_customers_inactive():
    if session.get('role') != 'QTV': return jsonify({"error":"unauthorized"}),403
    try:
        months = int(request.args.get('months', '3'))
    except:
        months = 3
    from datetime import timedelta
    cutoff = date.today() - timedelta(days=months*30)
    all_customers = get_all_doisoat_customers()
    inactive = []
    for c in all_customers:
        if not c['last_date_obj']:
            continue
        try:
            last = datetime.strptime(c['last_date_obj'], '%Y-%m-%d').date()
        except:
            try:
                last = datetime.strptime(c['last_date'], '%d-%m-%Y').date()
            except:
                continue
        if last < cutoff:
            inactive.append(c)
    inactive_sorted = sorted(inactive, key=lambda x: x['days_inactive'] or 0, reverse=True)
    return jsonify({"inactive": inactive_sorted, "cutoff_months": months, "cutoff_date": cutoff.isoformat()})

@app.route("/api/reports/tonghop_don")
def api_tonghop_don():
    if session.get('role') != 'QTV': return jsonify({"error":"unauthorized"}),403
    try:
        conn=get_donhang_db_safe(); cur=conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tonghopdon'")
        if not cur.fetchone():
            conn.close(); return jsonify([])
        rows=cur.execute("SELECT username, nickname, total_price, deposit, order_id FROM tonghopdon WHERE status='Đang Dồn'").fetchall()
        grouped={}
        for r in rows:
            uname=r['username']
            if uname not in grouped: grouped[uname]={"username":uname,"nickname":r['nickname'],"total_price":0,"deposit":0,"order_ids":[],"order_count":0}
            grouped[uname]["total_price"]+=clean_float(r['total_price']); grouped[uname]["deposit"]+=clean_float(r['deposit']); grouped[uname]["order_ids"].append(str(r['order_id'])); grouped[uname]["order_count"]+=1
        result=sorted(grouped.values(), key=lambda x: x["deposit"]); conn.close(); return jsonify(result)
    except Exception as e: print(e); return jsonify([])

@app.route("/api/taxes/pay", methods=["POST"])
def api_taxes_pay():
    if session.get('role') != 'QTV': return jsonify({"error": "unauthorized"}), 403
    data=request.get_json() or {}
    try:
        today=datetime.now(VN_TZ).date()
        try: nam=int(data.get('nam', today.year))
        except: nam=today.year
        conn=get_donhang_db_safe(); cur=conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS log_nop_thue (id INTEGER PRIMARY KEY AUTOINCREMENT, nam INTEGER, ky TEXT, ngay_nop TEXT, doanh_thu REAL, doanh_thu_luy_ke REAL, doanh_thu_mien_thue REAL, thue_gtgt REAL, thue_tncn REAL, ghi_chu TEXT)""")
        year_start=date(nam, 1, 1); year_end=date(nam, 12, 31) if nam < today.year else today
        year_filtered=filter_doisoat_by_range(year_start.isoformat(), year_end.isoformat())
        luy_ke=sum(clean_float(r.get('revenue')) for r in year_filtered)
        cur.execute("""INSERT INTO log_nop_thue (nam, ky, ngay_nop, doanh_thu, doanh_thu_luy_ke, doanh_thu_mien_thue, thue_gtgt, thue_tncn, ghi_chu) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", (nam, data.get('ky'), data.get('ngay_nop', today.isoformat()), clean_float(data.get('doanh_thu')), luy_ke, clean_float(data.get('doanh_thu_mien_thue', 0)), clean_float(data.get('thue_gtgt')), clean_float(data.get('thue_tncn')), data.get('ghi_chu','')))
        conn.commit(); conn.close(); return jsonify({"status": "success"})
    except Exception as e:
        print("pay tax error:", e); return jsonify({"error": str(e)}), 500


@app.route("/api/s2a/data")
def api_s2a_data():
    if session.get('role') != 'QTV':
        return jsonify({"error":"unauthorized"}),403
    from_iso = request.args.get('from')
    to_iso = request.args.get('to')
    data = load_s2a_data_new(from_iso, to_iso)
    return jsonify(data)

@app.route("/api/s2a/export-pdf")
def api_s2a_export_pdf():
    if session.get('role') != 'QTV':
        return jsonify({"error":"unauthorized"}),403
    from_iso = request.args.get('from')
    to_iso = request.args.get('to')
    data = load_s2a_data_new(from_iso, to_iso)
    font_reg, font_bold = register_vietnamese_font()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=25, leftMargin=25, topMargin=25, bottomMargin=25)
    elements = []
    style_normal = ParagraphStyle("NormalVN", fontName=font_reg, fontSize=9, leading=12)
    style_bold = ParagraphStyle("BoldVN", fontName=font_bold, fontSize=9, leading=12)
    style_italic = ParagraphStyle("ItalicVN", fontName=font_reg, fontSize=8, leading=11)
    style_title = ParagraphStyle("TitleVN", fontName=font_bold, fontSize=12, leading=15, alignment=1)
    p = data["profile"]
    left_hdr = [
        Paragraph(f"<b>HỘ, CÁ NHÂN KINH DOANH:</b> {sanitize_text_for_pdf(p['name'])}", style_normal),
        Paragraph(f"<b>Địa chỉ:</b> {sanitize_text_for_pdf(p['address'])}", style_normal),
        Paragraph(f"<b>Mã số thuế:</b> {sanitize_text_for_pdf(p['tax_id'])}", style_normal),
    ]
    right_hdr = [
        Paragraph("<para align='center'><b>Mẫu số S2a-HKD</b><br/><i>(Kèm theo Thông tư số 152/2025/TT-BTC<br/>ngày 31 tháng 12 năm 2025 của Bộ trưởng<br/>Bộ Tài chính)</i></para>", style_normal)
    ]
    hdr_table = Table([[left_hdr, right_hdr]], colWidths=[330, 215])
    hdr_table.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0), (-1,-1), 0), ("RIGHTPADDING", (0,0), (-1,-1), 0)]))
    elements.append(hdr_table)
    elements.append(Spacer(1, 10))
    elements.append(Paragraph("SỔ DOANH THU BÁN HÀNG HÓA, DỊCH VỤ", style_title))
    elements.append(Paragraph(f"<para align='center'>Địa điểm kinh doanh: {sanitize_text_for_pdf(p['address'])}</para>", style_normal))
    elements.append(Paragraph(f"<para align='center'>Kỳ kê khai: {data['ky_ke_khai']}</para>", style_normal))
    elements.append(Paragraph("<para align='right'><i>Đơn vị tính: Đồng</i></para>", style_normal))
    elements.append(Spacer(1, 6))
    table_data = [
        [Paragraph("<b>Chứng từ</b>", style_bold), "", Paragraph("<b>Diễn giải</b>", style_bold), Paragraph("<b>Số tiền</b>", style_bold)],
        [Paragraph("<b>Số hiệu</b>", style_bold), Paragraph("<b>Ngày, tháng</b>", style_bold), "", ""],
        [Paragraph("<i>A</i>", style_italic), Paragraph("<i>B</i>", style_italic), Paragraph("<i>C</i>", style_italic), Paragraph("<i>1</i>", style_italic)],
        ["", "", Paragraph(f"<b>1. Ngành nghề: {sanitize_text_for_pdf(p['career'])}</b>", style_bold), ""],
    ]
    for item in data["orders"]:
        table_data.append([
            Paragraph(sanitize_text_for_pdf(item["tracking_number"]), style_normal),
            Paragraph(item["date"], style_normal),
            Paragraph(sanitize_text_for_pdf(item["dien_giai"]), style_normal),
            Paragraph(f"<para align='right'>{item['total_payment']:,.0f}</para>", style_normal),
        ])
    table_data.append(["", "", Paragraph("<b>Tổng cộng (1)</b>", style_bold), Paragraph(f"<para align='right'><b>{data['tong_doanh_thu']:,.0f}</b></para>", style_bold)])
    table_data.append(["", "", Paragraph(f"Thuế GTGT ({data['pct_gtgt']}%)", style_normal), Paragraph(f"<para align='right'>{data['thue_gtgt']:,.0f}</para>", style_normal)])
    table_data.append(["", "", Paragraph(f"Thuế TNCN ({data['pct_tncn']}%)", style_normal), Paragraph(f"<para align='right'>{data['thue_tncn']:,.0f}</para>", style_normal)])
    table_data.append(["", "", Paragraph("<b>Tổng số thuế GTGT phải nộp</b>", style_bold), Paragraph(f"<para align='right'><b>{data['thue_gtgt']:,.0f}</b></para>", style_bold)])
    table_data.append(["", "", Paragraph("<b>Tổng số thuế TNCN phải nộp</b>", style_bold), Paragraph(f"<para align='right'><b>{data['thue_tncn']:,.0f}</b></para>", style_bold)])
    table = Table(table_data, colWidths=[85, 85, 270, 105], repeatRows=3)
    table.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.black),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("SPAN", (0,0), (1,0)),
        ("SPAN", (0,0), (0,1)),
        ("SPAN", (2,0), (2,1)),
        ("SPAN", (3,0), (3,1)),
        ("ALIGN", (0,0), (-1,2), "CENTER"),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 15))
    footer = [Paragraph(f"<para align='center'><i>Ngày {data['ngay_lap']} tháng {data['thang_lap']} năm {data['nam_lap']}</i><br/><b>NGƯỜI ĐẠI DIỆN HỘ KINH DOANH/<br/>CÁ NHÂN KINH DOANH</b><br/><i>(Ký, ghi rõ họ tên và đóng dấu (nếu có))</i></para>", style_normal)]
    ft_table = Table([["", footer]], colWidths=[290, 255])
    ft_table.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0), (-1,-1), 0)]))
    elements.append(ft_table)
    doc.build(elements)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="So_S2a_HKD_152_2025.pdf", mimetype="application/pdf")




# === BẢNG KÊ MUA HÀNG - THÊM VÀO app.py ===

def ensure_bangke_table():
    try:
        conn = get_donhang_db_safe()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bangke_muahang (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ngay_mua TEXT,
                ten_nguoi_ban TEXT,
                dia_chi TEXT,
                cccd TEXT,
                dien_thoai TEXT,
                ten_hang_hoa TEXT,
                so_luong REAL,
                don_gia REAL,
                thanh_toan REAL,
                ghi_chu TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print("ensure_bangke_table error", e)

# Gọi ngay sau ensure_khachhang_tables()
ensure_bangke_table()

@app.route("/admin/bangke")
def bangke_page():
    if session.get('role') != 'QTV':
        return redirect(url_for('login'))
    return render_template("bangke.html", current_year=datetime.now(VN_TZ).year, today_ddmmyyyy=datetime.now(VN_TZ).strftime("%d/%m/%Y"))

@app.route("/api/bangke", methods=["GET"])
def api_bangke_list():
    if session.get('role') != 'QTV':
        return jsonify({"error":"unauthorized"}),403
    q = request.args.get('q','').strip().lower()
    from_date = request.args.get('from')
    to_date = request.args.get('to')
    try:
        conn = get_donhang_db_safe()
        cur = conn.cursor()
        sql = "SELECT * FROM bangke_muahang WHERE 1=1"
        params = []
        if from_date:
            sql += " AND date(ngay_mua) >= date(?)"
            params.append(from_date)
        if to_date:
            sql += " AND date(ngay_mua) <= date(?)"
            params.append(to_date)
        if q:
            sql += " AND (lower(ten_nguoi_ban) LIKE ? OR lower(ten_hang_hoa) LIKE ? OR lower(cccd) LIKE ? OR lower(dien_thoai) LIKE ?)"
            like = f"%{q}%"
            params.extend([like, like, like, like])
        sql += " ORDER BY date(ngay_mua) DESC, id DESC"
        rows = cur.execute(sql, params).fetchall()
        conn.close()
        result = [dict(r) for r in rows]
        tong = sum(clean_float(r.get('thanh_toan') or 0) for r in result)
        return jsonify({"data": result, "tong": tong, "count": len(result)})
    except Exception as e:
        print("api_bangke_list error", e)
        return jsonify({"data":[], "tong":0, "count":0})

@app.route("/api/bangke/add", methods=["POST"])
def api_bangke_add():
    if session.get('role') != 'QTV':
        return jsonify({"error":"unauthorized"}),403
    d = request.get_json() or {}
    try:
        so_luong = clean_float(d.get('so_luong'))
        don_gia = clean_float(d.get('don_gia'))
        thanh_toan = clean_float(d.get('thanh_toan')) or (so_luong * don_gia)
        conn = get_donhang_db_safe()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO bangke_muahang (ngay_mua, ten_nguoi_ban, dia_chi, cccd, dien_thoai, ten_hang_hoa, so_luong, don_gia, thanh_toan, ghi_chu)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (d.get('ngay_mua'), d.get('ten_nguoi_ban'), d.get('dia_chi'), d.get('cccd'), d.get('dien_thoai'), d.get('ten_hang_hoa'), so_luong, don_gia, thanh_toan, d.get('ghi_chu')))
        conn.commit()
        conn.close()
        return jsonify({"status":"success"})
    except Exception as e:
        print("add error", e)
        return jsonify({"error": str(e)}),500

@app.route("/api/bangke/edit", methods=["POST"])
def api_bangke_edit():
    if session.get('role') != 'QTV':
        return jsonify({"error":"unauthorized"}),403
    d = request.get_json() or {}
    try:
        id_ = d.get('id')
        if not id_:
            return jsonify({"error":"missing id"}),400
        so_luong = clean_float(d.get('so_luong'))
        don_gia = clean_float(d.get('don_gia'))
        thanh_toan = clean_float(d.get('thanh_toan')) or (so_luong * don_gia)
        conn = get_donhang_db_safe()
        cur = conn.cursor()
        cur.execute("""
            UPDATE bangke_muahang SET ngay_mua=?, ten_nguoi_ban=?, dia_chi=?, cccd=?, dien_thoai=?, ten_hang_hoa=?, so_luong=?, don_gia=?, thanh_toan=?, ghi_chu=? WHERE id=?
        """, (d.get('ngay_mua'), d.get('ten_nguoi_ban'), d.get('dia_chi'), d.get('cccd'), d.get('dien_thoai'), d.get('ten_hang_hoa'), so_luong, don_gia, thanh_toan, d.get('ghi_chu'), id_))
        conn.commit()
        conn.close()
        return jsonify({"status":"success"})
    except Exception as e:
        print("edit error", e)
        return jsonify({"error": str(e)}),500

@app.route("/api/bangke/delete", methods=["POST"])
def api_bangke_delete():
    if session.get('role') != 'QTV':
        return jsonify({"error":"unauthorized"}),403
    d = request.get_json() or {}
    try:
        id_ = d.get('id')
        conn = get_donhang_db_safe()
        cur = conn.cursor()
        cur.execute("DELETE FROM bangke_muahang WHERE id=?", (id_,))
        conn.commit()
        conn.close()
        return jsonify({"status":"success"})
    except Exception as e:
        return jsonify({"error": str(e)}),500

@app.route("/api/bangke/export-pdf")
def api_bangke_export_pdf():
    if session.get('role') != 'QTV':
        return jsonify({"error": "unauthorized"}), 403

    from_iso = request.args.get('from')
    to_iso = request.args.get('to')
    q = request.args.get('q', '')

    try:
        conn = get_donhang_db_safe()
        cur = conn.cursor()
        sql = "SELECT * FROM bangke_muahang WHERE 1=1"
        params = []
        if from_iso:
            sql += " AND date(ngay_mua) >= date(?)"
            params.append(from_iso)
        if to_iso:
            sql += " AND date(ngay_mua) <= date(?)"
            params.append(to_iso)
        if q:
            sql += " AND (lower(ten_nguoi_ban) LIKE ? OR lower(ten_hang_hoa) LIKE ? OR lower(cccd) LIKE ? OR lower(dien_thoai) LIKE ?)"
            like = f"%{q.lower()}%"
            params.extend([like, like, like, like])
        sql += " ORDER BY date(ngay_mua) ASC, id ASC"
        rows = cur.execute(sql, params).fetchall()
        conn.close()
        data_rows = [dict(r) for r in rows]
    except Exception as e:
        print(e)
        data_rows = []

    font_reg, font_bold = register_vietnamese_font()
    buffer = io.BytesIO()
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors

    # Khởi tạo document khổ A4 ngang
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=landscape(A4), 
        rightMargin=36, 
        leftMargin=36, 
        topMargin=36, 
        bottomMargin=36
    )
    elements = []

    # Định dạng các Style chữ
    style_normal = ParagraphStyle("NormalVN", fontName=font_reg, fontSize=8, leading=11)
    style_bold = ParagraphStyle("BoldVN", fontName=font_bold, fontSize=8, leading=11)
    style_small = ParagraphStyle("SmallVN", fontName=font_reg, fontSize=7.5, leading=9, alignment=1)
    
    style_title = ParagraphStyle("TitleVN", fontName=font_bold, fontSize=12, leading=15, alignment=1)
    style_header_cell = ParagraphStyle("HeaderCell", fontName=font_bold, fontSize=8, leading=10, alignment=1)
    style_center = ParagraphStyle("CenterVN", fontName=font_reg, fontSize=8, leading=11, alignment=1)
    style_italic_center = ParagraphStyle("ItalicCenterVN", fontName=font_reg, fontSize=8, leading=11, alignment=1)

    profile = get_business_profile()

    # Xác định ngày/tháng/năm hiển thị trên tiêu đề bảng kê
    now = datetime.now(VN_TZ)
    ngay_bk = now.strftime("%d")
    thang_bk = now.strftime("%m")
    nam_bk = now.strftime("%Y")
    if from_iso and to_iso:
        try:
            dt = datetime.strptime(to_iso, "%Y-%m-%d")
            ngay_bk = dt.strftime("%d")
            thang_bk = dt.strftime("%m")
            nam_bk = dt.strftime("%Y")
        except:
            pass

    # 1. TIÊU ĐỀ
    elements.append(Paragraph("<b>BẢNG KÊ MUA HÀNG HÓA, DỊCH VỤ<br/>KHÔNG CÓ HÓA ĐƠN</b>", style_title))
    elements.append(Paragraph(f"(Ngày {ngay_bk} tháng {thang_bk} năm {nam_bk})", style_italic_center))
    elements.append(Spacer(1, 12))

    # 2. THÔNG TIN HỘ KINH DOANH
    phone_number = profile.get('phone', '') or '................................................'
    elements.append(Paragraph(f"- Tên hộ kinh doanh: {sanitize_text_for_pdf(profile.get('name', ''))}", style_normal))
    elements.append(Paragraph(f"- Mã số thuế: {sanitize_text_for_pdf(profile.get('tax_id', ''))}", style_normal))
    elements.append(Paragraph(f"- Địa chỉ: {sanitize_text_for_pdf(profile.get('address', ''))}", style_normal))
    elements.append(Paragraph(f"- Số điện thoại: {phone_number}", style_normal))
    elements.append(Paragraph(f"- Địa chỉ nơi tổ chức thu mua: ....................................................................................................", style_normal))
    elements.append(Spacer(1, 10))

    # 3. BẢNG DỮ LIỆU
    table_data = [
        # Dòng 1 Header
        [
            Paragraph("Ngày tháng năm mua hàng", style_header_cell),
            Paragraph("Người bán", style_header_cell), "", "", "",
            Paragraph("Hàng hóa, dịch vụ mua vào", style_header_cell), "", "", "",
            Paragraph("Ghi chú", style_header_cell)
        ],
        # Dòng 2 Header
        [
            "",
            Paragraph("Tên người bán", style_header_cell),
            Paragraph("Địa chỉ", style_header_cell),
            Paragraph("Số căn cước/Số định danh", style_header_cell),
            Paragraph("Số điện thoại (nếu có)", style_header_cell),
            Paragraph("Tên hàng hóa, dịch vụ", style_header_cell),
            Paragraph("Số lượng, trọng lượng", style_header_cell),
            Paragraph("Đơn giá", style_header_cell),
            Paragraph("Tổng giá thanh toán", style_header_cell),
            ""
        ],
        # Dòng 3 STT
        [
            Paragraph("1", style_small),
            Paragraph("2", style_small),
            Paragraph("3", style_small),
            Paragraph("4", style_small),
            Paragraph("5", style_small),
            Paragraph("6", style_small),
            Paragraph("7", style_small),
            Paragraph("8", style_small),
            Paragraph("9", style_small),
            Paragraph("10", style_small)
        ]
    ]

    tong_all = 0
    for r in data_rows:
        tong = clean_float(r.get('thanh_toan') or 0)
        tong_all += tong
        ngay_raw = r.get('ngay_mua') or ''
        ngay_vn = format_date_vn(ngay_raw)

        table_data.append([
            Paragraph(ngay_vn, style_center),
            Paragraph(sanitize_text_for_pdf(r.get('ten_nguoi_ban') or ''), style_normal),
            Paragraph(sanitize_text_for_pdf(r.get('dia_chi') or ''), style_normal),
            Paragraph(sanitize_text_for_pdf(r.get('cccd') or ''), style_center),
            Paragraph(sanitize_text_for_pdf(r.get('dien_thoai') or ''), style_center),
            Paragraph(sanitize_text_for_pdf(r.get('ten_hang_hoa') or ''), style_normal),
            Paragraph(f"{clean_float(r.get('so_luong') or 0):,.0f}", style_center),
            Paragraph(f"{clean_float(r.get('don_gia') or 0):,.0f}", style_center),
            Paragraph(f"{tong:,.0f}", style_center),
            Paragraph(sanitize_text_for_pdf(r.get('ghi_chu') or ''), style_normal),
        ])

    # Hàng tổng cộng trong Bảng
    table_data.append([
        Paragraph("<b>Tổng</b>", style_header_cell), "", "", "", "", "", "", "",
        Paragraph(f"<b>{tong_all:,.0f}</b>", style_header_cell),
        ""
    ])

    # Tổng chiều rộng trang A4 Landscape là ~842pt, trừ lề còn ~770pt
    col_widths = [60, 95, 110, 75, 65, 125, 55, 60, 75, 50]
    
    table = Table(table_data, colWidths=col_widths, repeatRows=3)
    
    table_style = [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        # Span cho Header
        ("SPAN", (0, 0), (0, 1)),  # Cột 1: Ngày tháng năm
        ("SPAN", (1, 0), (4, 0)),  # Cột 2-5: Người bán
        ("SPAN", (5, 0), (8, 0)),  # Cột 6-9: Hàng hóa dịch vụ
        ("SPAN", (9, 0), (9, 1)),  # Cột 10: Ghi chú
    ]
    
    # Merge dòng Tổng ở hàng cuối
    last_row_idx = len(table_data) - 1
    table_style.append(("SPAN", (0, last_row_idx), (7, last_row_idx)))

    table.setStyle(TableStyle(table_style))
    elements.append(table)
    elements.append(Spacer(1, 10))

    # 4. DÒNG TỔNG TIỀN VÀ HÌNH THỨC THANH TOÁN
    elements.append(Paragraph(f"- Tổng giá trị hàng hóa, dịch vụ mua vào: <b>{tong_all:,.0f}</b> (Số tiền bằng chữ: ........................................................................)", style_normal))
    elements.append(Paragraph("- Hình thức thanh toán: Tiền mặt / Chuyển khoản", style_normal))
    elements.append(Spacer(1, 15))

    # 5. CHỮ KÝ VÀ TÊN
    footer_data = [
        [
            "", 
            Paragraph(f"<i>Ngày {ngay_bk} tháng {thang_bk} năm {nam_bk}</i>", style_center)
        ],
        [
            Paragraph("<b>Người lập bảng kê</b><br/><br/><br/><i>(Ký, ghi rõ họ tên)</i>", style_center), 
            Paragraph("<b>Chủ hộ kinh doanh hoặc người chủ hộ<br/>kinh doanh ủy quyền</b><br/><br/><br/><i>(Ký tên, đóng dấu)</i>", style_center)
        ]
    ]
    
    ft_table = Table(footer_data, colWidths=[385, 385])
    ft_table.setStyle(TableStyle([
        ("ALIGN", (0,0), (-1,-1), "CENTER"), 
        ("VALIGN", (0,0), (-1,-1), "TOP")
    ]))
    
    elements.append(ft_table)

    # Xuất ra PDF
    doc.build(elements)
    buffer.seek(0)
    return send_file(
        buffer, 
        as_attachment=True, 
        download_name="BangKe_MuaHang_KhongHoaDon.pdf", 
        mimetype="application/pdf"
    )

#-------kết thúc phần bảng kê mua hàng----------------------------

###############------------------- phần đối soát -----------------------###############
"""
Routes Đối soát - Bản rút gọn theo yêu cầu mới
- Bỏ _ensure_doisoat_table() và ALTER is_reconciled / doisoat_date
- Flow:
  1. Upload Excel -> update cột success trong tonghopdon (Giao thành công, Đang vận chuyển, Đang hoàn...)
  2. Hoàn thành nhanh: lấy đơn success='Giao thành công' -> ghi vào doisoat (theo mẫu bạn gửi) -> xóa khỏi tonghopdon + chitietdon
  3. Duyệt thủ công: không quan tâm success, đưa luôn vào doisoat và xóa khỏi tonghopdon + chitietdon (đơn bán trực tiếp)
- Bảng doisoat đã có sẵn: order_id TEXT, nickname TEXT, username TEXT, tracking_number TEXT, revenue REAL, date TEXT, total_payment TEXT, shipping_cost TEXT
"""

import os
import re
import sqlite3
from datetime import datetime, date as date_cls
from flask import request, jsonify, render_template, session
from zoneinfo import ZoneInfo

try:
    VN_TZ
except NameError:
    VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

def _parse_date_flexible(s):
    if not s:
        return None
    s = str(s).strip()
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%m/%d/%Y', '%Y/%m/%d', '%d-%m-%y', '%Y-%m-%d %H:%M:%S', '%d/%m/%Y %H:%M:%S'):
        try:
            return datetime.strptime(s, fmt).date()
        except:
            continue
    return None

# --- 1. Render trang giao diện ---
@app.route("/doisoat")
def doisoat_page():
    try:
        if 'user_id' in session and session.get('role') and session.get('role') != 'QTV':
            return "Từ chối truy cập! Chỉ QTV được xem đối soát.", 403
        return render_template("doisoat.html")
    except Exception as e:
        print(f"doisoat_page error: {e}")
        try:
            return render_template("doisoat_new.html")
        except:
            return f"Lỗi render doisoat: {e}", 500

@app.route("/admin/doisoat")
def admin_doisoat_page():
    return doisoat_page()

# --- 2. Lấy danh sách đơn chờ đối soát ---
@app.route("/api/doisoat/pending", methods=["GET"])
def api_doisoat_pending():
    """
    Lấy tất cả đơn có status là Đã Đi Đơn (chỉ hiện các đơn này).
    Duyệt thủ công cho đơn lấy trực tiếp thì phần mềm trước đó 
    đã đưa nó về Đã Đi Đơn nên sẽ hiện trong bảng.
    """
    try:
        conn = get_donhang_db_safe()
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tonghopdon'")
        if not cur.fetchone():
            conn.close()
            return jsonify([])

        rows = cur.execute("""
            SELECT order_id, nickname, username,
                   COALESCE(total_price, 0) as total_price,
                   COALESCE(tracking_number, '') as tracking_number,
                   COALESCE(success, '') as success
            FROM tonghopdon
            WHERE TRIM(status) = 'Đã Đi Đơn'
            ORDER BY order_id DESC
            LIMIT 500
        """).fetchall()

        result = []
        for r in rows:
            result.append({
                "order_id": r["order_id"],
                "nickname": r["nickname"] or "",
                "username": r["username"] or "",
                "total_price": int(float(r["total_price"] or 0)),
                "tracking_number": r["tracking_number"] or "",
                "success": r["success"] or ""
            })
        conn.close()
        return jsonify(result)
    except Exception as e:
        print(f"api_doisoat_pending error: {e}")
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# --- 3. Tổng kết doanh thu - tính từ bảng doisoat (theo hàm mẫu calculate_revenue của bạn) ---
@app.route("/api/doisoat/summary", methods=["GET"])
def api_doisoat_summary():
    """
    Query: ?start=YYYY-MM-DD&end=YYYY-MM-DD
    Tính tổng từ bảng doisoat theo date (dd-mm-yyyy)
    Trả về: {revenue, total_payment, shipping_cost}
    """
    try:
        start_str = request.args.get('start', '').strip()
        end_str = request.args.get('end', '').strip()

        today = datetime.now(VN_TZ).date()
        if not start_str:
            start_date = date_cls(today.year, today.month, 1)
        else:
            start_date = _parse_date_flexible(start_str) or date_cls(today.year, today.month, 1)

        if not end_str:
            end_date = today
        else:
            end_date = _parse_date_flexible(end_str) or today

        conn = get_donhang_db_safe()
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='doisoat'")
        if not cur.fetchone():
            conn.close()
            return jsonify({"revenue": 0, "total_payment": 0, "shipping_cost": 0})

        cur.execute("SELECT revenue, total_payment, shipping_cost, date FROM doisoat")
        all_rows = cur.fetchall()
        conn.close()

        total_payment_sum = 0
        shipping_cost_sum = 0
        revenue_sum = 0

        for r in all_rows:
            date_str = r["date"] or ""
            try:
                date_obj = datetime.strptime(date_str, "%d-%m-%Y").date()
            except:
                date_obj = _parse_date_flexible(date_str)
                if not date_obj:
                    # Nếu không parse được ngày và có filter thì bỏ qua
                    if start_str or end_str:
                        continue
                    date_obj = today

            if date_obj < start_date or date_obj > end_date:
                continue

            revenue_sum += float(r["revenue"] or 0)
            total_payment_sum += float(r["total_payment"] or 0)
            shipping_cost_sum += float(r["shipping_cost"] or 0)

        return jsonify({
            "revenue": int(revenue_sum),
            "total_payment": int(total_payment_sum),
            "shipping_cost": int(shipping_cost_sum)
        })

    except Exception as e:
        print(f"api_doisoat_summary error: {e}")
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e), "revenue": 0, "total_payment": 0, "shipping_cost": 0}), 500

# --- 4. Duyệt đối soát - logic mới ---
@app.route("/api/doisoat/approve", methods=["POST"])
def api_doisoat_approve():
    """
    Logic mới:
    - single: Không quan tâm success, đưa luôn vào doisoat và xóa khỏi tonghopdon + chitietdon (dùng cho đơn bán trực tiếp)
    - all_success: Lấy đơn có success = 'Giao thành công' (phân biệt hoa thường, dấu) -> ghi vào doisoat -> xóa
    """
    try:
        data = request.get_json() or {}
        mode = data.get('mode', 'single')

        conn = get_donhang_db_safe()
        cur = conn.cursor()

        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tonghopdon'")
        if not cur.fetchone():
            conn.close()
            return jsonify({"error": "Không tìm thấy bảng tonghopdon"}), 400

        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='doisoat'")
        if not cur.fetchone():
            conn.close()
            return jsonify({"error": "Không tìm thấy bảng doisoat (bảng phải có sẵn)"}), 400

        from datetime import datetime as dt

        if mode == 'single':
            order_id = str(data.get('order_id', '')).strip()
            if not order_id:
                conn.close()
                return jsonify({"error": "Thiếu order_id"}), 400

            # Lấy thông tin đơn - như hàm mẫu complete_single_order
            cur.execute("SELECT order_id, nickname, username, total_price, total_payment, shipping_cost, tracking_number FROM tonghopdon WHERE order_id=?", (order_id,))
            row = cur.fetchone()
            if not row:
                conn.close()
                return jsonify({"error": f"Không tìm thấy đơn {order_id}"}), 404

            order_id_db, nickname, username, total_price, total_payment, shipping_cost, tracking_number = row["order_id"], row["nickname"], row["username"], row["total_price"], row["total_payment"], row["shipping_cost"], row["tracking_number"]

            revenue = max(0.0, float(total_price or 0.0))
            total_payment_val = max(0.0, float(total_payment or 0.0))
            shipping_cost_val = max(0.0, float(shipping_cost or 0.0))
            today = dt.now().strftime("%d-%m-%Y")

            # Lưu vào doisoat - đúng thứ tự bạn yêu cầu
            try:
                cur.execute("""
                    INSERT INTO doisoat (order_id, nickname, username, tracking_number, revenue, total_payment, shipping_cost, date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (order_id_db, nickname, username, tracking_number, revenue, total_payment_val, shipping_cost_val, today))
            except Exception as e:
                print(f"Insert doisoat single error, thử REPLACE: {e}")
                cur.execute("""
                    INSERT OR REPLACE INTO doisoat (order_id, nickname, username, tracking_number, revenue, total_payment, shipping_cost, date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (order_id_db, nickname, username, tracking_number, revenue, total_payment_val, shipping_cost_val, today))

            # Xóa khỏi bảng cũ
            cur.execute("DELETE FROM chitietdon WHERE order_id=?", (order_id_db,))
            cur.execute("DELETE FROM tonghopdon WHERE order_id=?", (order_id_db,))

            conn.commit()
            conn.close()
            return jsonify({"status": "success", "message": f"Đã duyệt đơn {order_id_db}, chuyển vào doisoat và xóa khỏi tonghopdon/chitietdon"})

        elif mode == 'all_success':
            # Lấy đơn có success = 'Giao thành công' - phân biệt hoa thường, dấu
            cur.execute("""
                SELECT order_id, nickname, username, total_price, total_payment, shipping_cost, tracking_number
                FROM tonghopdon
                WHERE success = 'Giao thành công'
            """)
            rows = cur.fetchall()

            today = dt.now().strftime("%d-%m-%Y")
            count = 0
            for r in rows:
                order_id_db, nickname, username, total_price, total_payment, shipping_cost, tracking_number = r["order_id"], r["nickname"], r["username"], r["total_price"], r["total_payment"], r["shipping_cost"], r["tracking_number"]
                revenue = max(0.0, float(total_price or 0.0))
                total_payment_val = max(0.0, float(total_payment or 0.0))
                shipping_cost_val = max(0.0, float(shipping_cost or 0.0))

                try:
                    cur.execute("""
                        INSERT INTO doisoat (order_id, nickname, username, tracking_number, revenue, total_payment, shipping_cost, date)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (order_id_db, nickname, username, tracking_number, revenue, total_payment_val, shipping_cost_val, today))
                except:
                    cur.execute("""
                        INSERT OR REPLACE INTO doisoat (order_id, nickname, username, tracking_number, revenue, total_payment, shipping_cost, date)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (order_id_db, nickname, username, tracking_number, revenue, total_payment_val, shipping_cost_val, today))

                cur.execute("DELETE FROM chitietdon WHERE order_id=?", (order_id_db,))
                cur.execute("DELETE FROM tonghopdon WHERE order_id=?", (order_id_db,))
                count += 1

            conn.commit()
            conn.close()
            return jsonify({"status": "success", "message": f"Đã duyệt {count} đơn Giao thành công", "count": count})

        else:
            conn.close()
            return jsonify({"error": "Mode không hợp lệ"}), 400

    except Exception as e:
        print(f"api_doisoat_approve error: {e}")
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# --- 5. Upload Excel đối soát - chỉ update success ---
@app.route("/api/doisoat/upload_status", methods=["POST"])
def api_doisoat_upload_status():
    """
    Flow mới:
    - Đọc Excel Viettel (có tiêu đề ở trên, header thật ở dòng có "Mã Vận Đơn" ở cột B, Trạng Thái ở cột AG)
    - Chỉ update cột success cho tonghopdon (Giao thành công, Đang vận chuyển, Đang hoàn...)
    - Không ghi vào doisoat ở bước này, chỉ cập nhật trạng thái
    """
    try:
        if 'file' not in request.files:
            return jsonify({"error": "Không tìm thấy file"}), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "Tên file trống"}), 400
        filename = file.filename.lower()
        if not (filename.endswith('.xlsx') or filename.endswith('.xls') or filename.endswith('.csv')):
            return jsonify({"error": "Chỉ hỗ trợ .xlsx, .xls, .csv"}), 400

        import tempfile, os, re
        tmp_path = os.path.join(tempfile.gettempdir(), file.filename)
        file.save(tmp_path)

        parsed_rows = []
        header_info = {}

        def norm(s):
            if s is None: return ''
            s = str(s).strip()
            if '.' in s and s.replace('.','',1).isdigit():
                s = s.split('.')[0]
            return s

        def clean_code(s):
            s = norm(s)
            if s.endswith('.0'): s = s[:-2]
            return re.sub(r'[^0-9]', '', s) or s

        # Đọc bằng openpyxl
        try:
            import openpyxl
            wb = openpyxl.load_workbook(tmp_path, read_only=True, data_only=True)
            ws = wb.active
            all_rows = list(ws.iter_rows(values_only=True))
            wb.close()

            header_idx = None
            order_col_idx = None
            status_col_idx = None

            for i, row in enumerate(all_rows[:70]):
                if not row: continue
                row_vals = [norm(c) for c in row]
                row_low = [v.lower() for v in row_vals]
                has_ma = any('mã vận đơn' in v or 'ma van don' in v for v in row_low)
                has_tt = any('trạng thái' in v or 'trang thai' in v for v in row_low)
                if has_ma:
                    if header_idx is None: header_idx = i
                    for idx, val in enumerate(row_vals):
                        lv = val.lower()
                        if ('mã vận đơn' in lv or 'ma van don' in lv) and order_col_idx is None:
                            order_col_idx = idx
                        if ('trạng thái' in lv or 'trang thai' in lv) and status_col_idx is None:
                            status_col_idx = idx
                    if has_ma and has_tt and order_col_idx is not None and status_col_idx is not None:
                        header_idx = i
                        break

            if order_col_idx is None: order_col_idx = 1  # B
            if status_col_idx is None: status_col_idx = 32  # AG
            # File mẫu 3 cột thì AG trống -> lấy cột C
            if status_col_idx == 32 and header_idx is not None and header_idx < len(all_rows):
                if len([c for c in all_rows[header_idx] if c]) <= 6:
                    status_col_idx = 2

            if header_idx is None: header_idx = -1
            header_info = {"header_idx": header_idx, "order_col_idx": order_col_idx, "status_col_idx": status_col_idx}

            start_row = header_idx + 1 if header_idx >=0 else 0
            for row in all_rows[start_row:]:
                if not row or len(row) <= order_col_idx: continue
                ma_van = norm(row[order_col_idx] if order_col_idx < len(row) else '')
                trang_thai = norm(row[status_col_idx] if status_col_idx < len(row) else '')
                if not trang_thai and len(row) > 2:
                    maybe = norm(row[2])
                    if maybe: trang_thai = maybe
                if not ma_van or 'mã vận đơn' in ma_van.lower() or ma_van.lower()=='stt' or len(clean_code(ma_van))<5:
                    continue
                parsed_rows.append((ma_van, trang_thai))
        except Exception as e:
            print(f"openpyxl error: {e}")
            import traceback; traceback.print_exc()

        if not parsed_rows:
            try: os.remove(tmp_path)
            except: pass
            return jsonify({"error": f"Không đọc được dữ liệu. Header: {header_info}", "header_info": header_info}), 400

        # Map tracking_number trong DB để khớp
        conn = get_donhang_db_safe()
        cur = conn.cursor()
        all_db = cur.execute("SELECT order_id, tracking_number FROM tonghopdon").fetchall()
        map_clean = {}
        map_raw = {}
        for r in all_db:
            tn = r["tracking_number"] or ""
            if tn:
                map_clean[clean_code(tn)] = r["order_id"]
                map_raw[tn.strip()] = r["order_id"]

        updated = 0
        not_found = []
        for ma_raw, tt in parsed_rows:
            ma_clean = clean_code(ma_raw)
            oid = map_raw.get(ma_raw.strip()) or map_clean.get(ma_clean)
            if not oid:
                row = cur.execute("SELECT order_id FROM tonghopdon WHERE tracking_number LIKE ? LIMIT 1", (f"%{ma_clean}%",)).fetchone()
                if row: oid = row["order_id"]
            if not oid:
                not_found.append(ma_raw)
                continue
            cur.execute("UPDATE tonghopdon SET success=? WHERE order_id=?", (tt, oid))
            updated += 1

        conn.commit()
        conn.close()
        try: os.remove(tmp_path)
        except: pass

        return jsonify({
            "status": "success",
            "message": f"Đã đọc {len(parsed_rows)} dòng (header dòng {header_info.get('header_idx')}, cột B->AG). Cập nhật {updated} đơn vào cột success.",
            "header_info": header_info,
            "updated": updated,
            "not_found": not_found[:30],
            "total_rows": len(parsed_rows)
        })

    except Exception as e:
        print(f"upload_status error: {e}")
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500

###############------------------- kết thúc phần đối soát -----------------------###############


###############------------------- phần ký gửi -----------------------###############
"""
ROUTE KÝ GỬI - VIẾT LẠI HOÀN TOÀN - GỘP 2 FILE THÀNH 1
Tương thích hệ thống cũ (uid + get_user_data_db) và mới (QTV + get_donhang_db_safe)
Bảng: kygui(id, order_id, nickname, username, price, kygui, pay, thoigian TEXT DD-MM-YYYY)
Logic cũ:
- Chờ: kygui != '' 
- Đã TT: pay != ''
- Thanh toán: pay=kygui, thoigian=dd-mm-yyyy, kygui=''
"""

import re
from datetime import datetime
from flask import request, redirect, url_for, flash, render_template, session
from zoneinfo import ZoneInfo

try:
    VN_TZ
except NameError:
    VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# --- Tương thích get_user_data_db cũ ---
try:
    get_donhang_db_safe
except NameError:
    def get_user_data_db(uid=None):
        try:
            return get_donhang_db_safe()
        except Exception as e:
            print(f"get_user_data_db fallback: {e}")
            return None

def _get_db():
    """Lấy DB cho cả 2 hệ thống"""
    if "uid" in session:
        try:
            db = get_user_data_db(session["uid"])
            if db:
                return db
        except Exception as e:
            print(f"_get_db uid error: {e}")
    try:
        return get_donhang_db_safe()
    except:
        return None

# --- Filter tiền tệ ---
def format_currency(value):
    try:
        return f"{float(value):,.0f}".replace(',', '.')
    except (ValueError, TypeError):
        return "0"

try:
    app.jinja_env.filters['vnd'] = format_currency
except:
    pass

@app.template_filter('vn_date')
def vn_date_filter(value):
    if not value:
        return ""
    d = _parse_vn_date(str(value))
    return d.strftime("%d/%m/%Y") if d else str(value)

def _parse_vn_date(s):
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except:
            continue
    m = re.search(r'(\d{1,2})[-/\.](\d{1,2})[-/\.](\d{2,4})', s)
    if m:
        try:
            d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if y < 100:
                y += 2000
            from datetime import date
            if d > 31:  # YYYY-MM-DD
                return date(d if d>1000 else y, mth, y if y<32 else d)
            return date(y, mth, d)
        except:
            pass
    return None

def _ensure_kygui_table():
    try:
        conn = get_donhang_db_safe()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kygui (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                nickname TEXT,
                username TEXT,
                price REAL,
                kygui TEXT,
                pay TEXT,
                thoigian TEXT
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"_ensure_kygui_table: {e}")

_ensure_kygui_table()

# ==================== ROUTE CHÍNH - GỘP 2 TAB ====================
@app.route('/kygui', methods=['GET'])
def kygui():
    # Check quyền
    if "uid" not in session and session.get('role') and session.get('role') != 'QTV':
        return "Từ chối truy cập!", 403
    if "uid" not in session and not session.get('role') and not session.get('user_id'):
        # Nếu chưa login ở hệ thống mới, cho qua để tránh lỗi khi test
        pass

    db = _get_db()
    if not db:
        flash("Không kết nối được CSDL!", "danger")
        return redirect("/")

    try:
        # Params chung
        active_tab = request.args.get('tab', request.args.get('active_tab', 'pending'))  # pending | history
        filter_kygui = request.args.get('filter_kygui', 'all')
        filter_pay = request.args.get('filter_pay', 'all')
        filter_date = request.args.get('filter_date', 'all')

        # ---- TAB 1: CHỜ THANH TOÁN (kygui != '') ----
        cur = db.execute("SELECT DISTINCT kygui FROM kygui WHERE kygui IS NOT NULL AND TRIM(kygui) != '' ORDER BY kygui")
        khach_hang_list_pending = [r['kygui'] for r in cur.fetchall()]

        if filter_kygui == 'all':
            pending_rows = db.execute("SELECT * FROM kygui WHERE kygui IS NOT NULL AND TRIM(kygui) != '' ORDER BY id DESC").fetchall()
        else:
            pending_rows = db.execute("SELECT * FROM kygui WHERE TRIM(kygui) = ?", (filter_kygui,)).fetchall()

        pending_rows = [dict(r) for r in pending_rows]
        total_price = sum(float(r['price']) for r in pending_rows if r['price'])
        commission = total_price * 0.3
        net = total_price * 0.7

        # ---- TAB 2: LỊCH SỬ (pay != '') ----
        cur2 = db.execute("SELECT DISTINCT pay FROM kygui WHERE pay IS NOT NULL AND TRIM(pay) != '' ORDER BY pay")
        khach_hang_list_history = [r['pay'] for r in cur2.fetchall()]

        cur3 = db.execute("SELECT DISTINCT thoigian FROM kygui WHERE thoigian IS NOT NULL AND TRIM(thoigian) != ''")
        ngay_raw = [r['thoigian'] for r in cur3.fetchall()]
        # Sort ngày mới nhất trước
        def sort_date_key(s):
            d = _parse_vn_date(s)
            return d or datetime.min.date()
        ngay_list = sorted(set([n for n in ngay_raw if n]), key=sort_date_key, reverse=True)

        # Query lịch sử có lọc
        query = "SELECT * FROM kygui WHERE pay IS NOT NULL AND TRIM(pay) != ''"
        params = []
        if filter_pay != 'all':
            query += " AND TRIM(pay) = ?"
            params.append(filter_pay)
        if filter_date != 'all':
            # filter_date có thể là YYYY-MM-DD từ input date hoặc DD-MM-YYYY cũ
            parsed = _parse_vn_date(filter_date)
            if parsed:
                ddmm = parsed.strftime("%d-%m-%Y")
                # So sánh cả 2 kiểu để tương thích
                query += " AND (TRIM(thoigian) = ? OR TRIM(thoigian) = ?)"
                params.extend([filter_date, ddmm])
            else:
                query += " AND TRIM(thoigian) = ?"
                params.append(filter_date)
        query += " ORDER BY id DESC"
        history_rows = db.execute(query, params).fetchall()
        history_rows = [dict(r) for r in history_rows]

        history_total = sum(float(r['price']) for r in history_rows if r['price'])
        history_commission = history_total * 0.3
        history_net = history_total * 0.7

        return render_template('kygui.html',
            # Tab pending
            rows=pending_rows,
            pending_orders=pending_rows,
            khach_hang_list=khach_hang_list_pending,
            khach_hang_list_pending=khach_hang_list_pending,
            selected_filter=filter_kygui,
            filter_kygui=filter_kygui,
            total_price=total_price,
            commission=commission,
            net=net,
            # Tab history
            history_rows=history_rows,
            history_orders=history_rows,
            khach_hang_list_history=khach_hang_list_history,
            ngay_list=ngay_list,
            filter_pay=filter_pay,
            filter_date=filter_date,
            history_total_price=history_total,
            history_total=history_total,
            history_commission=history_commission,
            history_net=history_net,
            total_price_history=history_total,
            # Chung
            active_tab=active_tab
        )
    except Exception as e:
        print(f"kygui error: {e}")
        import traceback; traceback.print_exc()
        flash(f"Lỗi tải ký gửi: {e}", "danger")
        return render_template('kygui.html', rows=[], pending_orders=[], khach_hang_list=[], khach_hang_list_pending=[], selected_filter='all', filter_kygui='all', total_price=0, commission=0, net=0, history_rows=[], history_orders=[], khach_hang_list_history=[], ngay_list=[], filter_pay='all', filter_date='all', history_total_price=0, history_total=0, history_commission=0, history_net=0, active_tab='pending')
    finally:
        try:
            db.close()
        except:
            pass

# Alias
@app.route('/admin/kygui')
def admin_kygui():
    return kygui()

@app.route('/kygui/history')
def kygui_history():
    # Giữ route cũ để không gãy link, nhưng redirect sang tab history của trang gộp
    args = request.args.to_dict()
    args['tab'] = 'history'
    return redirect(url_for('kygui', **args))

@app.route('/admin/kygui/history')
def admin_kygui_history():
    return kygui_history()

# --- Thêm mới ---
@app.route('/kygui/add', methods=['POST'])
def add_kygui():
    db = _get_db()
    if not db:
        flash("Không kết nối DB!", "danger")
        return redirect(url_for('kygui'))
    try:
        data = (
            request.form.get('order_id'),
            request.form.get('nickname'),
            request.form.get('username'),
            request.form.get('price'),
            request.form.get('kygui')
        )
        if not data[0] or not data[4]:
            flash("Thiếu mã đơn hoặc tên khách ký gửi!", "warning")
            return redirect(url_for('kygui'))
        db.execute("INSERT INTO kygui (order_id, nickname, username, price, kygui) VALUES (?, ?, ?, ?, ?)", data)
        db.commit()
        flash('Đã thêm đơn hàng ký gửi mới!', 'success')
    except Exception as e:
        print(f"add_kygui error: {e}")
        flash(f'Lỗi thêm: {e}', 'danger')
    finally:
        try:
            db.close()
        except:
            pass
    return redirect(url_for('kygui'))

# Alias cho template mới
app.view_functions['kygui_add'] = add_kygui

# --- Xóa ---
@app.route('/kygui/delete/<int:id>', methods=['POST'])
def delete_kygui(id):
    db = _get_db()
    if not db:
        return redirect(url_for('kygui'))
    try:
        db.execute("DELETE FROM kygui WHERE id = ?", (id,))
        db.commit()
        flash('Đã xóa đơn hàng!', 'success')
    except Exception as e:
        print(f"delete_kygui error: {e}")
        flash('Lỗi xóa!', 'danger')
    finally:
        try:
            db.close()
        except:
            pass
    return redirect(url_for('kygui'))

# --- Thanh toán ---
@app.route('/kygui/pay', methods=['POST'])
def process_payment():
    khach_hang = request.form.get('khach_hang')
    if not khach_hang or khach_hang == 'all':
        flash('Vui lòng chọn một khách hàng cụ thể để thanh toán!', 'warning')
        return redirect(url_for('kygui'))

    db = _get_db()
    if not db:
        return redirect(url_for('kygui'))

    try:
        now = datetime.now(VN_TZ).strftime("%d-%m-%Y")
        db.execute("""
            UPDATE kygui 
            SET pay = kygui, thoigian = ?, kygui = '' 
            WHERE TRIM(kygui) = ?
        """, (now, khach_hang))
        db.commit()
        flash(f'Đã thanh toán thành công cho khách hàng: {khach_hang}', 'success')
    except Exception as e:
        print(f"process_payment error: {e}")
        flash('Lỗi thanh toán!', 'danger')
    finally:
        try:
            db.close()
        except:
            pass
    return redirect(url_for('kygui', tab='history', filter_pay=khach_hang))

@app.route('/kygui/process_payment', methods=['POST'])
def kygui_process_payment():
    return process_payment()

###############------------------- kết thúc phần ký gửi -----------------------###############

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8000, debug=True)
