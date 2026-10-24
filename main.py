"""main.py - UI trình nghe nhạc Pygame (portrait, lấp đầy màn hình). Cần touchpad.py cạnh file này.
APK: phát nhạc ở service/main.py. Pydroid3: tự chuyển chế độ dev (phát bằng pygame.mixer trong UI)."""
import pygame, os, sys, json, io, base64, re, bisect, threading, time, socket, queue, hashlib, random, gc
import urllib.request, urllib.parse, urllib.error

try: import mutagen, mutagen.flac
except ImportError: mutagen = None

try:                                                         
    from jnius import autoclass
    autoclass("org.kivy.android.PythonService"); APK = True
except Exception: APK = False
if APK:
    from android.storage import app_storage_path
    DATA = app_storage_path()
else:
    try: DATA = os.path.dirname(os.path.abspath(__file__))
    except NameError: DATA = os.getcwd()
LRC = os.path.join(DATA, "lrc"); os.makedirs(LRC, exist_ok=True)
SF, PL, CACHE, BADF = (os.path.join(DATA, n) for n in (".mp_state.json", "playlist.json", "library.json", "bad.json"))
SP, UP = 41701, 41702
ev = queue.Queue()                                           
kick = threading.Event()                                     
BAD = set()                                                  
FF = os.path.join(DATA, "fav.json")                          
try: FAV = set(json.load(open(FF)))
except Exception: FAV = set()
ALL = []                                                     

# ====================================================================
# BACKEND: service (APK, UDP localhost) hoặc Dev (Pydroid3, trong tiến trình)
# ====================================================================
class Dev:
    shuf, rep = False, 1
    def __init__(s):
        s.rows, s.cur, s.curp, s.ready, s.paused, s.vol, s.base, s.sl_at, s.err, s.bad = [], 0, "", False, False, 0.7, 0.0, 0, None, None
        if "ANDROID_ROOT" in os.environ: pygame.mixer.quit(); os.environ["SDL_AUDIODRIVER"] = "openslES"
        try: pygame.mixer.init(44100, -16, 2, 2048)
        except pygame.error:
            os.environ.pop("SDL_AUDIODRIVER", None)
            try: pygame.mixer.init(44100, -16, 2, 2048)
            except pygame.error as e: s.err = "Mixer: " + str(e)[:30]

    def pos(s): return s.base + max(pygame.mixer.music.get_pos(), 0) / 1000.0

    def load(s, i, start=0.0):
        if not s.rows: return
        s.cur = i % len(s.rows); s.curp = s.rows[s.cur][0]
        try:
            m = pygame.mixer.music; m.load(s.curp); m.set_volume(s.vol)
            m.play(start=start) if start else m.play()
            s.ready, s.paused, s.base = True, False, float(start)
        except Exception as e:
            s.ready = False; s.err = "Loi: " + str(e)[:34]
            if pygame.mixer.get_init(): s.bad = s.curp

    def cmd(s, d):
        c, m = d["cmd"], pygame.mixer.music
        try:
            if c == "pl":
                s.rows = json.load(open(PL)); ps = [r[0] for r in s.rows]
                if s.curp in ps: s.cur = ps.index(s.curp)
            elif c == "play": s.load(d["i"], d.get("s", 0))
            elif c == "next": s.load(s.pick())
            elif c == "mode": s.shuf, s.rep = bool(d.get("sh")), int(d.get("rp", 1))
            elif c == "prev": s.load(s.cur - 1)
            elif c == "toggle":
                if not s.ready: s.load(s.cur)
                elif s.paused: m.unpause(); s.paused = False
                else: m.pause(); s.paused = True
            elif c == "seek" and s.ready:
                t = max(0.0, s.pos() + d["d"]); m.play(start=t); s.base = t
                if s.paused: m.pause()
            elif c == "vol": s.vol = d["v"]; m.set_volume(s.vol)
            elif c == "sleep": s.sl_at = time.time() + d["m"] * 60 if d["m"] else 0
            elif c == "quit": m.stop()
        except Exception as e: s.err = "Loi: " + str(e)[:34]

    def pick(s):
        n = len(s.rows)
        if s.shuf and n > 1: j = random.randrange(n - 1); return j + (j >= s.cur)
        return s.cur + 1

    def after(s):
        if s.rep == 2: s.load(s.cur)
        elif s.shuf or s.rep == 1 or s.cur + 1 < len(s.rows): s.load(s.pick())
        else: s.paused = True

    def state(s):
        m = pygame.mixer.music
        if s.ready and not s.paused and not m.get_busy(): s.after()
        if s.sl_at and time.time() >= s.sl_at:
            s.sl_at = 0
            if s.ready and not s.paused: m.pause(); s.paused = True
        sl = int((s.sl_at - time.time()) / 60) + 1 if s.sl_at else 0
        return dict(c=s.cur, t=s.curp, p=s.pos() if s.ready else 0.0, d=0.0, pl=int(s.ready), pa=int(s.paused), sl=sl, n=len(s.rows))

if APK:
    txs = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    rx.bind(("127.0.0.1", UP)); rx.setblocking(False)
else: dev = Dev()

def tx(cmd, **k):
    k["cmd"] = cmd
    if not APK: dev.cmd(k); return
    try: txs.sendto(json.dumps(k).encode(), ("127.0.0.1", SP))
    except OSError: pass

def recv_all():
    out = []
    if not APK:
        out.append(dev.state())
        if dev.err: out.append({"e": dev.err, "bad": dev.bad}); dev.err = dev.bad = None
        return out
    while True:
        try: out.append(json.loads(rx.recv(2048)))
        except (BlockingIOError, OSError, ValueError): return out

def boot():
    from android.permissions import request_permissions
    act = autoclass("org.kivy.android.PythonActivity").mActivity
    request_permissions(["android.permission.READ_MEDIA_AUDIO", "android.permission.READ_EXTERNAL_STORAGE",
                         "android.permission.POST_NOTIFICATIONS"])
    autoclass(act.getPackageName() + ".ServicePlayer").start(act, "")
if APK: boot()

# ====================================================================
# MÀN HÌNH: Khởi tạo tối ưu UI
# ====================================================================
os.environ["SDL_ANDROID_TRAP_BACK_BUTTON"] = "1"
pygame.display.init(); pygame.font.init()
from touchpad import TouchPad
W, PH = 320, 202
class Pad(TouchPad):
    def _want(s): return False, s.side
def fit_h(sw, sh): return max(400, min(900, round(W * sh / sw) - PH))
BTNS = (("S", "", 170, 22), ("A", "", 170, 112), ("C", "", 54, 112), ("B", "", 286, 112))
DP = (160, 112)
sw, sh = pygame.display.get_desktop_sizes()[0]
pad = Pad(W, fit_h(sw, sh), buttons=BTNS, dpad=DP, cell=36, ph=PH, touch=True)
def win_size():
    try: return pygame.display.get_window_size()
    except Exception: return pygame.display.get_surface().get_size()
if APK:
    try:
        from android.runnable import run_on_ui_thread
        @run_on_ui_thread
        def immersive():
            v = autoclass("android.view.View"); w = autoclass("org.kivy.android.PythonActivity").mActivity.getWindow()
            w.getDecorView().setSystemUiVisibility(v.SYSTEM_UI_FLAG_HIDE_NAVIGATION | v.SYSTEM_UI_FLAG_FULLSCREEN | v.SYSTEM_UI_FLAG_IMMERSIVE_STICKY |
                                                   v.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION | v.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN | v.SYSTEM_UI_FLAG_LAYOUT_STABLE)
            at = w.getAttributes(); at.layoutInDisplayCutoutMode = 1; w.setAttributes(at)
        immersive()
        for _ in range(12): pygame.event.pump(); pygame.time.wait(50)
    except Exception: pass
ww, wh = win_size()
if abs(fit_h(ww, wh) - pad.h) > 1: pad = Pad(W, fit_h(ww, wh), buttons=BTNS, dpad=DP, cell=36, ph=PH, touch=True)
S, H = pad.screen, pad.h

def mkfont(sz, bold=False):
    for p in ("/system/fonts/Roboto-Regular.ttf", "/system/fonts/NotoSans-Regular.ttf", "/system/fonts/DroidSans.ttf"):
        if os.path.exists(p): f = pygame.font.Font(p, sz); f.set_bold(bold); return f
    return pygame.font.SysFont("dejavusans,arial", sz, bold=bold)
F, FB = mkfont(12), mkfont(14, True)

# ====================================================================
# THƯ VIỆN NHẠC
# ====================================================================
tracks, names, lib, idx, N = [], [], [], {}, 0
scan_status = "..."

def rows_mediastore():
    act = autoclass("org.kivy.android.PythonActivity").mActivity
    M = autoclass("android.provider.MediaStore$Audio$Media")
    c = act.getContentResolver().query(M.EXTERNAL_CONTENT_URI, ["_data", "title", "artist", "duration"],
                                       "is_music!=0 AND duration>60000", None, "_data COLLATE NOCASE")
    out = []
    if c:
        while c.moveToNext():
            a = c.getString(2) or ""
            out.append([c.getString(0), c.getString(1) or "", "" if a == "<unknown>" else a, c.getLong(3) / 1000.0])
        c.close()
    return out

def rows_walk():
    BADD = ("record", "voice", "call", "ringtone", "alarm", "notif", "whatsapp", "zalo", "viber", "telegram", "msg", "android", "dcim", "movie", "picture")
    BADP = ("aud-", "aud_", "rec_", "rec-", "voice_", "voice-", "call_", "call-", "ptt-")
    out = []
    for r, dirs, fs in os.walk("/storage/emulated/0/"):
        dirs[:] = [d for d in dirs if not d.startswith(".") and not any(b in d.lower() for b in BADD)]
        for f in fs:
            fl = f.lower()
            if fl.endswith((".mp3", ".flac", ".m4a", ".ogg", ".wav")) and not fl.startswith(BADP):
                p = os.path.join(r, f)
                try:
                    if os.path.getsize(p) > 512000: out.append([p, "", "", 0.0])
                except OSError: pass
    return sorted(out, key=lambda x: x[0].lower())

def scanner():
    global scan_status
    if APK:
        from android.permissions import check_permission
        P = ("android.permission.READ_MEDIA_AUDIO", "android.permission.READ_EXTERNAL_STORAGE")
        if not any(check_permission(p) for p in P): ev.put(("toast", "Cần cấp quyền đọc nhạc để quét", 3000))
        while not any(check_permission(p) for p in P): scan_status = "Chờ cấp quyền..."; time.sleep(1)
    while True:
        scan_status = "Đang quét..."
        try:
            rows = [r for r in (rows_mediastore() if APK else rows_walk()) if r[0] not in BAD]
            if rows and rows != ALL:
                json.dump(rows, open(CACHE, "w")); ev.put(("lib", rows))
            scan_status = "Đã nạp %d bài" % len(rows); ev.put(("scanned", len(rows)))
        except Exception as e: scan_status = "Quét lỗi: " + str(e)[:24]; ev.put(("toast", "Quét lỗi: " + str(e)[:40], 3000))
        kick.wait(60); kick.clear()

# ====================================================================
# LYRIC + METADATA
# ====================================================================
TS = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")
def parse_lyrics(txt):
    out = []
    for ln in txt.replace("\r", "").split("\n"):
        ts = TS.findall(ln); s = TS.sub("", ln).strip()
        if ts: out += [(int(a) * 60 + float(b), s) for a, b in ts]
        elif s and not s.startswith("["): out.append((None, s))
    if out and all(t is not None for t, _ in out): out.sort(key=lambda x: x[0]); return True, out[:600]
    return False, [(None, s) for _, s in out if s][:600]

def lrc_path(p): return os.path.join(LRC, hashlib.md5(p.encode()).hexdigest()[:12] + ".lrc")

def find_lyrics(path, emb):
    for f, src in ((os.path.splitext(path)[0] + ".lrc", ".lrc cạnh bài"), (lrc_path(path), "đã tải về")):
        try: return parse_lyrics(open(f, encoding="utf-8-sig", errors="ignore").read()) + (src,)
        except OSError: pass
    return parse_lyrics(emb) + ("nhúng trong file",) if emb else (False, [], "")

CTX = None
def ssl_ctx():
    global CTX
    if CTX: return CTX
    import ssl
    try: import certifi; CTX = ssl.create_default_context(cafile=certifi.where()); return CTX
    except Exception: pass
    c = ssl.create_default_context(); d = "/system/etc/security/cacerts"
    try:
        pem = []
        for f in os.listdir(d):
            try: pem += re.findall(r"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", open(os.path.join(d, f), errors="ignore").read(), re.S)
            except OSError: pass
        if pem: c.load_verify_locations(cadata="\n".join(pem))
    except OSError: pass
    CTX = c; return c

def fetch_lyrics(p, a, t):
    try:
        url = "https://lrclib.net/api/get?artist_name=%s&track_name=%s" % (urllib.parse.quote(a), urllib.parse.quote(t))
        req = urllib.request.Request(url, headers={"User-Agent": "MinimalistPygamePlayer/5.0"})
        with urllib.request.urlopen(req, timeout=8, context=ssl_ctx()) as r: d = json.loads(r.read().decode("utf-8"))
        txt = d.get("syncedLyrics") or d.get("plainLyrics")
        if not txt: return "lrclib: không có lời"
        try: open(lrc_path(p), "w", encoding="utf-8").write(txt)
        except OSError: pass
        return parse_lyrics(txt) + ("lrclib.net",)
    except urllib.error.HTTPError as e: return "lrclib: không có lời" if e.code == 404 else "lỗi mạng: máy chủ %d" % e.code
    except Exception as e: return "lỗi mạng: " + type(e).__name__ + " " + str(e)[:40]

def M0(): return dict(art=None, rg=0.0, ly="", len=0.0, title="", artist="", album="", albumartist="", date="", genre="",
                      track="", fmt="", br=0, sr=0, ch=0, bits=0)

def meta(p):
    m = M0()
    if not mutagen: return m
    try: f = mutagen.File(p)
    except Exception: return m
    if f is None: return m
    i = f.info
    m.update(len=float(getattr(i, "length", 0) or 0), fmt=type(f).__name__, br=int(getattr(i, "bitrate", 0) or 0),
             sr=int(getattr(i, "sample_rate", 0) or 0), ch=int(getattr(i, "channels", 0) or 0), bits=int(getattr(i, "bits_per_sample", 0) or 0))
    try:
        e = mutagen.File(p, easy=True).tags or {}
        for k, d in (("title", "title"), ("artist", "artist"), ("album", "album"), ("albumartist", "albumartist"),
                     ("date", "date"), ("genre", "genre"), ("tracknumber", "track")):
            v = e.get(k); m[d] = str(v[0]) if v else ""
    except Exception: pass
    tg = f.tags
    if not tg: return m
    try:
        if hasattr(tg, "getall"):
            pics = tg.getall("APIC")
            if pics: m["art"] = pics[0].data
            us = tg.getall("USLT")
            if us: m["ly"] = us[0].text
            for x in tg.getall("TXXX"):
                if x.desc.upper() == "REPLAYGAIN_TRACK_GAIN": m["rg"] = float(str(x.text[0]).split()[0])
        elif type(f).__name__ == "MP4":
            if "covr" in tg: m["art"] = bytes(tg["covr"][0])
            m["ly"] = str(tg["\xa9lyr"][0]) if "\xa9lyr" in tg else ""
        else:
            g = lambda k: tg[k][0] if k in tg else None
            rg = g("replaygain_track_gain")
            if rg: m["rg"] = float(rg.split()[0])
            m["ly"] = g("lyrics") or g("unsyncedlyrics") or ""
            if getattr(f, "pictures", None): m["art"] = f.pictures[0].data
            elif g("metadata_block_picture"): m["art"] = mutagen.flac.Picture(base64.b64decode(g("metadata_block_picture"))).data
    except Exception: pass
    return m

def bg_meta(p, a, t):
    m = ly = None
    try:
        m = meta(p); ly = find_lyrics(p, m["ly"])
        a, t = m["artist"] or a, m["title"] or t
        if not ly[1] and a and t:
            res = fetch_lyrics(p, a, t); ly = res if isinstance(res, tuple) else (False, [], res)
    except Exception: pass
    ev.put(("meta", p, m or M0(), ly or (False, [], "")))

# ====================================================================
# TRẠNG THÁI + MÀU SẮC ĐÃ ĐƯỢC CACHE ĐỂ RENDER NHANH
# ====================================================================
cur = sel = 0; vol = 0.7; curp = ""; rpos = 0.0
CFG = {"thm": True, "dbg": True, "shuf": False, "rep": 1, "fav": False}
try:
    st = json.load(open(SF)); vol = float(st["v"]); curp = st.get("t", ""); rpos = float(st.get("p", 0))
    CFG.update(st.get("cfg", {}))
except Exception: pass
CFG["dbg"] = False                                        # đổi thành True để bật overlay debug
lastpos = 0.0

def save():
    try: json.dump({"t": curp, "v": round(vol, 2), "p": int(lastpos), "cfg": CFG}, open(SF, "w"))
    except Exception: pass

BGC = (12, 12, 16)
BG = pygame.Surface((W, H)).convert(); BG.fill(BGC)
BGT = (44, 38, 64)
for _y in range(H):
    _k = (_y / H) ** 2; BG.fill(tuple(int(BGT[i] + (BGC[i] - BGT[i]) * _k) for i in range(3)), (0, _y, W, 1))
MASK = pygame.Surface((48, 48), pygame.SRCALPHA); pygame.draw.circle(MASK, (255, 255, 255, 255), (24, 24), 24)
OVL = pygame.Surface((W, H), pygame.SRCALPHA); OVL.fill((10, 10, 14, 245))
frames = [None] * 72; D0 = None; ART = None

COLOR_ACC, COLOR_FG, COLOR_DIM, COLOR_OFF = (255, 110, 150), (240, 240, 250), (145, 142, 160), (56, 52, 76)
DIM2, DIM3 = (100, 98, 118), (72, 70, 90)
AMB, RING, RED = (255, 190, 70), (84, 64, 30), (255, 80, 70)
SEL_BG = (COLOR_ACC[0] // 5, COLOR_ACC[1] // 5, COLOR_ACC[2] // 5)

def make_disc(art):
    global D0, frames, COLOR_ACC, COLOR_FG, ART, SEL_BG
    ART = art
    D = pygame.Surface((80, 80), pygame.SRCALPHA)
    pygame.draw.circle(D, (20, 20, 26), (40, 40), 39)
    pygame.draw.circle(D, (36, 36, 44), (40, 40), 30, 1); pygame.draw.circle(D, (36, 36, 44), (40, 40), 34, 1)
    img = None; COLOR_ACC, COLOR_FG = (255, 110, 150), (240, 240, 250)
    if art and len(art) < 2000000:
        try:
            raw = pygame.image.load(io.BytesIO(art)).convert_alpha()
            if CFG["thm"]:
                c = pygame.transform.scale(raw, (1, 1)).get_at((0, 0))
                r, g, b = min(255, c.r + 30), min(255, c.g + 30), min(255, c.b + 30)
                COLOR_ACC, COLOR_FG = (r, g, b), (min(255, r + 120), min(255, g + 120), min(255, b + 120))
            img = pygame.transform.smoothscale(raw, (48, 48))
            img.blit(MASK, (0, 0), special_flags=pygame.BLEND_RGBA_MULT); D.blit(img, (16, 16))
        except Exception: img = None
    if img is None: pygame.draw.circle(D, COLOR_ACC, (40, 40), 20); pygame.draw.circle(D, BGC, (40, 40), 4)
    pygame.draw.circle(D, COLOR_FG, (40, 8), 2)
    D0, frames = D, [None] * 72
    SEL_BG = (COLOR_ACC[0] // 5, COLOR_ACC[1] // 5, COLOR_ACC[2] // 5)

def frame(a):
    if frames[a] is None: frames[a] = pygame.transform.rotate(D0, -a * 5).convert_alpha()
    return frames[a]

cache = {}
def T(s, col, font=F, max_w=0):                              # tra cache trước; max_w nằm trong key nên không đo chữ mỗi frame
    k = (s, col, id(font), max_w)
    r = cache.get(k)
    if r: return r
    t = s
    if max_w > 0 and font.size(t)[0] > max_w:
        while t and font.size(t + "...")[0] > max_w: t = t[:-1]
        t += "..."
    if len(cache) > 800:
        for _k in list(cache)[:200]: del cache[_k]
    r = cache[k] = font.render(t, True, col).convert_alpha()
    return r

def mmss(s): s = int(s); return "%02d:%02d" % (s // 60, s % 60)

def wrap(s, w, n=4):
    out, c = [], ""
    for ch in s:
        if F.size(c + ch)[0] > w: out.append(c); c = ch
        else: c += ch
    return (out + [c])[:n]

NB = 38
BX = [8 + i * 8 for i in range(NB)]
BW = [1.0 - abs(i - 19) / 40.0 for i in range(NB)]
wc = {}
def wrapw(s, font, w, n=2):
    k = (s, id(font))
    if k in wc: return wc[k]
    if len(wc) > 400:
        for _k in list(wc.keys())[:100]: del wc[_k]
    out, c = [], ""
    for wd in s.split():
        t = c + " " + wd if c else wd
        if font.size(t)[0] <= w: c = t
        else:
            if c: out.append(c)
            c = wd
    out.append(c)
    if len(out) > n: out = out[:n]; out[-1] += "..."
    wc[k] = out; return out

playing = paused = False; vol_t = -9999; hold = {}; used = set()
title = artist = MSG = lsrc = ""; length = rg = pos = 0.0; st_t = 0; sl = 0
lsync = lymode = info = lbusy = False; lyr = []; ltimes = []; minfo = info_rows = None
TOAST = ""
last_scan = None
KBACK = (getattr(pygame, "K_AC_BACK", -1), pygame.K_ESCAPE); back_t = 0
pend, got, fails, lastpl, toast_t, page = True, False, 0, 0, 0, 0
bars, tgt = [0.0] * NB, [0.0] * NB
make_disc(None)
DBG = pygame.Surface((110, 36), pygame.SRCALPHA); DBG.fill((0, 0, 0, 180)); dbg_t, dbg_s = 0, None

def setvol(): tx("vol", v=min(1.0, vol * 10 ** (rg / 20)))

def build_info():
    global info_rows
    m = minfo
    if not m: return
    rows = [("Tên", title), ("Nghệ sĩ", artist), ("Album", m["album"]), ("Năm", m["date"]), ("Thể loại", m["genre"]),
            ("Thời lượng", mmss(length) if length else ""),
            ("Định dạng", " · ".join(x for x in (m["fmt"], "%d kbps" % (m["br"] // 1000) if m["br"] else "") if x)),
            ("Lời", (lsrc + (" · đồng bộ" if lsync else "")) if lyr else (lsrc or "không có"))]
    rows = [(a, b) for a, b in rows if b]
    for i, ln in enumerate(wrap(curp, 220, 2)): rows.append(("Đường dẫn" if i == 0 else "", ln))
    info_rows = rows

def change():
    global curp, title, artist, length, rg, lsync, lyr, ltimes, MSG, lbusy, lsrc, minfo, info_rows, lastpos
    gc.collect()                                             # GC đã tắt trong vòng lặp: dọn khi đổi bài
    if not N: return
    curp = tracks[cur]; r = lib[cur]
    title, artist, length, rg, MSG = names[cur], r[2], r[3], 0.0, ""
    lsync, lyr, ltimes, lsrc, lbusy, minfo, info_rows, lastpos = False, [], [], "", True, None, None, 0
    make_disc(None); save()
    threading.Thread(target=bg_meta, args=(curp, artist, names[cur]), daemon=True).start()

def set_lib(rows):
    global tracks, names, lib, idx, N, cur, sel, ALL
    old = curp; selp = tracks[sel] if N and sel < N else ""; ALL = rows
    lib = [r for r in rows if r[0] not in BAD and (not CFG["fav"] or r[0] in FAV)]; tracks = [r[0] for r in lib]
    names = [r[1] or os.path.splitext(os.path.basename(r[0]))[0] for r in lib]
    idx = {t: i for i, t in enumerate(tracks)}; N = len(tracks)
    cur = idx.get(old, min(cur, max(N - 1, 0))); sel = idx.get(selp, cur)
    try: json.dump([[r[0], names[i], r[2]] for i, r in enumerate(lib)], open(PL, "w"))
    except OSError: pass
    tx("pl"); setvol()
    if N and (tracks[cur] != old or not title): change()

def drop_bad(p):
    global fails
    if p in BAD or p not in idx: return
    fails += 1
    if fails > 3: return
    i = idx[p]; BAD.add(p); toast("Không phát được, đã ẩn: " + names[i][:24], 2500)
    set_lib(ALL)
    if N: tx("play", i=i % N)

def send_mode(): tx("mode", sh=int(bool(CFG["shuf"])), rp=int(CFG["rep"]))

def toast(s, ms=1600):
    global TOAST, toast_t
    TOAST = s; toast_t = pygame.time.get_ticks() + ms

def toggle_fav(p):
    FAV.symmetric_difference_update({p})
    try: json.dump(sorted(FAV), open(FF, "w"))
    except OSError: pass
    toast("Đã thêm vào yêu thích" if p in FAV else "Đã bỏ yêu thích")
    if CFG["fav"] and p not in FAV: set_lib(ALL)

def set_favfilter(v):
    old = curp; CFG["fav"] = v; set_lib(ALL); save()
    if N and playing and old != curp: tx("play", i=cur)
    toast("Chỉ hiện yêu thích" if v else "Hiện tất cả bài")

def poll(now):
    global playing, paused, pos, st_t, sl, cur, sel, length, MSG, pend, got, fails, lastpl
    changed = False; last = None
    for d in recv_all():
        if "e" in d:
            if d.get("bad"): drop_bad(d["bad"]); changed = True
            if MSG != d["e"]: MSG = d["e"]; changed = True
        else: last = d
        
    if not got:
        if now - lastpl > 1000: lastpl = now; tx("pl"); send_mode()
        if now > 6000 and not MSG: 
            MSG = "Không nối được service"
            changed = True
    elif MSG == "Không nối được service": 
        MSG = ""
        changed = True
        
    if last:
        if not got: changed = True
        got = True
        
        # Chỉ báo "cần vẽ lại" nếu trạng thái thực sự đổi
        new_play, new_pause = bool(last["pl"]), bool(last["pa"])
        if new_play != playing or new_pause != paused: changed = True
        if last["sl"] != sl: changed = True
        
        playing, paused, pos, st_t, sl = new_play, new_pause, last["p"], now, last["sl"]
        if playing: fails = 0
        if last["d"] > 0 and last["d"] != length: length = last["d"]; changed = True
        
        t = last["t"]
        if t and t != curp and t in idx: 
            cur = sel = idx[t]; change(); changed = True
            
    if pend and got and N and curp:
        pend = False
        if not playing: tx("play", i=cur, s=rpos if 0 < rpos < length - 5 else 0)
        changed = True
        
    return changed


def drain():
    global lsync, lyr, ltimes, rg, length, title, artist, lbusy, lsrc, minfo, last_scan
    changed = False
    while True:
        try: m = ev.get_nowait()
        except queue.Empty: break
        changed = True
        if m[0] == "lib": set_lib(m[1])
        elif m[0] == "toast": toast(m[1], m[2] if len(m) > 2 else 1600)
        elif m[0] == "scanned":
            n = m[1]
            if n == 0: toast("Không tìm thấy nhạc", 2500)
            elif last_scan is None: toast("Đã quét xong: %d bài" % n, 2200)
            elif n != last_scan: toast("Thư viện: %d bài (%+d)" % (n, n - last_scan), 2200)
            last_scan = n
        elif m[0] == "meta" and m[1] == curp:
            mi = m[2]; rg = mi["rg"]; lsync, lyr = m[3][0], m[3][1]; lsrc = m[3][2]
            ltimes = [x[0] for x in lyr] if lsync else []; lbusy = False
            if mi["title"]: title = mi["title"]
            if mi["artist"] and not artist: artist = mi["artist"]
            if mi["len"] and not length: length = mi["len"]
            minfo = mi; build_info(); make_disc(mi["art"]); setvol()
            sr = m[3][2]
            if sr.startswith("lỗi mạng"): toast("Lỗi tải lyric: " + sr[10:], 3000)
            elif not lyr: toast("Không tìm thấy lyric hợp lệ", 2200)
            elif sr == "lrclib.net": toast("Đã tải lyric" + ("" if lsync else " (không đồng bộ)"), 2000)
    return changed

try: set_lib(json.load(open(CACHE)))
except Exception: pass
threading.Thread(target=scanner, daemon=True).start()
tx("pl"); setvol(); send_mode()

# ====================================================================
# VÒNG LẶP CHÍNH (TỐI ƯU SIÊU NHẸ)
# ====================================================================
clock, run = pygame.time.Clock(), True
get_ticks, get_events, blit = pygame.time.get_ticks, pygame.event.get, S.blit
draw_rect, draw_circle, draw_poly, set_clip = pygame.draw.rect, pygame.draw.circle, pygame.draw.polygon, S.set_clip
rd = random.random
ang, t_save = 0.0, 0
svc_lines, svc_t = [], -9999
SLP = (0, 15, 30, 60); slp_i = 0
Y0, BM = 36, 26
DCY, BY, TY, AY, PY, LY0 = Y0 + 46, Y0 + 112, Y0 + 126, Y0 + 148, Y0 + 182, Y0 + 216
LN = (H - LY0 - BM) // 22
LT, LB = Y0 + 48, H - BM - 62
SLOT = 40; LCY = (LT + LB - SLOT) // 2; LSIDE = min(5, ((LB - LT) // SLOT - 1) // 2)

st_last_hash, st_cached = None, ""
def status():                                                # Caching logic hash tránh build list string
    global st_last_hash, st_cached
    h = (CFG["shuf"], CFG["rep"], CFG["fav"], sl)
    if h != st_last_hash:
        s = []
        if h[0]: s.append("SHUF")
        if h[1] == 2: s.append("REP 1")
        elif h[1] == 0: s.append("NO REP")
        if h[2]: s.append("FAV")
        if h[3]: s.append("ZZ %dm" % h[3])
        st_cached = "  ".join(s)
        st_last_hash = h
    return st_cached

def heart(x, y, col):
    draw_circle(S, col, (x - 2, y), 2); draw_circle(S, col, (x + 2, y), 2); draw_poly(S, col, [(x - 4, y + 1), (x + 4, y + 1), (x, y + 6)])

def svc_log():
    try: return open(os.path.join(DATA, "svc.log"), encoding="utf-8", errors="ignore").read()[-500:].strip().split("\n")[-4:]
    except OSError: return ["(chưa có svc.log: service chưa chạy)"]

is_animating_text = False
def marq(s, col, font, x, y, w, ctr=False):
    global is_animating_text
    sf = T(s, col, font); tw = sf.get_width()
    if tw <= w: blit(sf, (x + (w - tw) // 2 if ctr else x, y)); return
    is_animating_text = True                                 # Yêu cầu main loop tiếp tục redrawing
    ov = tw - w; ph = (now / 1000.0) % (ov / 40.0 + 2.4)
    o = S.get_clip(); S.set_clip(o.clip((x, y, w, sf.get_height())))
    blit(sf, (x - int(max(0.0, min(ov, (ph - 1.2) * 40))), y)); S.set_clip(o)

def selbar(yb):
    draw_rect(S, SEL_BG, (8, yb, 304, 22), border_radius=4)
    hint = T("A: phát", AMB); blit(hint, (306 - hint.get_width(), yb + 4))
    marq("%d/%d  %s" % (sel + 1, N, names[sel]), COLOR_FG, F, 20, yb + 4, 306 - hint.get_width() - 28)

def centered(surf, y): blit(surf, (160 - surf.get_width() // 2, y))
def bar(x, y, w, frac, col):
    draw_rect(S, COLOR_OFF, (x, y, w, 3), border_radius=1)
    pw = int(w * max(0.0, min(1.0, frac))); draw_rect(S, col, (x, y, pw, 3), border_radius=1); draw_circle(S, COLOR_FG, (x + pw, y + 1), 4)

gc.collect(); gc.disable()                                   # vòng lặp ít tạo vòng tham chiếu: tắt GC để khỏi giật bất chợt
while run:
    now = get_ticks()
    
    # Adaptive Framerate tiết kiệm pin tối đa
    fps = 10
    if pad.ptr: fps = 60
    elif playing and not paused: fps = 20 if page == 0 else (24 if lsync else 15)
    elif is_animating_text or any(b > 0.5 for b in bars): fps = 20
    elif toast_t and now <= toast_t: fps = 30
    dt = clock.tick(fps)
    
    force_dirty = False                                      # Đánh dấu cần redraw màn hình
    for e in get_events():
        force_dirty = True
        if e.type == pygame.QUIT: run = False
        elif e.type == pygame.KEYDOWN and e.key in KBACK:
            if page: page = 0; lymode = info = False
            elif now < back_t: tx("quit"); run = False
            else: back_t = now + 2000; toast("Nhấn Back lần nữa để thoát và tắt nhạc", 2000)
        pad.event(e)
        
    if poll(now): force_dirty = True
    if drain(): force_dirty = True
    if toast_t and now > toast_t: toast_t = 0; force_dirty = True
        
    pad.update(); p = set(pad.pressed)
    if p or pad.held or pad.released: force_dirty = True
    
    on = playing and not paused
    
    # Zero-Render Idle Optimization (BỎ QUA TOÀN BỘ PHA VẼ NẾU KHÔNG CẦN THIẾT)
    if not (force_dirty or on or is_animating_text or (toast_t and now <= toast_t) or pad.ptr or any(b > 0.5 for b in bars) or not got or (now - vol_t < 1250)):
        continue
        
    is_animating_text = False                                # Reset cờ cuộn chữ

    pad.st["A"] = 2 if on else 0
    el = (pos + (now - st_t) / 1000.0 if on else pos) if playing else 0.0
    if length: el = min(el, length)
    if playing: lastpos = el
    if on and now - t_save > 5000: t_save = now; save()

    if "S" in p: hold["S"] = now; used.discard("S")
    if "S" in pad.held and "S" not in used and now - hold.get("S", now) > 500:
        used.add("S")
        if page == 2: tx("quit"); run = False
        else: set_favfilter(not CFG["fav"])
    if "S" in pad.released and "S" not in used: page = (page + 1) % 3; lymode, info = page == 1, page == 2

    for k in ("A", "B", "C"):
        if k in p: hold[k] = now; used.discard(k)
        if k in pad.held and k not in used and now - hold.get(k, now) > 500:
            used.add(k)
            if k == "A":
                if N: toggle_fav(tracks[sel])
            elif k == "B": CFG["shuf"] = not CFG["shuf"]; send_mode(); save(); toast("Ngẫu nhiên: " + ("BẬT" if CFG["shuf"] else "TẮT"))
            else: CFG["rep"] = (CFG["rep"] + 1) % 3; send_mode(); save(); toast("Lặp lại: " + ("TẮT", "TẤT CẢ", "1 BÀI")[CFG["rep"]])
        if k in pad.released and k not in used:
            if k == "A":
                if N:
                    if not got: toast("Service chưa nối (xem trang Thông tin)")
                    tx("toggle") if (playing and sel == cur) else tx("play", i=sel)
            else: tx("next" if k == "B" else "prev")
            
    if "down" in p and N: sel = (sel + 1) % N
    if "up" in p and N: sel = (sel - 1) % N
    for k, dv in (("up", -1), ("down", 1)):
        if k in p: hold[k] = hold[k + "r"] = now
        if k in pad.held and N and k in hold and now - hold[k] > 350 and now - hold[k + "r"] > 70:
            hold[k + "r"] = now; sel = (sel + dv * (10 if now - hold[k] > 1500 else 1)) % N
    for k, dv in (("left", -1), ("right", 1)):
        if k in p: hold[k] = now; used.discard(k)
        if page == 2:
            if k in p: slp_i = (slp_i + dv) % 4; tx("sleep", m=SLP[slp_i]); toast(("Hẹn giờ ngủ: %d phút" % SLP[slp_i]) if SLP[slp_i] else "Đã tắt hẹn giờ ngủ")
            continue
        if k in pad.held and now - hold.get(k, now) > 200: used.add(k); vol = min(1.0, max(0.0, vol + dv * 0.02)); setvol(); vol_t = now
        if k in pad.released:
            if k not in used: tx("seek", d=10 * dv)
            else: save()

    blit(BG, (0, 0))
    if on: ang = (ang + dt * 0.06) % 72

    if N and lymode:
        marq(title, COLOR_FG, FB, 12, Y0, 296, True)
        if artist: marq(artist, AMB, F, 12, Y0 + 20, 296, True)
        if not lyr:
            msg = "Đang tìm lời bài hát" + "." * (1 + now // 400 % 3) if lbusy else "Không có lời bài hát"
            centered(T(msg, COLOR_ACC if lbusy else COLOR_DIM), LCY)
        else:
            n = len(lyr); y_off = 0
            if lsync:
                i = max(0, bisect.bisect_right(ltimes, el) - 1)
                if i < n - 1:
                    dur = ltimes[i + 1] - ltimes[i]
                    if dur > 0:
                        pg = (el - ltimes[i]) / dur
                        if pg > 0.7: pr = (pg - 0.7) / 0.3; y_off = pr * pr * (3.0 - 2.0 * pr) * SLOT
            else: i = min(n - 1, int(el / length * n)) if length else 0
            set_clip((0, LT, W, LB - LT))
            for k in range(-LSIDE, LSIDE + 1):
                j = i + k
                if 0 <= j < n:
                    ak = abs(k)
                    if k == 0: col, ft = COLOR_FG, FB
                    elif ak == 1: col, ft = COLOR_ACC, F
                    else: col, ft = (DIM2 if ak == 2 else DIM3), F
                    ls = wrapw(lyr[j][1] or " ", ft, 300); lh = ft.get_linesize()
                    fy = int(LCY + k * SLOT - y_off) + (SLOT - lh * len(ls)) // 2
                    for q, ln in enumerate(ls): centered(T(ln or " ", col, ft, max_w=300), fy + q * lh)
            set_clip(None)
        if sel != cur: selbar(H - BM - 56)
        bar(20, H - BM - 30, 280, el / length if length else 0, COLOR_ACC)
        blit(T(mmss(el), AMB), (20, H - BM - 22))
        if length: t1 = T(mmss(length), COLOR_DIM); blit(t1, (300 - t1.get_width(), H - BM - 22))

    elif N:
        d = frame(int(ang)); blit(d, d.get_rect(center=(160, DCY)))
        draw_circle(S, RING, (160, DCY), 44, 1)
        st_ = status()
        if st_: blit(T(st_, AMB), (20, Y0 - 18))
        
        beat_force = (vol * (1.0 + (rg / 20.0))) if on else 0.0
        for i in range(NB):
            if on:
                if rd() < 0.35: tgt[i] = int((4 + rd() * 20) * BW[i] * beat_force)
            else: tgt[i] = 0
            
            diff = tgt[i] - bars[i]
            if diff: bars[i] += diff * 0.4
            
            h = int(bars[i])
            if h > 0:
                draw_rect(S, COLOR_OFF, (BX[i], BY - h, 2, h))
                if on and h > 8: draw_rect(S, COLOR_ACC, (BX[i], BY - h, 2, 2))
                
        marq(title, COLOR_FG, FB, 12, TY, 296, True)
        if curp in FAV: heart(300, Y0 - 12, COLOR_ACC)
        if MSG or artist: marq(MSG or artist, COLOR_ACC if MSG else AMB, F, 12, AY, 296, True)
        showv = now - vol_t < 1200
        bar(20, PY, 280, vol if showv else (el / length if length else 0), COLOR_FG if showv else COLOR_ACC)
        if showv: centered(T("Âm lượng %d%%" % int(vol * 100), COLOR_FG), PY + 8)
        else:
            blit(T(mmss(el), AMB), (20, PY + 8)); centered(T("%d / %d" % (cur + 1, N), COLOR_DIM), PY + 8)
            if length: t1 = T(mmss(length), COLOR_DIM); blit(t1, (300 - t1.get_width(), PY + 8))
            
        top = max(0, min(sel - LN // 2, N - LN))
        for ri in range(min(LN, N)):
            i = top + ri; y = LY0 + ri * 22
            if i == sel: draw_rect(S, SEL_BG, (8, y - 1, 300, 21), border_radius=4)
            if i == cur and playing: draw_poly(S, AMB, [(17, y + 4), (17, y + 12), (24, y + 8)])
            if i == sel: marq(names[i], COLOR_FG, FB, 30, y + 1, 250)
            else: blit(T(names[i], COLOR_DIM, F, max_w=250), (30, y + 1))
            if tracks[i] in FAV: heart(298, y + 6, COLOR_ACC)
            
        if N > LN:
            trk = LN * 22; th = max(10, trk * LN // N)
            draw_rect(S, COLOR_OFF, (312, LY0, 2, trk)); draw_rect(S, COLOR_ACC, (312, LY0 + (trk - th) * top // (N - LN), 2, th))
    else:
        centered(T("Chưa có bài yêu thích" if CFG["fav"] and ALL else scan_status, COLOR_DIM), H // 2 - 8)

    if info:
        blit(OVL, (0, 0)); centered(T("THÔNG TIN BÀI HÁT", COLOR_FG, FB), Y0)
        y = Y0 + 32
        if not info_rows: centered(T("Đang đọc thẻ nhạc...", COLOR_DIM), Y0 + 40)
        else:
            for lb, val in info_rows:
                if lb: blit(T(lb, COLOR_DIM), (14, y))
                marq(val, COLOR_FG, F, 92, y, 216); y += 18
        yy = H - BM - 50
        if N and sel != cur: selbar(yy - 26)
        yl = min(y + 6, yy - 30)
        blit(T("Service: " + ("đã nối" if got else "CHƯA NỐI"), AMB if got else COLOR_ACC, FB), (14, yl)); yl += 18
        if not got:
            if now - svc_t > 1000: svc_t = now; svc_lines = svc_log()
            for ln in svc_lines[-2:]:
                if yl + 13 <= yy - 28: blit(T(wrap(ln, 290, 1)[0] or " ", DIM2), (14, yl)); yl += 13
        blit(T("Hẹn giờ ngủ", COLOR_DIM), (14, yy)); blit(T("%d phút" % sl if sl else "TẮT", AMB), (92, yy))
        r_ = T("trái/phải", DIM2); blit(r_, (W - 14 - r_.get_width(), yy))
        centered(T("Giữ A thích · B ngẫu nhiên · C lặp lại", DIM2), yy + 18)
        centered(T("Giữ S: thoát & dừng nhạc", DIM2), yy + 34)

    if toast_t:
        tt = T(TOAST, (16, 16, 24), FB, max_w=288); rc = tt.get_rect(center=(160, H - BM - 16))
        draw_rect(S, AMB, rc.inflate(18, 8), border_radius=8); blit(tt, rc)

    if CFG["dbg"]:                                           # render thẳng (không qua T) để không làm phình cache
        if now - dbg_t > 500:
            dbg_t = now
            dbg_s = (F.render("FPS %d/%d" % (clock.get_fps(), fps), True, (0, 255, 100)),
                     F.render("C %d|%d" % (len(cache), len(wc)), True, (0, 255, 255)))
        if dbg_s: blit(DBG, (W - 110, 0)); blit(dbg_s[0], (W - 105, 4)); blit(dbg_s[1], (W - 105, 20))

    pad.present()

save(); pygame.quit(); sys.exit()
