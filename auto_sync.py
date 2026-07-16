
import os, time, requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# === BẠN CHỈ CẦN SỬA 2 DÒNG NÀY ===
CLOUD_URL = "https://ten-app-cua-ban.koyeb.app"  # dán link Koyeb vào đây sau khi deploy
TOKEN = "biolinh2hand_2026"
# =================================

FILES_TO_WATCH = ["khachhang.db", "database.db"]

class Handler(FileSystemEventHandler):
    def on_modified(self, event):
        ten = os.path.basename(event.src_path)
        if ten in FILES_TO_WATCH and not ten.endswith(".tmp"):
            print(f"-> Phat hien {ten} thay doi, dang day len cloud...")
            try:
                with open(event.src_path, 'rb') as f:
                    r = requests.post(f"{CLOUD_URL}/sync/{ten}",
                                      files={'file': f},
                                      headers={'X-TOKEN': TOKEN},
                                      timeout=20)
                print("   Thanh cong!" if r.status_code==200 else f"   Loi: {r.text}")
            except Exception as e:
                print(f"   Loi: {e}")

print(f"Dang canh file: {FILES_TO_WATCH}")
print("Hay de cua so nay chay, dung tat.")
observer = Observer()
observer.schedule(Handler(), ".", recursive=False)
observer.start()
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    observer.stop()
observer.join()
