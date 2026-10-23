"""service/main.py - phát nhạc nền: MediaPlayer + Foreground Service + AudioFocus + hẹn giờ ngủ.
Chạy trong tiến trình riêng nên sống khi UI bị đóng/tắt màn hình. KHÔNG import pygame.
IPC: UDP localhost. UI -> service cổng SP (lệnh JSON), service -> UI cổng UP (trạng thái JSON)."""
import socket, json, time, os, random, sys, traceback
try: from android.storage import app_storage_path; HOME = app_storage_path()
except Exception: HOME = os.getcwd()
LOG = os.path.join(HOME, "svc.log")                          # UI đọc file này và hiện ở trang Thông tin


def log(s):
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 20000: os.remove(LOG)
        open(LOG, "a").write("%s %s\n" % (time.strftime("%H:%M:%S"), s))
    except Exception: pass


sys.excepthook = lambda *a: log("CRASH " + "".join(traceback.format_exception(*a))[-300:])
log("service start")
from jnius import autoclass, PythonJavaClass, java_method

SP, UP = 41701, 41702
PL = os.path.join(HOME, "playlist.json")      # UI ghi [[path, title, artist], ...]
Svc = autoclass("org.kivy.android.PythonService").mService
Ctx, MP = autoclass("android.content.Context"), autoclass("android.media.MediaPlayer")
JS, SDK = autoclass("java.lang.String"), autoclass("android.os.Build$VERSION").SDK_INT


class Done(PythonJavaClass):                                 # hết bài -> chỉ đặt cờ, việc nặng làm ở vòng chính
    __javainterfaces__ = ["android/media/MediaPlayer$OnCompletionListener"]
    __javacontext__ = "app"
    @java_method("(Landroid/media/MediaPlayer;)V")
    def onCompletion(self, mp): nxt.append(1)


class Focus(PythonJavaClass):                                # cuộc gọi / app khác chiếm âm thanh
    __javainterfaces__ = ["android/media/AudioManager$OnAudioFocusChangeListener"]
    __javacontext__ = "app"
    @java_method("(I)V")
    def onAudioFocusChange(self, c): fev.append(c)


class Recv(PythonJavaClass):                                 # nhận bấm nút trên thông báo (Trước / Phát-Dừng / Sau)
    __javainterfaces__ = ["org/kivy/android/GenericBroadcastReceiverCallback"]
    __javacontext__ = "app"
    @java_method("(Landroid/content/Context;Landroid/content/Intent;)V")
    def onReceive(self, ctx, intent): acts.append(str(intent.getAction()))


nxt, fev, acts = [], [], []
ACTS = {"PREV": "prev", "TOGGLE": "toggle", "NEXT": "next"}
PKG = str(Svc.getPackageName()) + ".MP_"
done, focus = Done(), Focus()                                # giữ tham chiếu toàn cục, tránh bị GC
am = Svc.getSystemService(Ctx.AUDIO_SERVICE)
tracks, cur, curp, mp = [], 0, "", None
ready = paused = auto = False; vol, duck, sl_at, run = 0.7, 1.0, 0, True
shuf, rep = False, 1                                         # ngẫu nhiên; lặp: 0 tắt, 1 tất cả, 2 một bài

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); sock.bind(("127.0.0.1", SP))
log("socket bound")


def send(**d):
    try: sock.sendto(json.dumps(d).encode(), ("127.0.0.1", UP))
    except OSError: pass


def setup_receiver():
    global recv, rcv
    try:
        recv = Recv(); rcv = autoclass("org.kivy.android.GenericBroadcastReceiver")(recv)   # giữ tham chiếu toàn cục
        f = autoclass("android.content.IntentFilter")()
        for a in ACTS: f.addAction(JS(PKG + a))
        if SDK >= 33: Svc.registerReceiver(rcv, f, 4)        # RECEIVER_NOT_EXPORTED
        else: Svc.registerReceiver(rcv, f)
        log("receiver ok")
    except Exception: log("receiver FAIL " + traceback.format_exc()[-250:])


def notify():                                                # notification foreground: tên bài + nút Trước / Phát-Dừng / Sau
    try:
        r = tracks[cur] if tracks else ["", "Nghe Nhạc", ""]
        B = autoclass("android.app.Notification$Builder")
        if SDK >= 26:
            ch = autoclass("android.app.NotificationChannel")("mp", JS("Nhạc"), 2)   # IMPORTANCE_LOW: im lặng
            Svc.getSystemService(Ctx.NOTIFICATION_SERVICE).createNotificationChannel(ch); b = B(Svc, "mp")
        else: b = B(Svc)
        it = Svc.getPackageManager().getLaunchIntentForPackage(Svc.getPackageName())
        pi = autoclass("android.app.PendingIntent").getActivity(Svc, 0, it, 0x0C000000)   # IMMUTABLE|UPDATE_CURRENT
        b = (b.setContentTitle(JS(r[1] or os.path.basename(r[0]))).setContentText(JS(r[2] or ("Tạm dừng" if paused else "Đang phát")))
              .setSmallIcon(Svc.getApplicationInfo().icon).setContentIntent(pi).setOngoing(True).setVisibility(1))   # 1 = hiện cả trên màn hình khoá
        try:                                                 # nút điều khiển; hỏng thì vẫn có thông báo thường
            Rd, PI, In = autoclass("android.R$drawable"), autoclass("android.app.PendingIntent"), autoclass("android.content.Intent")
            playing = ready and not paused
            for i, (a, ic, lb) in enumerate((("PREV", Rd.ic_media_previous, "Trước"),
                                             ("TOGGLE", Rd.ic_media_pause if playing else Rd.ic_media_play, "Dừng" if playing else "Phát"),
                                             ("NEXT", Rd.ic_media_next, "Sau"))):
                ii = In(JS(PKG + a)); ii.setPackage(Svc.getPackageName())
                b.addAction(ic, JS(lb), PI.getBroadcast(Svc, i + 1, ii, 0x0C000000))
            ms = autoclass("android.app.Notification$MediaStyle")(); ms.setShowActionsInCompactView([0, 1, 2]); b.setStyle(ms)
        except Exception: log("notify actions: " + traceback.format_exc()[-250:])
        Svc.startForeground(1, b.build())
    except Exception as e: send(e="Notif: " + str(e)[:30]); log("notify: " + traceback.format_exc()[-250:])


def setv():
    if mp:
        try: v = vol * duck; mp.setVolume(v, v)
        except Exception: pass


def reload():                                                # đọc lại playlist (gói "pl" đầu tiên hay bị mất do service dậy chậm)
    global tracks, cur
    try:
        tracks = json.load(open(PL)); ps = [r[0] for r in tracks]
        if curp in ps: cur = ps.index(curp)
    except Exception as e: send(e="Playlist: " + str(e)[:28])


def load(i, start=0):
    global cur, curp, mp, ready, paused, auto
    if not tracks: reload()
    if not tracks: send(e="Chưa có playlist"); return
    cur = i % len(tracks); curp = tracks[cur][0]; log("load " + curp)
    try:                                                     # chỉ lỗi mở/giải mã file mới tính là "bài lỗi"
        if mp: mp.release()
        mp = MP(); mp.setWakeMode(Svc, 1)                    # PARTIAL_WAKE_LOCK: CPU không ngủ khi tắt màn hình
        mp.setAudioStreamType(3)
        fis = autoclass("java.io.FileInputStream")(curp)     # mở bằng FileDescriptor: ổn định hơn đường dẫn chuỗi
        try: mp.setDataSource(fis.getFD())
        finally: fis.close()
        mp.prepare()
        if start: mp.seekTo(int(start * 1000))               # tiếp tục đúng vị trí lần trước
        mp.start(); ready, paused, auto = True, False, False
    except Exception as e: ready = False; send(e="Loi: " + str(e)[:34], bad=curp); log("load FAIL " + traceback.format_exc()[-250:]); return
    log("playing")
    for f in (lambda: mp.setOnCompletionListener(done), setv, lambda: am.requestAudioFocus(focus, 3, 1), notify):
        try: f()
        except Exception as e: send(e="Svc: " + str(e)[:30]); log("accessory: " + traceback.format_exc()[-200:])   # phụ kiện hỏng thì vẫn phát được


def pick():                                                  # bài kế: ngẫu nhiên (khác bài hiện tại) hoặc tuần tự
    n = len(tracks)
    if shuf and n > 1: j = random.randrange(n - 1); return j + (j >= cur)
    return cur + 1


def after():                                                 # hết bài
    global paused
    if rep == 2: load(cur)
    elif shuf or rep == 1 or cur + 1 < len(tracks): load(pick())
    else: paused = True                                      # hết danh sách, không lặp: dừng


def cmd(d):
    global tracks, cur, vol, sl_at, run, paused, auto, shuf, rep
    c = d["cmd"]; log("cmd " + c)
    if c == "pl": reload()                                   # nạp lại danh sách, giữ nguyên bài đang phát
    elif c == "play": load(d["i"], d.get("s", 0))
    elif c == "next": load(pick())
    elif c == "mode": shuf, rep = bool(d.get("sh")), int(d.get("rp", 1))
    elif c == "prev": load(cur - 1)
    elif c == "toggle":
        if not ready: load(cur)
        elif paused: am.requestAudioFocus(focus, 3, 1); mp.start(); paused = False
        else: mp.pause(); paused = True
        notify()
    elif c == "seek" and ready:
        t = mp.getCurrentPosition() + int(d["d"] * 1000); dur = mp.getDuration()
        mp.seekTo(max(0, min(t, dur - 1000 if dur > 1000 else dur)))
    elif c == "vol": vol = d["v"]; setv()
    elif c == "sleep": sl_at = time.time() + d["m"] * 60 if d["m"] else 0
    elif c == "quit":
        run = False
        if mp: mp.release()
        Svc.stopForeground(True); Svc.stopSelf()


def tick():
    global paused, auto, duck, sl_at
    if nxt: nxt.clear(); after()
    while acts:                                              # bấm nút trên thông báo / màn hình khoá
        a = acts.pop(0)[len(PKG):]
        if a in ACTS: cmd({"cmd": ACTS[a]})
    while fev:
        c = fev.pop(0)
        if c == 1:                                           # GAIN: lấy lại âm thanh
            duck = 1.0; setv()
            if auto and ready: mp.start(); paused, auto = False, False; notify()
        elif c == -3: duck = 0.3; setv()                     # CAN_DUCK: hạ nhỏ
        elif c in (-1, -2) and ready and not paused:         # LOSS / LOSS_TRANSIENT: tạm dừng
            mp.pause(); paused, auto = True, c == -2; notify()
    if sl_at and time.time() >= sl_at:
        sl_at = 0
        if ready and not paused: mp.pause(); paused = True; notify()


def state():
    p = d = 0.0
    if ready and mp:
        try: p, d = mp.getCurrentPosition() / 1000.0, mp.getDuration() / 1000.0
        except Exception: pass
    sl = int((sl_at - time.time()) / 60) + 1 if sl_at else 0
    send(c=cur, t=curp, p=p, d=d, pl=int(ready), pa=int(paused), sl=sl, n=len(tracks))


try: cmd({"cmd": "pl"})                                      # service tự sống lại (sticky) -> đọc playlist cũ
except Exception: pass
setup_receiver(); notify(); log("loop start, tracks=%d" % len(tracks))
while run:
    sock.settimeout(0.25 if ready and not paused else 1.0)   # idle thì ngủ lâu, đỡ pin
    try: cmd(json.loads(sock.recv(4096)))
    except (socket.timeout, ValueError, KeyError): pass
    except Exception as e: send(e="Svc: " + str(e)[:34]); log("loop: " + traceback.format_exc()[-250:])
    try: tick(); state()
    except Exception as e: send(e="Tick: " + str(e)[:30]); log("tick: " + traceback.format_exc()[-250:])
