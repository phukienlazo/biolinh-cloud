
import os, sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, render_template, redirect, url_for, session

app = Flask(__name__)
app.secret_key = "biolinh_secret_2026"
TOKEN = "biolinh2hand_2026"
DONHANG_DB = "khachhang.db"

def get_donhang_db():
    conn = sqlite3.connect(DONHANG_DB)
    conn.row_factory = sqlite3.Row
    return conn

# ---- DB CHAM CONG ----
CHAMCONG_DB = "chamcong.db"
def init_chamcong():
    conn = sqlite3.connect(CHAMCONG_DB)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, username TEXT UNIQUE, password TEXT, role TEXT DEFAULT 'employee'
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER,
        date TEXT,
        check_in TEXT,
        check_out TEXT,
        work_hours REAL,
        FOREIGN KEY(employee_id) REFERENCES employees(id)
    )""")
    # tạo admin mặc định nếu chưa có
    c.execute("SELECT COUNT(*) FROM employees WHERE username='admin'")
    if c.fetchone()[0]==0:
        c.execute("INSERT INTO employees (name, username, password, role) VALUES (?,?,?,?)",
                  ("Admin Biolinh","admin","123456","admin"))
    conn.commit()
    conn.close()

init_chamcong()

def get_chamcong_db():
    conn = sqlite3.connect(CHAMCONG_DB)
    conn.row_factory = sqlite3.Row
    return conn

# ===== TRANG CHỦ MỚI =====
@app.route("/")
def home():
    tong = 0
    if os.path.exists(DONHANG_DB):
        try:
            conn = get_donhang_db()
            tong = conn.execute("SELECT COUNT(*) FROM tonghopdon").fetchone()[0]
            conn.close()
        except: pass
    return render_template("home.html", tong_don=tong)

# ===== DON HANG (GIỮ NGUYÊN) =====
@app.route("/donhang")
def donhang():
    if not os.path.exists(DONHANG_DB):
        return "<h3>Chua co khachhang.db. Hay chay auto_sync.py</h3><p><a href='/'>Ve trang chu</a></p>"
    conn = get_donhang_db()
    rows = conn.execute("SELECT order_id, nickname, username FROM tonghopdon ORDER BY order_id DESC LIMIT 500").fetchall()
    conn.close()
    data = [(r["order_id"], r["nickname"], r["username"]) for r in rows]
    return render_template("donhang.html", data=data)

@app.route("/order-details/<path:order_id>")
def order_details(order_id):
    conn = get_donhang_db()
    order = conn.execute("SELECT * FROM tonghopdon WHERE order_id = ?", (order_id,)).fetchone()
    if not order:
        conn.close()
        return jsonify({"error":"not found"}),404
    details = conn.execute("SELECT price FROM chitietdon WHERE order_id = ? ORDER BY id", (order_id,)).fetchall()
    prices = [[str(d["price"])] for d in details]
    if not prices:
        prices = [[str(order["total_price"] or 0)]]
    result = {"order_id":order["order_id"],"nickname":order["nickname"],"username":order["username"],
              "total_items":len(prices),"total_price":str(order["total_price"] or 0),"prices":prices}
    conn.close()
    return jsonify(result)

# ===== CHAM CONG =====
@app.route("/chamcong")
def chamcong_root():
    if "user_id" not in session:
        return redirect("/chamcong/login")
    if session.get("role")=="admin":
        return redirect("/chamcong/admin")
    else:
        return redirect("/chamcong/employee")

@app.route("/chamcong/login", methods=["GET","POST"])
def chamcong_login():
    error=None
    if request.method=="POST":
        u=request.form["username"]; p=request.form["password"]
        conn=get_chamcong_db()
        user=conn.execute("SELECT * FROM employees WHERE username=? AND password=?",(u,p)).fetchone()
        conn.close()
        if user:
            session["user_id"]=user["id"]; session["username"]=user["username"]; session["role"]=user["role"]; session["name"]=user["name"]
            if user["role"]=="admin":
                return redirect("/chamcong/admin")
            else:
                return redirect("/chamcong/employee")
        else:
            error="Sai tài khoản hoặc mật khẩu"
    return render_template("login.html", error=error)

@app.route("/chamcong/logout")
def chamcong_logout():
    session.clear()
    return redirect("/chamcong/login")

@app.route("/chamcong/employee", methods=["GET"])
def employee_dashboard():
    if "user_id" not in session:
        return redirect("/chamcong/login")
    msg=request.args.get("msg")
    now=datetime.now().strftime("%d/%m/%Y %H:%M")
    return render_template("employee_dashboard.html", user=session, now=now, msg=msg)

@app.route("/chamcong/checkin", methods=["POST"])
def checkin():
    if "user_id" not in session:
        return redirect("/chamcong/login")
    uid=session["user_id"]
    today=datetime.now().strftime("%Y-%m-%d")
    now_time=datetime.now().strftime("%H:%M:%S")
    conn=get_chamcong_db()
    # đã checkin hôm nay chưa
    row=conn.execute("SELECT * FROM attendance WHERE employee_id=? AND date=?",(uid,today)).fetchone()
    if row:
        conn.close()
        return redirect("/chamcong/employee?msg=Bạn đã check-in hôm nay lúc "+(row["check_in"] or ""))
    conn.execute("INSERT INTO attendance (employee_id,date,check_in) VALUES (?,?,?)",(uid,today,now_time))
    conn.commit(); conn.close()
    return redirect("/chamcong/employee?msg=Check-in thành công lúc "+now_time)

@app.route("/chamcong/checkout", methods=["POST"])
def checkout():
    if "user_id" not in session:
        return redirect("/chamcong/login")
    uid=session["user_id"]
    today=datetime.now().strftime("%Y-%m-%d")
    now_time=datetime.now().strftime("%H:%M:%S")
    conn=get_chamcong_db()
    row=conn.execute("SELECT * FROM attendance WHERE employee_id=? AND date=?",(uid,today)).fetchone()
    if not row:
        conn.close()
        return redirect("/chamcong/employee?msg=Bạn chưa check-in hôm nay")
    if row["check_out"]:
        conn.close()
        return redirect("/chamcong/employee?msg=Bạn đã check-out rồi")
    # tính giờ
    fmt="%H:%M:%S"
    try:
        t1=datetime.strptime(row["check_in"],fmt); t2=datetime.strptime(now_time,fmt)
        hours=round((t2-t1).seconds/3600,2)
    except:
        hours=0
    conn.execute("UPDATE attendance SET check_out=?, work_hours=? WHERE id=?",(now_time,hours,row["id"]))
    conn.commit(); conn.close()
    return redirect(f"/chamcong/employee?msg=Check-out thành công! Làm {hours} giờ")

@app.route("/chamcong/admin")
def admin_dashboard():
    if session.get("role")!="admin":
        return redirect("/chamcong/login")
    conn=get_chamcong_db()
    emps=conn.execute("SELECT * FROM employees ORDER BY id").fetchall()
    conn.close()
    return render_template("admin_dashboard.html", employees=emps)

@app.route("/chamcong/add_employee", methods=["POST"])
def add_employee():
    if session.get("role")!="admin":
        return redirect("/chamcong/login")
    name=request.form["name"]; username=request.form["username"]; password=request.form["password"]
    conn=get_chamcong_db()
    try:
        conn.execute("INSERT INTO employees (name,username,password,role) VALUES (?,?,?,?)",(name,username,password,"employee"))
        conn.commit()
    except: pass
    conn.close()
    return redirect("/chamcong/admin")

@app.route("/chamcong/edit/<int:emp_id>", methods=["GET","POST"])
def edit_employee(emp_id):
    if session.get("role")!="admin":
        return redirect("/chamcong/login")
    conn=get_chamcong_db()
    if request.method=="POST":
        name=request.form["name"]; username=request.form["username"]; password=request.form["password"]; role=request.form["role"]
        if password:
            conn.execute("UPDATE employees SET name=?,username=?,password=?,role=? WHERE id=?",(name,username,password,role,emp_id))
        else:
            conn.execute("UPDATE employees SET name=?,username=?,role=? WHERE id=?",(name,username,role,emp_id))
        conn.commit(); conn.close()
        return redirect("/chamcong/admin")
    emp=conn.execute("SELECT * FROM employees WHERE id=?",(emp_id,)).fetchone()
    conn.close()
    return render_template("edit_employee.html", emp=emp)

@app.route("/chamcong/delete/<int:emp_id>")
def delete_employee(emp_id):
    if session.get("role")!="admin":
        return redirect("/chamcong/login")
    conn=get_chamcong_db()
    conn.execute("DELETE FROM employees WHERE id=?",(emp_id,))
    conn.commit(); conn.close()
    return redirect("/chamcong/admin")

@app.route("/chamcong/log/<int:emp_id>")
@app.route("/chamcong/history")
def attendance_log(emp_id=None):
    if "user_id" not in session:
        return redirect("/chamcong/login")
    conn=get_chamcong_db()
    if emp_id:
        if session.get("role")!="admin":
            return redirect("/chamcong/login")
        logs=conn.execute("SELECT * FROM attendance WHERE employee_id=? ORDER BY date DESC",(emp_id,)).fetchall()
        emp=conn.execute("SELECT * FROM employees WHERE id=?",(emp_id,)).fetchone()
    else:
        uid=session["user_id"]
        logs=conn.execute("SELECT * FROM attendance WHERE employee_id=? ORDER BY date DESC",(uid,)).fetchall()
        emp=None
    conn.close()
    return render_template("attendance_log.html", logs=logs, employee=emp)

# ===== SYNC API GIỮ NGUYÊN =====
@app.route("/sync/<ten_db>", methods=["POST"])
def sync_db(ten_db):
    if request.headers.get("X-TOKEN") != TOKEN:
        return "Sai token",403
    if ten_db not in ["khachhang.db","database.db","chamcong.db"]:
        return "Ten file khong hop le",400
    tmp=ten_db+".tmp"
    request.files['file'].save(tmp)
    os.replace(tmp, ten_db)
    # nếu là chamcong.db thì init lại
    if ten_db=="chamcong.db":
        init_chamcong()
    return f"OK {ten_db}"

@app.route("/health")
def health():
    return "OK"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
