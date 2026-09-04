import os
import sys
import time
import hashlib
import threading
import requests
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


# ================== CẤU HÌNH ==================
CLOUD_URL = "https://biolinh-2hand.onrender.com/"  # sửa nếu cần
TOKEN = "biolinh2hand_2026"

# File cần quản lý
DB_FILES = ["khachhang.db", "nv.db"]
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Nếu chạy .exe thì lấy thư mục exe
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)

# Thử nhiều endpoint để tương thích với server cũ
MD5_ENDPOINTS = [
    f"{CLOUD_URL}/md5/{{}}",
    f"{CLOUD_URL}/sync/md5/{{}}",
    f"{CLOUD_URL}/api/md5/{{}}",
]
DOWNLOAD_ENDPOINTS = [
    f"{CLOUD_URL}/download/{{}}",
    f"{CLOUD_URL}/sync/download/{{}}",
    f"{CLOUD_URL}/api/download/{{}}",
]
UPLOAD_ENDPOINT = f"{CLOUD_URL}/sync/{{}}"

# ================== UTILS ==================
def get_local_md5(file_path):
    if not os.path.exists(file_path):
        return None
    h = hashlib.md5()
    try:
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None

def get_cloud_md5(filename):
    """Thử các endpoint md5, trả về md5 string hoặc None"""
    for url_tpl in MD5_ENDPOINTS:
        url = url_tpl.format(filename)
        try:
            r = requests.get(url, headers={'X-TOKEN': TOKEN}, timeout=10)
            if r.status_code == 200:
                # Server có thể trả về {"md5": "abc"} hoặc text thuần
                try:
                    data = r.json()
                    if isinstance(data, dict) and 'md5' in data:
                        return data['md5']
                    # có thể là {"khachhang.db": "md5"}
                    if filename in data:
                        return data[filename]
                except:
                    # trả về text
                    txt = r.text.strip()
                    # lọc lấy 32 ký tự md5
                    if len(txt) >= 32:
                        return txt[:32]
                    return txt
        except Exception:
            continue
    return None

def download_file_from_cloud(filename, dest_path):
    """Thử các endpoint download, trả về True/False"""
    for url_tpl in DOWNLOAD_ENDPOINTS:
        url = url_tpl.format(filename)
        try:
            with requests.get(url, headers={'X-TOKEN': TOKEN}, stream=True, timeout=60) as r:
                if r.status_code == 200 and 'text/html' not in r.headers.get('Content-Type','').lower():
                    # kiểm tra có phải file db không (tránh tải trang 404)
                    # nếu content-length quá nhỏ và là json thì bỏ qua
                    if r.headers.get('Content-Length') and int(r.headers['Content-Length']) < 100:
                        try:
                            if b'md5' in r.content[:200].lower() or b'not found' in r.content[:200].lower():
                                continue
                        except:
                            pass
                    with open(dest_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                    return True, url
        except Exception as e:
            last_err = str(e)
            continue
    return False, last_err if 'last_err' in locals() else "Không kết nối được server"

def upload_file_to_cloud(file_path):
    filename = os.path.basename(file_path)
    url = UPLOAD_ENDPOINT.format(filename)
    try:
        with open(file_path, 'rb') as f:
            r = requests.post(url, files={'file': f}, headers={'X-TOKEN': TOKEN}, timeout=60)
        return r.status_code == 200, r.text
    except Exception as e:
        return False, str(e)

# ================== WATCHDOG HANDLER ==================
class DbHandler(FileSystemEventHandler):
    def __init__(self, gui_ref):
        super().__init__()
        self.gui = gui_ref
        self._last_upload = 0
        self._debounce = 2.0

    def on_modified(self, event):
        if event.is_directory:
            return
        ten = os.path.basename(event.src_path)
        if ten != "khachhang.db":
            return
        if ten.endswith((".tmp", ".wal", ".journal")):
            return
        now = time.time()
        if now - self._last_upload < self._debounce:
            return
        self._last_upload = now
        time.sleep(0.5)
        
        # FIX: Cập nhật MD5 local ngay khi file thay đổi
        new_local_md5 = get_local_md5(event.src_path)
        if new_local_md5:
            self.gui.root.after(0, lambda: self.gui.local_md5_vars[ten].set(new_local_md5))
            self.gui.root.after(0, lambda: self.gui.status_vars[ten].set("⏳ Đang đẩy..."))
            self.gui.log(f"-> Phát hiện {ten} thay đổi (MD5 mới: {new_local_md5[:8]}...), đang đẩy lên cloud...")

        ok, msg = upload_file_to_cloud(event.src_path)
        if ok:
            self.gui.log(f"   [OK] Đẩy {ten} lên cloud thành công!")
            # FIX: Cập nhật cả 2 ô MD5 về cùng giá trị mới
            self.gui.root.after(0, lambda: self.gui.on_sync_success(ten, new_local_md5))
        else:
            self.gui.log(f"   [LỖI] Đẩy {ten} thất bại: {msg}")
            self.gui.root.after(0, lambda: self.gui.status_vars[ten].set("❌ Lỗi đẩy"))

# ================== GUI ==================
class SyncGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("BioLinh - Quản lý đồng bộ DB")
        self.root.geometry("750x620")
        self.root.minsize(750, 620)

        self.observer = None
        self.sync_enabled = False
        self.handler = DbHandler(self)

        # Biến lưu md5
        self.local_md5_vars = {}
        self.cloud_md5_vars = {}
        self.status_vars = {}

        self.build_ui()
        self.log(f"Thư mục làm việc: {BASE_DIR}")
        self.log(f"Cloud: {CLOUD_URL}")
        self.log("Đang khởi động kiểm tra MD5...")
        # auto check sau 800ms
        self.root.after(800, lambda: self.run_in_thread(self.check_all_md5))

    def build_ui(self):
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        # --- Tiêu đề ---
        title = ttk.Label(main, text="ĐỒNG BỘ DỮ LIỆU - CLOUD LÀM CHUẨN", font=("Segoe UI", 13, "bold"))
        title.pack(anchor="w", pady=(0,10))

        # --- Frame trạng thái file ---
        status_frame = ttk.LabelFrame(main, text="Trạng thái MD5", padding=10)
        status_frame.pack(fill=tk.X, pady=5)

        # Header
        headers = ["File", "MD5 Local", "MD5 Cloud", "Trạng thái"]
        for col, h in enumerate(headers):
            ttk.Label(status_frame, text=h, font=("Segoe UI", 9, "bold")).grid(row=0, column=col, padx=6, pady=4, sticky="w")

        for idx, fname in enumerate(DB_FILES, start=1):
            ttk.Label(status_frame, text=fname, font=("Segoe UI", 10, "bold")).grid(row=idx, column=0, padx=6, pady=6, sticky="w")

            local_var = tk.StringVar(value="...")
            cloud_var = tk.StringVar(value="...")
            status_var = tk.StringVar(value="Chưa kiểm tra")

            self.local_md5_vars[fname] = local_var
            self.cloud_md5_vars[fname] = cloud_var
            self.status_vars[fname] = status_var

            ttk.Label(status_frame, textvariable=local_var, font=("Consolas", 8), width=34).grid(row=idx, column=1, padx=6)
            ttk.Label(status_frame, textvariable=cloud_var, font=("Consolas", 8), width=34).grid(row=idx, column=2, padx=6)
            ttk.Label(status_frame, textvariable=status_var, font=("Segoe UI", 9), width=16).grid(row=idx, column=3, padx=6)

        status_frame.grid_columnconfigure(1, weight=1)
        status_frame.grid_columnconfigure(2, weight=1)

        # --- Frame nút điều khiển ---
        ctrl_frame = ttk.LabelFrame(main, text="Điều khiển", padding=10)
        ctrl_frame.pack(fill=tk.X, pady=10)

        row1 = ttk.Frame(ctrl_frame)
        row1.pack(fill=tk.X, pady=2)
        self.btn_check = ttk.Button(row1, text="🔄 Kiểm tra lại MD5", command=lambda: self.run_in_thread(self.check_all_md5))
        self.btn_check.pack(side=tk.LEFT, padx=4)

        self.btn_dl_kh = ttk.Button(row1, text="⬇ Tải khachhang.db từ Cloud", command=lambda: self.run_in_thread(lambda: self.download_flow("khachhang.db", ask=False)))
        self.btn_dl_kh.pack(side=tk.LEFT, padx=4)

        self.btn_dl_nv = ttk.Button(row1, text="⬇ Tải nv.db từ Cloud", command=lambda: self.run_in_thread(lambda: self.download_flow("nv.db", ask=False)))
        self.btn_dl_nv.pack(side=tk.LEFT, padx=4)

        row2 = ttk.Frame(ctrl_frame)
        row2.pack(fill=tk.X, pady=(8,2))

        self.btn_toggle_sync = ttk.Button(row2, text="▶ Bật đồng bộ khachhang.db lên Cloud", command=self.toggle_sync, state=tk.DISABLED)
        self.btn_toggle_sync.pack(side=tk.LEFT, padx=4)

        self.btn_up_kh = ttk.Button(row2, text="⬆ Đẩy khachhang.db lên Cloud (thủ công)", command=lambda: self.run_in_thread(lambda: self.manual_upload("khachhang.db")))
        self.btn_up_kh.pack(side=tk.LEFT, padx=4)

        self.btn_up_nv = ttk.Button(row2, text="⬆ Đẩy nv.db lên Cloud (Backup)", command=lambda: self.run_in_thread(lambda: self.manual_upload("nv.db")))
        self.btn_up_nv.pack(side=tk.LEFT, padx=4)

        self.lbl_sync_status = ttk.Label(ctrl_frame, text="Đồng bộ tự động: TẮT", foreground="red", font=("Segoe UI", 9, "bold"))
        self.lbl_sync_status.pack(anchor="w", pady=(8,0))

        # --- Log ---
        log_frame = ttk.LabelFrame(main, text="Nhật ký", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.txt_log = scrolledtext.ScrolledText(log_frame, height=18, font=("Consolas", 9))
        self.txt_log.pack(fill=tk.BOTH, expand=True)
        self.txt_log.configure(state=tk.DISABLED)

    # --- Log thread-safe ---
    def log(self, msg):
        def _append():
            self.txt_log.configure(state=tk.NORMAL)
            ts = time.strftime("%H:%M:%S")
            self.txt_log.insert(tk.END, f"[{ts}] {msg}\n")
            self.txt_log.see(tk.END)
            self.txt_log.configure(state=tk.DISABLED)
        self.root.after(0, _append)

    def run_in_thread(self, func):
        threading.Thread(target=func, daemon=True).start()

    def on_sync_success(self, filename, new_md5):
        if new_md5:
            self.local_md5_vars[filename].set(new_md5)
            self.cloud_md5_vars[filename].set(new_md5)
            self.status_vars[filename].set("✅ Khớp")

    # --- Các hàm xử lý chính ---
    def check_all_md5(self):
        self.log("=== Bắt đầu kiểm tra MD5 ===")
        all_match = True
        kh_match = None

        for fname in DB_FILES:
            fpath = os.path.join(BASE_DIR, fname)
            local_md5 = get_local_md5(fpath)
            self.root.after(0, lambda f=fname, v=local_md5 or "Không có file": self.local_md5_vars[f].set(v))
            
            if local_md5 is None:
                self.log(f"{fname}: Không tìm thấy file local")
                self.root.after(0, lambda f=fname: self.status_vars[f].set("Thiếu file local"))
            else:
                self.log(f"{fname}: MD5 local = {local_md5}")

            cloud_md5 = get_cloud_md5(fname)
            self.root.after(0, lambda f=fname, v=cloud_md5 or "Lỗi/Không có": self.cloud_md5_vars[f].set(v))

            if cloud_md5 is None:
                self.log(f"{fname}: Không lấy được MD5 từ Cloud (server chưa hỗ trợ /md5 hoặc file chưa có trên cloud)")
                self.root.after(0, lambda f=fname: self.status_vars[f].set("Không lấy được MD5 cloud"))
                all_match = False
                if fname == "khachhang.db":
                    kh_match = False
                continue

            self.log(f"{fname}: MD5 cloud = {cloud_md5}")

            if local_md5 == cloud_md5:
                self.log(f"✅ {fname}: Khớp MD5")
                self.root.after(0, lambda f=fname: self.status_vars[f].set("✅ Khớp"))
                if fname == "khachhang.db":
                    kh_match = True
            else:
                self.log(f"⚠️ {fname}: LỆCH MD5! Cloud làm chuẩn -> cần tải về")
                self.root.after(0, lambda f=fname: self.status_vars[f].set("⚠️ Lệch MD5"))
                all_match = False
                if fname == "khachhang.db":
                    kh_match = False
                # Hỏi tải về
                self.root.after(0, lambda fn=fname: self.ask_download(fn))

        # Kích hoạt nút đồng bộ nếu khachhang.db khớp
        if kh_match:
            self.log("khachhang.db đã khớp -> kích hoạt nút bật đồng bộ")
            self.root.after(0, lambda: self.btn_toggle_sync.config(state=tk.NORMAL))
        else:
            # nếu lệch, disable cho đến khi tải xong
            self.root.after(0, lambda: self.btn_toggle_sync.config(state=tk.DISABLED))
            if kh_match is False:
                self.log("Nút đồng bộ khachhang.db đang TẮT cho đến khi tải file chuẩn từ cloud về")

        self.log("=== Kết thúc kiểm tra MD5 ===")

    def ask_download(self, filename):
        # Hỏi trên main thread
        if not messagebox.askyesno("Lệch MD5", f"File {filename} trên máy khác với Cloud (Cloud làm chuẩn).\nBạn có muốn tải bản chuẩn từ Cloud về ghi đè không?"):
            self.log(f"{filename}: Người dùng chọn KHÔNG tải về")
            return
        self.run_in_thread(lambda: self.download_flow(filename, ask=False))

    def download_flow(self, filename, ask=True):
        fpath = os.path.join(BASE_DIR, filename)
        if ask:
            # dùng cho nút bấm thủ công
            pass

        self.log(f"⬇ Bắt đầu tải {filename} từ Cloud...")
        ok, info = download_file_from_cloud(filename, fpath + ".tmp")
        if ok:
            try:
                # backup file cũ
                if os.path.exists(fpath):
                    bak = fpath + f".bak_{int(time.time())}"
                    os.rename(fpath, bak)
                    self.log(f"Đã backup file cũ thành {os.path.basename(bak)}")
                os.rename(fpath + ".tmp", fpath)
                self.log(f"✅ Tải về hoàn tất: {filename} đã được ghi đè bằng bản chuẩn từ Cloud ({info})")
                new_md5 = get_local_md5(fpath)
                self.root.after(0, lambda: self.local_md5_vars[filename].set(new_md5))
                self.root.after(0, lambda: self.cloud_md5_vars[filename].set(new_md5)) # sau khi tải thì coi như khớp
                self.root.after(0, lambda: self.status_vars[filename].set("✅ Khớp (vừa tải)"))
                # Nếu là khachhang.db thì kích hoạt nút đồng bộ
                if filename == "khachhang.db":
                    self.root.after(0, lambda: self.btn_toggle_sync.config(state=tk.NORMAL))
                    self.log("Nút 'Bật đồng bộ khachhang.db lên Cloud' đã được kích hoạt")
                self.root.after(0, lambda fn=filename: messagebox.showinfo("Hoàn tất", f"Tải {fn} từ Cloud thành công!"))
            except Exception as e:
                self.log(f"[LỖI] Ghi file {filename}: {e}")
        else:
            self.log(f"[LỖI] Không tải được {filename}: {info}")
            self.root.after(0, lambda: messagebox.showerror("Lỗi tải", f"Không tải được {filename}:\n{info}"))

    def manual_upload(self, filename):
        fpath = os.path.join(BASE_DIR, filename)
        if not os.path.exists(fpath):
            self.log(f"[LỖI] Không có file {filename} để đẩy")
            self.root.after(0, lambda: messagebox.showerror("Lỗi", f"Không tìm thấy {fpath}"))
            return
        self.log(f"⬆ Đang đẩy {filename} lên Cloud (thủ công)...")
        ok, msg = upload_file_to_cloud(fpath)
        if ok:
            self.log(f"✅ Đẩy {filename} lên Cloud thành công!")
            # cập nhật lại cloud md5
            new_local = get_local_md5(fpath)
            self.root.after(0, lambda: self.cloud_md5_vars[filename].set(new_local or ""))
            self.root.after(0, lambda: self.status_vars[filename].set("✅ Khớp (vừa đẩy)"))
            if filename == "khachhang.db":
                self.root.after(0, lambda: self.btn_toggle_sync.config(state=tk.NORMAL))
            self.root.after(0, lambda: messagebox.showinfo("Thành công", f"Đã đẩy {filename} lên Cloud"))
        else:
            self.log(f"[LỖI] Đẩy {filename} thất bại: {msg}")
            self.root.after(0, lambda: messagebox.showerror("Lỗi", f"Đẩy {filename} thất bại:\n{msg}"))

    def update_cloud_md5_after_upload(self, filename):
        fpath = os.path.join(BASE_DIR, filename)
        md5 = get_local_md5(fpath)
        if md5:
            self.root.after(0, lambda: self.cloud_md5_vars[filename].set(md5))

    def toggle_sync(self):
        if not self.sync_enabled:
            # Bật
            self.start_observer()
        else:
            self.stop_observer()

    def start_observer(self):
        if self.observer and self.observer.is_alive():
            return
        try:
            self.observer = Observer()
            self.observer.schedule(self.handler, BASE_DIR, recursive=False)
            self.observer.start()
            self.sync_enabled = True
            self.root.after(0, lambda: self.btn_toggle_sync.config(text="⏸ Tắt đồng bộ khachhang.db"))
            self.root.after(0, lambda: self.lbl_sync_status.config(text="Đồng bộ tự động: BẬT - Đang lắng nghe thay đổi khachhang.db", foreground="green"))
            self.log("▶ Đã BẬT đồng bộ tự động khachhang.db -> Cloud (watchdog)")
        except Exception as e:
            self.log(f"[LỖI] Không bật được observer: {e}")

    def stop_observer(self):
        if self.observer:
            try:
                self.observer.stop()
                self.observer.join(timeout=2)
            except:
                pass
            self.observer = None
        self.sync_enabled = False
        self.root.after(0, lambda: self.btn_toggle_sync.config(text="▶ Bật đồng bộ khachhang.db lên Cloud"))
        self.root.after(0, lambda: self.lbl_sync_status.config(text="Đồng bộ tự động: TẮT", foreground="red"))
        self.log("⏸ Đã TẮT đồng bộ tự động")

    def on_close(self):
        self.stop_observer()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    # style
    try:
        style = ttk.Style()
        style.theme_use("clam")
    except:
        pass
    app = SyncGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
