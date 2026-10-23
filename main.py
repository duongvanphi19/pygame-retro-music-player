"""main.py - UI trình nghe nhạc Pygame (portrait, lấp đầy màn hình). Cần touchpad.py cạnh file này.
APK: phát nhạc ở service/main.py. Pydroid3: tự chuyển chế độ dev (phát bằng pygame.mixer trong UI)."""
import pygame, os, sys, json, io, base64, re, bisect, threading, time, socket, queue, hashlib, random
import urllib.request, urllib.parse

try: import mutagen, mutagen.flac
except ImportError: mutagen = None

try:                                                         # có class của p4a => đang chạy trong APK; Pydroid3 thì không
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
ev = queue.Queue()                                           # thread nền -> vòng chính (không đụng global từ thread)
kick = threading.Event()                                     # đánh thức bộ quét ngay
try: BAD = set(json.load(open(BADF)))                        # bài phát lỗi: không liệt kê nữa
except Exception: BAD = set()

# ====================================================================
# BACKEND: service (APK, UDP localhost) hoặc Dev (Pydroid3, trong tiến trình)
# ====================================================================
class Dev:
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
            if pygame.mixer.get_init(): s.bad = s.curp       # mixer hỏng thì không đổ lỗi cho bài hát

    def cmd(s, d):
        c, m = d["cmd"], pygame.mixer.music
        try:
            if c == "pl":
                s.rows = json.load(open(PL)); ps = [r[0] for r in s.rows]
                if s.curp in ps: s.cur = ps.index(s.curp)
            elif c == "play": s.load(d["i"], d.get("s", 0))
            elif c == "next": s.load(s.cur + 1)
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

    def state(s):
        m = pygame.mixer.music
        if s.ready and not s.paused and not m.get_busy(): s.load(s.cur + 1)       # hết bài -> bài kế
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

def boot():                                                  # xin quyền + khởi động service (đã chạy thì bị bỏ qua)
    from android.permissions import request_permissions
    act = autoclass("org.kivy.android.PythonActivity").mActivity
    request_permissions(["android.permission.READ_MEDIA_AUDIO", "android.permission.READ_EXTERNAL_STORAGE",
                         "android.permission.POST_NOTIFICATIONS"])
    autoclass(act.getPackageName() + ".ServicePlayer").start(act, "")
if APK: boot()

# ====================================================================
# MÀN HÌNH: canvas cao bằng đúng tỉ lệ màn hình => không còn dải đen trên/dưới
# ====================================================================
pygame.display.init(); pygame.font.init()                    # không pygame.init(): bỏ mixer trong UI (APK)
from touchpad import TouchPad
W, PH = 320, 112
class Pad(TouchPad):
    def _want(s): return False, s.side                       # khoá chế độ dọc, bỏ layout ngang có 2 dải bên
def fit_h(sw, sh): return max(400, min(720, round(W * sh / sw) - PH))
BTNS = (("C", "", 160, 56), ("A", "", 220, 56), ("B", "", 280, 56), ("S", "", 280, 10))
sw, sh = pygame.display.get_desktop_sizes()[0]
pad = Pad(W, fit_h(sw, sh), buttons=BTNS, touch=True)
if not APK:                                                  # Pydroid: cửa sổ thật khác màn hình (thanh trạng thái) -> khớp lại
    ww, wh = pygame.display.get_surface().get_size()
    if abs(fit_h(ww, wh) - pad.h) > 3: pad = Pad(W, fit_h(ww, wh), buttons=BTNS, touch=True)
S, H = pad.screen, pad.h

def mkfont(sz, bold=False):                                  # font hệ thống Android có đủ dấu tiếng Việt
    for p in ("/system/fonts/Roboto-Regular.ttf", "/system/fonts/NotoSans-Regular.ttf", "/system/fonts/DroidSans.ttf"):
        if os.path.exists(p): f = pygame.font.Font(p, sz); f.set_bold(bold); return f
    return pygame.font.SysFont("dejavusans,arial", sz, bold=bold)
F, FB = mkfont(12), mkfont(14, True)

# ====================================================================
# THƯ VIỆN NHẠC: MediaStore (APK) / os.walk (dev) + cache JSON
# ====================================================================
tracks, names, lib, idx, N = [], [], [], {}, 0               # lib: [[path, title, artist, giây], ...]
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
        while not any(check_permission(p) for p in P): scan_status = "Chờ cấp quyền..."; time.sleep(1)
    while True:
        scan_status = "Đang quét..."
        try:
            rows = [r for r in (rows_mediastore() if APK else rows_walk()) if r[0] not in BAD]
            if rows and rows != lib:                         # quét rỗng (chưa có quyền/thẻ chưa gắn) thì giữ danh sách cũ
                json.dump(rows, open(CACHE, "w")); ev.put(("lib", rows))
            scan_status = "Đã nạp %d bài" % len(rows)
        except Exception as e: scan_status = "Quét lỗi: " + str(e)[:24]
        kick.wait(60); kick.clear()

# ====================================================================
# LYRIC + METADATA (thread nền)
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

def find_lyrics(path, emb):                                  # -> (có_thời_gian, dòng, nguồn)
    for f, src in ((os.path.splitext(path)[0] + ".lrc", ".lrc cạnh bài"), (lrc_path(path), "đã tải về")):
        try: return parse_lyrics(open(f, encoding="utf-8-sig", errors="ignore").read()) + (src,)
        except OSError: pass
    return parse_lyrics(emb) + ("nhúng trong file",) if emb else (False, [], "")

def fetch_lyrics(p, a, t):
    try:
        url = "https://lrclib.net/api/get?artist_name=%s&track_name=%s" % (urllib.parse.quote(a), urllib.parse.quote(t))
        req = urllib.request.Request(url, headers={"User-Agent": "MinimalistPygamePlayer/5.0"})
        with urllib.request.urlopen(req, timeout=4) as r: d = json.loads(r.read().decode("utf-8"))
        txt = d.get("syncedLyrics") or d.get("plainLyrics")
        if txt:
            open(lrc_path(p), "w", encoding="utf-8").write(txt); return parse_lyrics(txt) + ("lrclib.net",)
    except Exception: pass

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
    try:                                                     # thẻ chuẩn hoá cho mọi định dạng
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
        if not ly[1] and a and t: ly = fetch_lyrics(p, a, t) or ly
    except Exception: pass
    ev.put(("meta", p, m or M0(), ly or (False, [], "")))

# ====================================================================
# TRẠNG THÁI + ĐĨA XOAY
# ====================================================================
cur = sel = 0; vol = 0.7; curp = ""; rpos = 0.0
CFG = {"thm": True, "dbg": False}
try:
    st = json.load(open(SF)); vol = float(st["v"]); curp = st.get("t", ""); rpos = float(st.get("p", 0))
    CFG.update(st.get("cfg", {}))
except Exception: pass
lastpos = 0.0

def save():
    try: json.dump({"t": curp, "v": round(vol, 2), "p": int(lastpos), "cfg": CFG}, open(SF, "w"))
    except Exception: pass

BGC = (12, 12, 16)                                           # trùng màu dải phím => liền mạch
BG = pygame.Surface((W, H)).convert(); BG.fill(BGC)
MASK = pygame.Surface((48, 48), pygame.SRCALPHA); pygame.draw.circle(MASK, (255, 255, 255, 255), (24, 24), 24)
OVL = pygame.Surface((W, H), pygame.SRCALPHA); OVL.fill((10, 10, 14, 245))
frames = [None] * 72; D0 = None; ART = None
COLOR_ACC, COLOR_FG, COLOR_DIM, COLOR_OFF = (255, 110, 150), (240, 240, 250), (120, 120, 130), (30, 30, 40)
DIM2, DIM3 = (60, 60, 65), (40, 40, 44)

def make_disc(art):
    global D0, frames, COLOR_ACC, COLOR_FG, ART
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

def frame(a):
    if frames[a] is None: frames[a] = pygame.transform.rotate(D0, -a * 5).convert_alpha()
    return frames[a]

cache = {}
def T(s, col, font=F, max_w=0):
    if max_w > 0 and font.size(s)[0] > max_w:
        while s and font.size(s + "...")[0] > max_w: s = s[:-1]
        s += "..."
    k = (s, col, id(font))
    if k not in cache:
        if len(cache) > 240: cache.clear()
        cache[k] = font.render(s, True, col).convert_alpha()
    return cache[k]
def mmss(s): s = int(s); return "%02d:%02d" % (s // 60, s % 60)

def wrap(s, w, n=4):                                         # ngắt dòng theo bề rộng (đường dẫn dài)
    out, c = [], ""
    for ch in s:
        if F.size(c + ch)[0] > w: out.append(c); c = ch
        else: c += ch
    return (out + [c])[:n]

NB = 38
BX = [8 + i * 8 for i in range(NB)]
BW = [1.0 - abs(i - 19) / 40.0 for i in range(NB)]
playing = paused = False; vol_t = -9999; hold = {}; used = set()
title = artist = MSG = lsrc = ""; length = rg = pos = 0.0; st_t = 0; sl = 0
lsync = lymode = info = lbusy = False; lyr = []; ltimes = []; minfo = info_rows = None
pend, got, fails = True, False, 0                            # pend: tự phát bài trước đó khi mở app
bars, tgt = [0.0] * NB, [0.0] * NB
make_disc(None)
particles = [[random.randint(10, 310), random.randint(0, H), random.random() * 0.5 + 0.2, random.randint(1, 3)] for _ in range(25)]

def setvol(): tx("vol", v=min(1.0, vol * 10 ** (rg / 20)))

def build_info():                                            # dựng sẵn 1 lần khi có metadata, vẽ thì chỉ blit
    global info_rows
    m = minfo
    if not m: return
    try: sz = os.path.getsize(curp) / 1048576.0
    except OSError: sz = 0
    kh = "%.1f kHz" % (m["sr"] / 1000.0) if m["sr"] else ""
    rows = [("Tên", title), ("Nghệ sĩ", artist), ("Album", m["album"]), ("NS album", m["albumartist"]), ("Năm", m["date"]),
            ("Thể loại", m["genre"]), ("Track", m["track"]), ("Thời lượng", mmss(length) if length else ""),
            ("Định dạng", " · ".join(x for x in (m["fmt"], "%d bit" % m["bits"] if m["bits"] else "") if x)),
            ("Bitrate", "%d kbps" % (m["br"] // 1000) if m["br"] else ""),
            ("Lấy mẫu", " · ".join(x for x in (kh, "%d kênh" % m["ch"] if m["ch"] else "") if x)),
            ("Dung lượng", "%.1f MB" % sz if sz else ""), ("ReplayGain", "%+.1f dB" % m["rg"] if m["rg"] else ""),
            ("Bìa", "%d KB" % (len(m["art"]) // 1024) if m["art"] else "không có"),
            ("Lời", lsrc + (" · đồng bộ" if lsync else " · không đồng bộ") if lyr else "không có")]
    rows = [(a, b) for a, b in rows if b]
    for i, ln in enumerate(wrap(curp, 220)): rows.append(("Đường dẫn" if i == 0 else "", ln))
    info_rows = rows

def change():                                                # bài hiện tại đổi (do mình chọn hoặc service tự chuyển)
    global curp, title, artist, length, rg, lsync, lyr, ltimes, MSG, lbusy, lsrc, minfo, info_rows, lastpos
    if not N: return
    curp = tracks[cur]; r = lib[cur]
    title, artist, length, rg, MSG = names[cur], r[2], r[3], 0.0, ""
    lsync, lyr, ltimes, lsrc, lbusy, minfo, info_rows, lastpos = False, [], [], "", True, None, None, 0
    make_disc(None); save()
    threading.Thread(target=bg_meta, args=(curp, artist, names[cur]), daemon=True).start()

def set_lib(rows):
    global tracks, names, lib, idx, N, cur, sel
    old = curp; lib = [r for r in rows if r[0] not in BAD]; tracks = [r[0] for r in lib]
    names = [r[1] or os.path.splitext(os.path.basename(r[0]))[0] for r in lib]
    idx = {t: i for i, t in enumerate(tracks)}; N = len(tracks)
    cur = sel = idx.get(old, min(cur, max(N - 1, 0)))
    try: json.dump([[r[0], names[i], r[2]] for i, r in enumerate(lib)], open(PL, "w"))
    except OSError: pass
    tx("pl"); setvol()
    if N and (tracks[cur] != old or not title): change()

def drop_bad(p):                                             # bài lỗi: ẩn vĩnh viễn, tự nhảy bài kế
    global fails
    if p in BAD or p not in idx: return
    fails += 1
    if fails > 3: return                                     # lỗi hàng loạt (mất quyền, thẻ nhớ...) -> đừng ẩn nhầm cả thư viện
    i = idx[p]; BAD.add(p)
    try: json.dump(sorted(BAD), open(BADF, "w"))
    except OSError: pass
    set_lib(lib)
    if N: tx("play", i=i % N)

def poll(now):                                               # đọc hết gói, chỉ giữ trạng thái mới nhất
    global playing, paused, pos, st_t, sl, cur, sel, length, MSG, pend, got, fails
    last = None
    for d in recv_all():
        if "e" in d:
            if d.get("bad"): drop_bad(d["bad"])
            MSG = d["e"]
        else: last = d
    if last:
        got = True
        playing, paused, pos, st_t, sl = bool(last["pl"]), bool(last["pa"]), last["p"], now, last["sl"]
        if playing: fails = 0
        if last["d"] > 0: length = last["d"]
        t = last["t"]
        if t and t != curp and t in idx: cur = sel = idx[t]; change()
    if pend and got and N and curp:                          # mở app là phát ngay bài trước đó (nếu service chưa phát)
        pend = False
        if not playing: tx("play", i=cur, s=rpos if 0 < rpos < length - 5 else 0)

def drain():
    global lsync, lyr, ltimes, rg, length, title, artist, lbusy, lsrc, minfo
    while True:
        try: m = ev.get_nowait()
        except queue.Empty: break
        if m[0] == "lib": set_lib(m[1])
        elif m[0] == "meta" and m[1] == curp:
            mi = m[2]; rg = mi["rg"]; lsync, lyr = m[3][0], m[3][1]; lsrc = m[3][2]
            ltimes = [x[0] for x in lyr] if lsync else []; lbusy = False
            if mi["title"]: title = mi["title"]
            if mi["artist"] and not artist: artist = mi["artist"]
            if mi["len"] and not length: length = mi["len"]
            minfo = mi; build_info(); make_disc(mi["art"]); setvol()

try: set_lib(json.load(open(CACHE)))                         # hiện ngay danh sách đã nhớ, quét ngầm sau
except Exception: pass
threading.Thread(target=scanner, daemon=True).start()
tx("pl"); setvol()

# ====================================================================
# VÒNG LẶP CHÍNH
# ====================================================================
clock, run = pygame.time.Clock(), True
get_ticks, get_events, blit = pygame.time.get_ticks, pygame.event.get, S.blit
draw_rect, draw_circle, draw_poly, set_clip = pygame.draw.rect, pygame.draw.circle, pygame.draw.polygon, S.set_clip
randint, rd = random.randint, random.random
ui_state, set_idx, ang, t_save = 0, 0, 0.0, 0
SET_ITEMS = ["Màu nền bìa", "Thông số Debug", "Hẹn giờ ngủ", "Hiện lại bài lỗi", "Thoát & dừng nhạc"]
SLP = (0, 15, 30, 60); slp_i = 0
Y0 = 18                                                      # chừa vùng tai thỏ/thanh trạng thái
DCY, BY, TY, AY, PY, LY0 = Y0 + 46, Y0 + 112, Y0 + 126, Y0 + 148, Y0 + 182, Y0 + 216
LN = (H - LY0 - 6) // 22                                     # số dòng danh sách hiển thị
LT, LB = Y0 + 48, H - 44                                     # vùng lời bài hát
LCY = (LT + LB) // 2 - 12; LSIDE = min(7, (LB - LT) // 52)

def centered(surf, y): blit(surf, (160 - surf.get_width() // 2, y))
def bar(x, y, w, frac, col):
    draw_rect(S, COLOR_OFF, (x, y, w, 3), border_radius=1)
    pw = int(w * max(0.0, min(1.0, frac))); draw_rect(S, col, (x, y, pw, 3), border_radius=1); draw_circle(S, COLOR_FG, (x + pw, y + 1), 4)

while run:
    now = get_ticks(); dt = clock.get_time()
    for e in get_events():
        if e.type == pygame.QUIT: run = False                # thoát UI, nhạc vẫn chạy nhờ service
        pad.event(e)
    poll(now); drain()
    pad.update(); p = set(pad.pressed)
    on = playing and not paused
    pad.st["A"] = 2 if on else 0
    el = (pos + (now - st_t) / 1000.0 if on else pos) if playing else 0.0
    if length: el = min(el, length)
    if playing: lastpos = el
    if on and now - t_save > 5000: t_save = now; save()     # nhớ vị trí phát

    if info and p: info = False; used |= p; p = set()        # chạm phím bất kỳ để đóng bảng thông tin
    if "S" in p: ui_state = 1 - ui_state; set_idx = 0

    if ui_state == 1:
        if "down" in p: set_idx = (set_idx + 1) % 5
        if "up" in p: set_idx = (set_idx - 1) % 5
        if "A" in p or "right" in p or "left" in p:
            if set_idx == 0: CFG["thm"] = not CFG["thm"]; make_disc(ART)
            elif set_idx == 1: CFG["dbg"] = not CFG["dbg"]
            elif set_idx == 2: slp_i = (slp_i + 1) % 4; tx("sleep", m=SLP[slp_i])
            elif set_idx == 3 and "A" in p:
                BAD.clear(); fails = 0; kick.set()
                try: os.remove(BADF)
                except OSError: pass
            elif set_idx == 4 and "A" in p: tx("quit"); run = False
            save()
    else:
        if "A" in p and N: tx("toggle") if (playing and sel == cur) else tx("play", i=sel)
        for k in ("B", "C"):                                 # chạm = chuyển bài; giữ 0.5s: B = lời bài hát, C = thông tin bài
            if k in p: hold[k] = now; used.discard(k)
            if k in pad.held and k not in used and now - hold.get(k, now) > 500:
                used.add(k)
                if k == "B": lymode = not lymode
                else: info = True
            if k in pad.released and k not in used: tx("next" if k == "B" else "prev")
        if "down" in p and N: sel = (sel + 1) % N
        if "up" in p and N: sel = (sel - 1) % N
        for k, dv in (("left", -1), ("right", 1)):
            if k in p: hold[k] = now; used.discard(k)
            if k in pad.held and now - hold.get(k, now) > 200: used.add(k); vol = min(1.0, max(0.0, vol + dv * 0.02)); setvol(); vol_t = now
            if k in pad.released:
                if k not in used: tx("seek", d=10 * dv)
                else: save()

    blit(BG, (0, 0))
    if on: ang = (ang + dt * 0.06) % 72                      # theo thời gian, không phụ thuộc fps

    if N and lymode:
        # ---------------- MÀN HÌNH LỜI BÀI HÁT ----------------
        for q in particles:
            q[1] -= q[2]
            if q[1] < 0: q[0], q[1], q[2] = randint(10, 310), H, rd() * 0.5 + 0.2
            draw_circle(S, COLOR_ACC, (int(q[0]), int(q[1])), q[3])
        centered(T(title, COLOR_FG, FB, max_w=296), Y0)
        if artist: centered(T(artist, COLOR_DIM, max_w=296), Y0 + 20)
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
                        if pg > 0.7: pr = (pg - 0.7) / 0.3; y_off = pr * pr * (3.0 - 2.0 * pr) * 26
            else: i = min(n - 1, int(el / length * n)) if length else 0
            set_clip((0, LT, W, LB - LT))
            for k in range(-LSIDE, LSIDE + 1):
                j = i + k
                if 0 <= j < n:
                    fy = int(LCY + k * 26 - y_off)
                    ak = abs(k)
                    if k == 0: col, ft = COLOR_FG, FB
                    elif ak == 1: col, ft = COLOR_ACC, F
                    else: col, ft = (DIM2 if ak == 2 else DIM3), F
                    centered(T(lyr[j][1] or " ", col, ft, max_w=300), fy)
            set_clip(None)
        bar(20, H - 30, 280, el / length if length else 0, COLOR_ACC)
        blit(T(mmss(el), COLOR_DIM), (20, H - 22))
        if length: t1 = T(mmss(length), COLOR_DIM); blit(t1, (300 - t1.get_width(), H - 22))

    elif N:
        # ---------------- MÀN HÌNH CHÍNH ----------------
        d = frame(int(ang)); blit(d, d.get_rect(center=(160, DCY)))
        beat_force = (vol * (1.0 + (rg / 20.0))) if on else 0.0
        for i in range(NB):
            if on:
                if rd() < 0.35: tgt[i] = int(randint(4, 24) * BW[i] * beat_force)
            else: tgt[i] = 0
            bars[i] += (tgt[i] - bars[i]) * 4 // 10
            h = int(bars[i])
            if h > 0:
                draw_rect(S, COLOR_OFF, (BX[i], BY - h, 2, h))
                if on and h > 8: draw_rect(S, COLOR_ACC, (BX[i], BY - h, 2, 2))
        centered(T(title, COLOR_FG, FB, max_w=296), TY)
        if MSG or artist: centered(T(MSG or artist, COLOR_ACC if MSG else COLOR_DIM, max_w=296), AY)
        showv = now - vol_t < 1200
        bar(20, PY, 280, vol if showv else (el / length if length else 0), COLOR_FG if showv else COLOR_ACC)
        if showv: centered(T("Âm lượng %d%%" % int(vol * 100), COLOR_FG), PY + 8)
        else:
            blit(T(mmss(el), COLOR_DIM), (20, PY + 8)); centered(T("%d / %d" % (cur + 1, N), COLOR_DIM), PY + 8)
            if length: t1 = T(mmss(length), COLOR_DIM); blit(t1, (300 - t1.get_width(), PY + 8))
        pygame.draw.line(S, COLOR_OFF, (12, LY0 - 6), (308, LY0 - 6))
        top = max(0, min(sel - LN // 2, N - LN))
        for ri in range(min(LN, N)):
            i = top + ri; y = LY0 + ri * 22
            if i == sel:
                draw_rect(S, (COLOR_ACC[0] // 5, COLOR_ACC[1] // 5, COLOR_ACC[2] // 5), (8, y - 1, 300, 21), border_radius=4)
                draw_rect(S, COLOR_ACC, (10, y + 4, 3, 10), border_radius=1)
            if i == cur and playing: draw_poly(S, COLOR_ACC, [(17, y + 4), (17, y + 12), (24, y + 8)])
            blit(T(names[i], COLOR_FG if i == sel else COLOR_DIM, FB if i == sel else F, max_w=268), (30, y + 1))
        if N > LN:                                           # thanh cuộn mảnh
            trk = LN * 22; th = max(10, trk * LN // N)
            draw_rect(S, COLOR_OFF, (315, LY0, 2, trk)); draw_rect(S, COLOR_ACC, (315, LY0 + (trk - th) * top // (N - LN), 2, th))
    else:
        centered(T(scan_status, COLOR_DIM), H // 2 - 8)

    if info:
        blit(OVL, (0, 0)); centered(T("THÔNG TIN BÀI HÁT", COLOR_FG, FB), Y0)
        if not info_rows: centered(T("Đang đọc thẻ nhạc...", COLOR_DIM), Y0 + 40)
        else:
            y = Y0 + 32
            for lb, val in info_rows:
                if lb: blit(T(lb, COLOR_DIM), (14, y))
                blit(T(val, COLOR_FG, max_w=216), (92, y)); y += 18
        centered(T("Chạm phím bất kỳ để đóng", DIM2), H - 22)

    if ui_state == 1:
        blit(OVL, (0, 0)); centered(T("CÀI ĐẶT", COLOR_FG, FB), Y0)
        for i, txt in enumerate(SET_ITEMS):
            if i == 2: v_str, is_on = ("%d Phút" % sl, True) if sl > 0 else ("TẮT", False)
            elif i == 3: v_str, is_on = ("%d bài" % len(BAD), len(BAD) > 0)
            elif i == 4: v_str, is_on = "", False
            else: is_on = CFG[("thm", "dbg")[i]]; v_str = "BẬT" if is_on else "TẮT"
            y = Y0 + 44 + i * 38
            if i == set_idx: draw_rect(S, (COLOR_ACC[0] // 5, COLOR_ACC[1] // 5, COLOR_ACC[2] // 5), (14, y - 6, 292, 30), border_radius=4)
            blit(T(txt, COLOR_ACC if i == set_idx else COLOR_DIM, FB if i == set_idx else F), (26, y))
            if v_str: vs = T(v_str, COLOR_FG if is_on else COLOR_DIM, FB); blit(vs, (W - 26 - vs.get_width(), y))

    if CFG["dbg"]:
        t1 = "FPS %d | %s | %dx%d | bad %d" % (int(clock.get_fps()), "APK" if APK else "DEV", W, H, len(BAD))
        blit(T(t1, (10, 10, 10)), (7, 3)); blit(T(t1, (0, 255, 128)), (6, 2))
        blit(T(scan_status, (10, 10, 10)), (7, 17)); blit(T(scan_status, (255, 200, 0)), (6, 16))

    pad.present()
    clock.tick(60 if (pad.ptr or ui_state == 1) else 30)     # rảnh thì 30fps cho nhẹ pin

save(); pygame.quit(); sys.exit()
