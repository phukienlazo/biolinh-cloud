
import time, requests, os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# --- CẤU HÌNH ---
CLOUD_URL = "https://ten-app-cua-ban.koyeb.app"  # <-- dán link Koyeb sau khi deploy vào đây
TOKEN = "biolinh2hand_2026" # phải khớp với TOKEN ở app.py
FILES_TO_WATCH = ["database.db"] # bạn có 2 file 112k và 596k, để cả 2 tên vào đây
# Ví dụ: FILES_TO_WATCH = ["database.db", "database2.db"]

class Handler(FileSystemEventHandler):
    def on_modified(self, event):
        ten = os.path.basename(event.src_path)
        if ten in FILES_TO_WATCH:
            print(f"-> Phát hiện {ten} thay đổi, đang đẩy lên cloud...")
            try:
                with open(event.src_path, 'rb') as f:
                    r = requests.post(f"{CLOUD_URL}/sync/{ten}",
                                      files={'file': f},
                                      headers={'X-TOKEN': TOKEN},
                                      timeout=15)
                if r.status_code == 200:
                    print("   OK đẩy thành công!")
                else:
                    print(f"   Lỗi server: {r.text}")
            except Exception as e:
                print(f"   Không đẩy được: {e}")

print(f"Đang canh các file: {FILES_TO_WATCH}")
print("Để cửa sổ này chạy ngầm, đừng tắt.")
observer = Observer()
observer.schedule(Handler(), ".", recursive=False)
observer.start()
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    observer.stop()
observer.join()
