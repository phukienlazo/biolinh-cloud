
import os, time, requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

CLOUD_URL = "https://ten-app-cua-ban.koyeb.app" # <-- DÁN LINK KOYEB VÀO ĐÂY
TOKEN = "biolinh2hand_2026"
FILES_TO_WATCH = ["khachhang.db", "database.db"] # 2 file của bạn

class Handler(FileSystemEventHandler):
    def on_modified(self, event):
        ten = os.path.basename(event.src_path)
        if ten in FILES_TO_WATCH:
            # tránh trigger khi đang ghi file tmp
            if ten.endswith(".tmp"):
                return
            print(f"-> {ten} thay đổi, đang đẩy lên...")
            try:
                with open(event.src_path, 'rb') as f:
                    r = requests.post(f"{CLOUD_URL}/sync/{ten}",
                                      files={'file': f},
                                      headers={'X-TOKEN': TOKEN},
                                      timeout=20)
                print("   OK!" if r.status_code==200 else f"   Lỗi: {r.text}")
            except Exception as e:
                print(f"   Lỗi: {e}")

observer = Observer()
observer.schedule(Handler(), ".", recursive=False)
observer.start()
print(f"Đang canh: {FILES_TO_WATCH} - Đừng tắt cửa sổ này")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    observer.stop()
observer.join()
