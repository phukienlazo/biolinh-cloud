
import os, sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash

app = Flask(__name__)
app.secret_key = "biolinh_secret_2026"
TOKEN = "biolinh2hand_2026"
DONHANG_DB = "khachhang.db"
CHAMCONG_DB = "chamcong.db"

def get_donhang_db():
    conn = sqlite3.connect(DONHANG_DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_chamcong():
    conn = sqlite3.connect(CHAMCONG_DB)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        hovaten TEXT,
        chucdanh TEXT DEFAULT 'Nhân Viên',
        luong REAL DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER,
        date TEXT,
        session_type TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS phatsinh (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER,
        amount REAL,
        note TEXT,
        date TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS salary_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER,
        amount REAL,
        date TEXT,
        note TEXT
    )""")
    c.execute("SELECT COUNT(*) FROM employees WHERE username='admin'")
    if c.fetchone()[0]==0:
        c.execute("INSERT INTO employees (username,password,hovaten,chucdanh,luong) VALUES (?,?,?,?,?)",
                  ("admin","123456","Admin Biolinh","QTV",10000000))
    conn.commit(); conn.close()

init_chamcong()

def get_chamcong_db():
    conn = sqlite3.connect(CHAMCONG_DB)
    conn.row_factory = sqlite3.Row
    return conn

def calc_employee_stats(emp_id):
    conn = get_chamcong_db()
    emp = conn.execute("SELECT * FROM employees WHERE id=?",(emp_id,)).fetchone()
    if not emp:
        conn.close(); return None
    cnt = conn.execute("SELECT COUNT(*) FROM attendance WHERE employee_id=?",(emp_id,)).fetchone()[0]
    tong_cong = round(cnt/2,1)
    luong = emp["luong"] or 0
    thu_nhap_uoc_tinh = round(luong/26 * tong_cong,0) if luong else 0
    phat = conn.execute("SELECT COALESCE(SUM(amount),0) FROM phatsinh WHERE employee_id=?",(emp_id,)).fetchone()[0]
    thuc_nhan = thu_nhap_uoc_tinh + (phat or 0)
    result = {
        "id": emp["id"],
        "username": emp["username"],
        "hovaten": emp["hovaten"],
        "chucdanh": emp["chucdanh"],
        "luong": luong,
        "tong_cong": tong_cong,
        "thu_nhap_uoc_tinh": thu_nhap_uoc_tinh,
        "tong_phat_sinh": phat or 0,
        "thuc_nhan": thuc_nhan
    }
    conn.close()
    return result

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

@app.route("/chamcong")
def chamcong_root():
    if "user_id" not in session:
        return redirect(url_for('login'))
    if session.get("chucdanh")=="QTV":
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('employee_dashboard_page'))

@app.route("/login", methods=["GET","POST"])
@app.route("/chamcong/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        u=request.form["username"]; p=request.form["password"]
        conn=get_chamcong_db()
        user=conn.execute("SELECT * FROM employees WHERE username=? AND password=?",(u,p)).fetchone()
        conn.close()
        if user:
            session["user_id"]=user["id"]; session["username"]=user["username"]
            session["hovaten"]=user["hovaten"]; session["chucdanh"]=user["chucdanh"]
            flash("Đăng nhập thành công","success")
            if user["chucdanh"]=="QTV":
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('employee_dashboard_page'))
        else:
            flash("Sai tài khoản hoặc mật khẩu","danger")
    return render_template("login.html")

@app.route("/logout")
@app.route("/chamcong/logout")
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route("/employee_dashboard")
@app.route("/chamcong/employee")
def employee_dashboard_page():
    if "user_id" not in session:
        return redirect(url_for('login'))
    emp = calc_employee_stats(session["user_id"])
    today=datetime.now().strftime("%Y-%m-%d")
    conn=get_chamcong_db()
    sang = conn.execute("SELECT * FROM attendance WHERE employee_id=? AND date=? AND session_type='sang'",(emp["id"],today)).fetchone()
    chieu = conn.execute("SELECT * FROM attendance WHERE employee_id=? AND date=? AND session_type='chieu'",(emp["id"],today)).fetchone()
    conn.close()
    return render_template("employee_dashboard.html", emp=emp, session=session,
                           sang_available=sang is None, chieu_available=chieu is None)

@app.route("/employee_checkin", methods=["POST"])
@app.route("/chamcong/checkin", methods=["POST"])
def employee_checkin():
    if "user_id" not in session:
        return redirect(url_for('login'))
    session_type=request.form.get("session_type","sang")
    today=datetime.now().strftime("%Y-%m-%d")
    conn=get_chamcong_db()
    exists=conn.execute("SELECT * FROM attendance WHERE employee_id=? AND date=? AND session_type=?",
                        (session["user_id"],today,session_type)).fetchone()
    if not exists:
        conn.execute("INSERT INTO attendance (employee_id,date,session_type) VALUES (?,?,?)",
                     (session["user_id"],today,session_type))
        conn.commit()
        flash(f"Chấm công ca {session_type} thành công","success")
    else:
        flash(f"Đã chấm ca {session_type} rồi","warning")
    conn.close()
    return redirect(url_for('employee_dashboard_page'))

@app.route("/admin_dashboard")
@app.route("/chamcong/admin")
def admin_dashboard():
    if session.get("chucdanh")!="QTV":
        flash("Không có quyền","danger")
        return redirect(url_for('login'))
    conn=get_chamcong_db()
    emps_raw=conn.execute("SELECT * FROM employees ORDER BY id").fetchall()
    conn.close()
    employees=[]
    for e in emps_raw:
        employees.append(calc_employee_stats(e["id"]))
    return render_template("admin_dashboard.html", employees=employees, session=session)

@app.route("/add_employee", methods=["POST"])
@app.route("/chamcong/add_employee", methods=["POST"])
def add_employee():
    if session.get("chucdanh")!="QTV":
        return redirect(url_for('login'))
    username=request.form["username"]; password=request.form["password"]
    hovaten=request.form["hovaten"]; chucdanh=request.form["chucdanh"]; luong=float(request.form["luong"] or 0)
    conn=get_chamcong_db()
    try:
        conn.execute("INSERT INTO employees (username,password,hovaten,chucdanh,luong) VALUES (?,?,?,?,?)",
                     (username,password,hovaten,chucdanh,luong))
        conn.commit()
        flash("Thêm nhân viên thành công","success")
    except Exception as ex:
        flash(f"Lỗi: {ex}","danger")
    conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route("/edit_employee/<int:emp_id>", methods=["GET","POST"])
@app.route("/chamcong/edit/<int:emp_id>", methods=["GET","POST"])
def edit_employee(emp_id):
    if session.get("chucdanh")!="QTV":
        return redirect(url_for('login'))
    conn=get_chamcong_db()
    if request.method=="POST":
        hovaten=request.form.get("hovaten"); chucdanh=request.form.get("chucdanh")
        luong=float(request.form.get("luong") or 0); password=request.form.get("password")
        if password:
            conn.execute("UPDATE employees SET hovaten=?,chucdanh=?,luong=?,password=? WHERE id=?",
                         (hovaten,chucdanh,luong,password,emp_id))
        else:
            conn.execute("UPDATE employees SET hovaten=?,chucdanh=?,luong=? WHERE id=?",
                         (hovaten,chucdanh,luong,emp_id))
        if "phatsinh_amount" in request.form:
            try:
                amt=float(request.form["phatsinh_amount"] or 0)
                note=request.form.get("phatsinh_note","")
                if amt!=0:
                    conn.execute("INSERT INTO phatsinh (employee_id,amount,note,date) VALUES (?,?,?,?)",
                                 (emp_id,amt,note,datetime.now().strftime("%Y-%m-%d")))
            except: pass
        conn.commit()
        flash("Cập nhật thành công","success")
    emp_raw=conn.execute("SELECT * FROM employees WHERE id=?",(emp_id,)).fetchone()
    stat=calc_employee_stats(emp_id)
    logs=conn.execute("SELECT * FROM attendance WHERE employee_id=? ORDER BY date DESC",(emp_id,)).fetchall()
    phats=conn.execute("SELECT * FROM phatsinh WHERE employee_id=? ORDER BY date DESC",(emp_id,)).fetchall()
    conn.close()
    emp_dict=dict(emp_raw)
    emp_dict.update(stat)
    return render_template("edit_employee.html", emp=emp_dict, logs=logs, phatsinh=phats)

@app.route("/delete_employee/<int:emp_id>")
@app.route("/chamcong/delete/<int:emp_id>")
def delete_employee(emp_id):
    if session.get("chucdanh")!="QTV":
        return redirect(url_for('login'))
    conn=get_chamcong_db()
    conn.execute("DELETE FROM employees WHERE id=?",(emp_id,))
    conn.execute("DELETE FROM attendance WHERE employee_id=?",(emp_id,))
    conn.commit(); conn.close()
    flash("Đã xóa","warning")
    return redirect(url_for('admin_dashboard'))

@app.route("/attendance_log/<int:emp_id>", methods=["GET","POST"])
@app.route("/chamcong/log/<int:emp_id>", methods=["GET","POST"])
def attendance_log(emp_id):
    if session.get("chucdanh")!="QTV":
        return redirect(url_for('login'))
    conn=get_chamcong_db()
    if request.method=="POST" and "add_attendance" in request.form:
        date=request.form["date"]; sess=request.form["session"]
        conn.execute("INSERT INTO attendance (employee_id,date,session_type) VALUES (?,?,?)",(emp_id,date,sess))
        conn.commit()
        flash("Đã thêm công","success")
    emp=calc_employee_stats(emp_id)
    logs=conn.execute("SELECT * FROM attendance WHERE employee_id=? ORDER BY date DESC",(emp_id,)).fetchall()
    conn.close()
    return render_template("attendance_log.html", emp=emp, logs=logs)

@app.route("/pay_salary/<int:emp_id>", methods=["POST"])
@app.route("/chamcong/pay_salary/<int:emp_id>", methods=["POST"])
def pay_salary(emp_id):
    if session.get("chucdanh")!="QTV":
        return redirect(url_for('login'))
    conn=get_chamcong_db()
    stat=calc_employee_stats(emp_id)
    if stat:
        conn.execute("INSERT INTO salary_history (employee_id,amount,date,note) VALUES (?,?,?,?)",
                     (emp_id,stat["thuc_nhan"],datetime.now().strftime("%Y-%m-%d"),f"Thanh toán {stat['tong_cong']} công"))
        conn.execute("DELETE FROM attendance WHERE employee_id=?",(emp_id,))
        conn.execute("DELETE FROM phatsinh WHERE employee_id=?",(emp_id,))
        conn.commit()
        flash(f"Đã thanh toán {stat['thuc_nhan']:,.0f} VNĐ","success")
    conn.close()
    return redirect(url_for('attendance_log', emp_id=emp_id))

@app.route("/delete_attendance/<int:log_id>")
def delete_attendance(log_id):
    if session.get("chucdanh")!="QTV":
        return redirect(url_for('login'))
    conn=get_chamcong_db()
    conn.execute("DELETE FROM attendance WHERE id=?",(log_id,))
    conn.commit(); conn.close()
    return redirect(request.referrer or url_for('admin_dashboard'))

@app.route("/sync/<ten_db>", methods=["POST"])
def sync_db(ten_db):
    if request.headers.get("X-TOKEN") != TOKEN:
        return "Sai token",403
    if ten_db not in ["khachhang.db","chamcong.db"]:
        return "Ten file khong hop le",400
    tmp=ten_db+".tmp"
    request.files['file'].save(tmp)
    os.replace(tmp, ten_db)
    if ten_db=="chamcong.db":
        init_chamcong()
    return f"OK {ten_db}"

@app.route("/health")
def health():
    return "OK"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
