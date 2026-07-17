
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

app = Flask(__name__)
app.secret_key = 'super_secret_key_attendance_system'
TOKEN = "biolinh2hand_2026"
DONHANG_DB = 'khachhang.db'
DATABASE = 'nv.db'

def get_donhang_db():
    conn = sqlite3.connect(DONHANG_DB)
    conn.row_factory = sqlite3.Row
    return conn

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    if not os.path.exists(DATABASE):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS nv (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                hovaten TEXT NOT NULL,
                chucdanh TEXT NOT NULL,
                luong REAL NOT NULL DEFAULT 0
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                session TEXT NOT NULL,
                FOREIGN KEY(employee_id) REFERENCES nv(id) ON DELETE CASCADE,
                UNIQUE(employee_id, date, session)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chi_tiet_phat_sinh (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                noidung TEXT NOT NULL,
                sotien REAL NOT NULL,
                loai TEXT NOT NULL,
                FOREIGN KEY(employee_id) REFERENCES nv(id) ON DELETE CASCADE
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payment_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                payment_date TEXT NOT NULL,
                luong_co_ban REAL NOT NULL,
                tong_cong REAL NOT NULL,
                thu_nhap_tinh REAL NOT NULL,
                tong_phat_sinh REAL NOT NULL,
                thuc_nhan REAL NOT NULL,
                FOREIGN KEY(employee_id) REFERENCES nv(id) ON DELETE CASCADE
            )
        ''')
        cursor.execute("SELECT * FROM nv WHERE username = 'admin'")
        if not cursor.fetchone():
            cursor.execute("INSERT INTO nv (username, password, hovaten, chucdanh, luong) VALUES ('admin', 'admin123', 'Người Quản Lý', 'QTV', 0)")
        conn.commit()
        conn.close()

init_db()

def calculate_salary_details(emp, conn):
    emp_id = emp['id']
    luong_thang = emp['luong']
    luong_ngay = luong_thang / 26.0
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM attendance WHERE employee_id = ?", (emp_id,))
    total_sessions = cur.fetchone()[0]
    tong_cong = total_sessions / 2.0
    thu_nhap_uoc_tinh = tong_cong * luong_ngay
    cur.execute("SELECT sotien, loai FROM chi_tiet_phat_sinh WHERE employee_id = ?", (emp_id,))
    phat_sinh_list = cur.fetchall()
    tong_phat_sinh = 0.0
    for ps in phat_sinh_list:
        if ps['loai'] == 'tang':
            tong_phat_sinh += ps['sotien']
        elif ps['loai'] == 'giam':
            tong_phat_sinh -= ps['sotien']
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

# HOME - TRANG CHỦ MỚI THEO YÊU CẦU
@app.route("/")
def home():
    tong=0
    if os.path.exists(DONHANG_DB):
        try:
            conn=get_donhang_db()
            tong=conn.execute("SELECT COUNT(*) FROM tonghopdon").fetchone()[0]
            conn.close()
        except: pass
    return render_template("home.html", tong_don=tong)

@app.route("/donhang")
def donhang():
    if not os.path.exists(DONHANG_DB):
        return "<h3>Chua co khachhang.db</h3><a href='/'>Ve trang chu</a>"
    conn=get_donhang_db()
    rows=conn.execute("SELECT order_id,nickname,username FROM tonghopdon ORDER BY order_id DESC LIMIT 500").fetchall()
    conn.close()
    data=[(r["order_id"],r["nickname"],r["username"]) for r in rows]
    return render_template("donhang.html", data=data)

@app.route("/order-details/<path:order_id>")
def order_details(order_id):
    conn=get_donhang_db()
    order=conn.execute("SELECT * FROM tonghopdon WHERE order_id=?",(order_id,)).fetchone()
    if not order:
        conn.close(); return jsonify({"error":"not found"}),404
    details=conn.execute("SELECT price FROM chitietdon WHERE order_id=? ORDER BY id",(order_id,)).fetchall()
    prices=[[str(d["price"])] for d in details] or [[str(order["total_price"] or 0)]]
    result={"order_id":order["order_id"],"nickname":order["nickname"],"username":order["username"],
            "total_items":len(prices),"total_price":str(order["total_price"] or 0),"prices":prices}
    conn.close()
    return jsonify(result)

# CHAM CONG - GIỮ NGUYÊN 100%
@app.route("/chamcong")
def chamcong_index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if session.get('role') == 'QTV':
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('employee_dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM nv WHERE username = ? AND password = ?", (username, password))
        user = cur.fetchone()
        conn.close()
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['hovaten'] = user['hovaten']
            session['role'] = user['chucdanh']
            flash('Đăng nhập thành công!', 'success')
            return redirect(url_for('chamcong_index'))
        else:
            flash('Tên đăng nhập hoặc mật khẩu không đúng.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Đã đăng xuất tài khoản.', 'info')
    return redirect(url_for('login'))

@app.route('/admin')
def admin_dashboard():
    if session.get('role') != 'QTV':
        return "Từ chối truy cập!", 403
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM nv WHERE chucdanh != 'QTV'")
    employees = cur.fetchall()
    emp_list = []
    for emp in employees:
        details = calculate_salary_details(emp, conn)
        emp_list.append(details)
    conn.close()
    return render_template('admin_dashboard.html', employees=emp_list)

@app.route('/admin/add_employee', methods=['POST'])
def add_employee():
    if session.get('role') != 'QTV':
         return "Từ chối truy cập!", 403
    username = request.form['username'].strip()
    password = request.form['password'].strip()
    hovaten = request.form['hovaten'].strip()
    chucdanh = request.form['chucdanh']
    luong = float(request.form['luong'] or 0)
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute('INSERT INTO nv (username, password, hovaten, chucdanh, luong) VALUES (?, ?, ?, ?, ?)', (username, password, hovaten, chucdanh, luong))
        conn.commit()
        flash('Thêm nhân viên mới thành công!', 'success')
    except sqlite3.IntegrityError:
        flash('Tên đăng nhập đã tồn tại!', 'danger')
    finally:
        conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/edit_employee/<int:emp_id>', methods=['GET', 'POST'])
def edit_employee(emp_id):
    if session.get('role') != 'QTV':
         return "Từ chối truy cập!", 403
    conn = get_db()
    cur = conn.cursor()
    if request.method == 'POST':
        hovaten = request.form['hovaten'].strip()
        chucdanh = request.form['chucdanh']
        luong = float(request.form['luong'] or 0)
        password = request.form['password'].strip()
        if password:
            cur.execute('UPDATE nv SET hovaten=?, chucdanh=?, luong=?, password=? WHERE id=?', (hovaten, chucdanh, luong, password, emp_id))
        else:
            cur.execute('UPDATE nv SET hovaten=?, chucdanh=?, luong=? WHERE id=?', (hovaten, chucdanh, luong, emp_id))
        conn.commit()
        flash('Cập nhật thông tin nhân viên thành công!', 'success')
        conn.close()
        return redirect(url_for('admin_dashboard'))
    cur.execute("SELECT * FROM nv WHERE id = ?", (emp_id,))
    emp = cur.fetchone()
    cur.execute("SELECT * FROM chi_tiet_phat_sinh WHERE employee_id = ? ORDER BY date DESC", (emp_id,))
    phat_sinh = cur.fetchall()
    details = calculate_salary_details(emp, conn)
    conn.close()
    return render_template('edit_employee.html', emp=details, phat_sinh=phat_sinh)

@app.route('/admin/delete_employee/<int:emp_id>')
def delete_employee(emp_id):
    if session.get('role') != 'QTV':
         return "Từ chối truy cập!", 403
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM nv WHERE id = ?", (emp_id,))
    conn.commit()
    conn.close()
    flash('Đã xóa nhân viên khỏi hệ thống.', 'warning')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/add_phat_sinh/<int:emp_id>', methods=['POST'])
def add_phat_sinh(emp_id):
    if session.get('role') != 'QTV':
         return "Từ chối truy cập!", 403
    date = request.form['date']
    noidung = request.form['noidung'].strip()
    sotien = float(request.form['sotien'] or 0)
    loai = request.form['loai']
    conn = get_db()
    cur = conn.cursor()
    cur.execute('INSERT INTO chi_tiet_phat_sinh (employee_id, date, noidung, sotien, loai) VALUES (?, ?, ?, ?, ?)', (emp_id, date, noidung, sotien, loai))
    conn.commit()
    conn.close()
    flash('Thêm khoản phát sinh thành công!', 'success')
    return redirect(url_for('edit_employee', emp_id=emp_id))

@app.route('/admin/delete_phat_sinh/<int:ps_id>/<int:emp_id>')
def delete_phat_sinh(ps_id, emp_id):
    if session.get('role') != 'QTV':
         return "Từ chối truy cập!", 403
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM chi_tiet_phat_sinh WHERE id = ?", (ps_id,))
    conn.commit()
    conn.close()
    flash('Đã xóa khoản phát sinh.', 'info')
    return redirect(url_for('edit_employee', emp_id=emp_id))

@app.route('/admin/attendance_log/<int:emp_id>', methods=['GET', 'POST'])
def attendance_log(emp_id):
    if session.get('role') != 'QTV':
         return "Từ chối truy cập!", 403
    conn = get_db()
    cur = conn.cursor()
    if request.method == 'POST' and 'add_attendance' in request.form:
        date = request.form['date']
        session_type = request.form['session']
        try:
            cur.execute("INSERT INTO attendance (employee_id, date, session) VALUES (?, ?, ?)", (emp_id, date, session_type))
            conn.commit()
            flash('Thêm công mới thành công!', 'success')
        except sqlite3.IntegrityError:
            flash('Ca làm việc này vào ngày đã chọn đã được ghi nhận!', 'danger')
    cur.execute("SELECT * FROM nv WHERE id = ?", (emp_id,))
    emp = cur.fetchone()
    cur.execute("SELECT * FROM attendance WHERE employee_id = ? ORDER BY date DESC, session DESC", (emp_id,))
    logs = cur.fetchall()
    details = calculate_salary_details(emp, conn)
    conn.close()
    return render_template('attendance_log.html', emp=details, logs=logs)

@app.route('/admin/delete_attendance/<int:att_id>/<int:emp_id>')
def delete_attendance(att_id, emp_id):
    if session.get('role') != 'QTV':
         return "Từ chối truy cập!", 403
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM attendance WHERE id = ?", (att_id,))
    conn.commit()
    conn.close()
    flash('Đã xóa chấm công đã chọn.', 'warning')
    return redirect(url_for('attendance_log', emp_id=emp_id))

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
    details = calculate_salary_details(emp, conn)
    today = datetime.now(VN_TZ).strftime('%Y-%m-%d %H:%M:%S')
    cur.execute('INSERT INTO payment_history (employee_id, payment_date, luong_co_ban, tong_cong, thu_nhap_tinh, tong_phat_sinh, thuc_nhan) VALUES (?, ?, ?, ?, ?, ?, ?)', (emp_id, today, details['luong'], details['tong_cong'], details['thu_nhap_uoc_tinh'], details['tong_phat_sinh'], details['thuc_nhan']))
    cur.execute("DELETE FROM attendance WHERE employee_id = ?", (emp_id,))
    cur.execute("DELETE FROM chi_tiet_phat_sinh WHERE employee_id = ?", (emp_id,))
    conn.commit()
    conn.close()
    flash(f"Thanh toán lương thành công cho nhân viên {emp['hovaten']}. Hệ thống đã reset chu kỳ chấm công.", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/employee')
def employee_dashboard():
    if 'user_id' not in session or session.get('role') == 'QTV':
        return redirect(url_for('login'))
    emp_id = session['user_id']
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM nv WHERE id = ?", (emp_id,))
    emp = cur.fetchone()
    details = calculate_salary_details(emp, conn)
    cur.execute("SELECT * FROM chi_tiet_phat_sinh WHERE employee_id = ? ORDER BY date DESC", (emp_id,))
    phat_sinh = cur.fetchall()
    cur.execute("SELECT * FROM attendance WHERE employee_id = ? ORDER BY date DESC, session DESC", (emp_id,))
    attendance_history = cur.fetchall()
    conn.close()
    now = datetime.now(VN_TZ)
    current_time = now.strftime('%H:%M')
    today_str = now.strftime('%Y-%m-%d')
    sang_available = "07:30" <= current_time <= "11:30"
    chieu_available = "13:30" <= current_time <= "17:30"
    return render_template('employee_dashboard.html', emp=details, phat_sinh=phat_sinh, history=attendance_history, sang_available=sang_available, chieu_available=chieu_available)

@app.route('/employee/checkin', methods=['POST'])
def employee_checkin():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    emp_id = session['user_id']
    session_type = request.form['session_type']
    now = datetime.now(VN_TZ)
    current_time = now.strftime('%H:%M')
    today_str = now.strftime('%Y-%m-%d')
    if session_type == 'sang' and not ("07:30" <= current_time <= "11:30"):
        flash("Ngoài khung giờ chấm công Ca Sáng (07:30 - 11:30)!", "danger")
        return redirect(url_for('employee_dashboard'))
    elif session_type == 'chieu' and not ("13:30" <= current_time <= "17:30"):
        flash("Ngoài khung giờ chấm công Ca Chiều (13:30 - 17:30)!", "danger")
        return redirect(url_for('employee_dashboard'))
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO attendance (employee_id, date, session) VALUES (?, ?, ?)", (emp_id, today_str, session_type))
        conn.commit()
        flash(f"Điểm danh thành công Ca {session_type.capitalize()} ngày {today_str}!", "success")
    except sqlite3.IntegrityError:
        flash(f"Bạn đã chấm công Ca {session_type.capitalize()} cho ngày hôm nay rồi!", "warning")
    finally:
        conn.close()
    return redirect(url_for('employee_dashboard'))

@app.route("/sync/<ten_db>", methods=["POST"])
def sync_db(ten_db):
    if request.headers.get("X-TOKEN") != TOKEN:
        return "Sai token",403
    if ten_db not in ["khachhang.db","nv.db"]:
        return "Ten file khong hop le",400
    tmp=ten_db+".tmp"
    request.files['file'].save(tmp)
    os.replace(tmp, ten_db)
    if ten_db=="nv.db":
        init_db()
    return f"OK {ten_db}"

@app.route("/health")
def health():
    return "OK"

if __name__ == '__main__':
    init_db()
    app.run(host="0.0.0.0", port=8000)
