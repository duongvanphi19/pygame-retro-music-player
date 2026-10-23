import pygame, math, os
DIRS = (("down", 0, 1), ("up", 0, -1), ("left", -1, 0), ("right", 1, 0))
SM, SIDE, RATIO = 150, 100, 1.7
_TOUCH = (pygame.FINGERDOWN, pygame.FINGERMOTION, pygame.FINGERUP)
_MOUSE = (pygame.MOUSEBUTTONDOWN, pygame.MOUSEMOTION, pygame.MOUSEBUTTONUP)
_LOST = tuple(getattr(pygame, n) for n in ("WINDOWFOCUSLOST", "APP_WILLENTERBACKGROUND") if hasattr(pygame, n))

class TouchPad:
    def __init__(s, w, h, ph=112, buttons=None, dpad=None, scale=3, touch=False, font=None, cell=36, tint=None):
        s.w, s.h, s.ph, s.sc0, s.btn, s.cell, s.on = w, h, ph, scale, buttons or [], cell, None
        s.dp = dpad or (cell * 3 // 2 + 16, ph // 2)
        s.ptr, s.held, s.pressed, s.released = {}, set(), set(), set()
        s.st = {} 
        s.swipe_start = {} 
        s.vp, s._dst, s._fs, s.canvas = (1.0, 0, 0), None, False, None
        s.land, s.side, s.vo, s.view, s.bgs, s.ov, s.bt, s.bp, s.pcs = False, SIDE, (SM, 0), None, [], {}, {}, {}, []
        s.kr, s.cl, s.dc = 20, cell, (0, 0)
        s.lr = False
        
        s.show(touch)
        s.canvas = pygame.Surface((w + 2 * SM, h + ph)).convert()
        s.screen = s.canvas.subsurface((SM, 0, w, h))
        s._build()

    def _wsz(s):
        try: return pygame.display.get_window_size()
        except Exception: return pygame.display.get_desktop_sizes()[0]

    def _want(s):
        ww, wh = s._wsz()
        if not (s.on and ww >= wh * RATIO): return False, s.side
        return True, max(SIDE, min(SM, int((ww / wh * s.h - s.w) / 2)))

    def _place(s):
        w, h, sd = s.w, s.h, s.side
        if not s.on or not s.land:
            s.vo, s.view, s.pcs, s.kr, s.cl = (SM, 0), s.canvas.subsurface((SM, 0, w, h + s.ph)), [(SM, h, w, s.ph)], 20, s.cell
            s.dc = (SM + s.dp[0], h + s.dp[1])
            s.bp = {b[0]: (SM + b[2]-10, h + b[3]) for b in s.btn}
        else:
            s.vo, s.view, s.cl = (SM - sd, 0), s.canvas.subsurface((SM - sd, 0, w + 2 * sd, h)), min(s.cell, (sd - 8) // 3)
            s.pcs, s.dc, s.kr = [(SM - sd, 0, sd, h), (SM + w, 0, sd, h)], (SM - sd // 2, h // 2 + 28), 20
            cx, cy = SM + w + sd // 2, h // 2
            s.bp = {"C": (cx, cy - 56), "A": (cx, cy), "B": (cx, cy + 56), "S": (cx, 28)}

    def _draw_aa_button(s, name, r, bg_color, border_color, icon_color, is_pause=False):
        tr = r * 2 
        surf = pygame.Surface((tr * 2, tr * 2), pygame.SRCALPHA)
        pygame.draw.circle(surf, bg_color, (tr, tr), tr)
        pygame.draw.circle(surf, border_color, (tr, tr), tr, 1)
        cx, cy = tr, tr
        if name == "A": 
            if is_pause:
                pygame.draw.rect(surf, icon_color, (cx-5, cy-6, 3, 12), border_radius=1)
                pygame.draw.rect(surf, icon_color, (cx+2, cy-6, 3, 12), border_radius=1)
            else: pygame.draw.polygon(surf, icon_color, [(cx-4, cy-7), (cx-4, cy+7), (cx+6, cy)])
        elif name == "B": 
            pygame.draw.polygon(surf, icon_color, [(cx-6, cy-5), (cx-6, cy+5), (cx+2, cy)])
            pygame.draw.polygon(surf, icon_color, [(cx+2, cy-5), (cx+2, cy+5), (cx+10, cy)])
        elif name == "C": 
            pygame.draw.polygon(surf, icon_color, [(cx+6, cy-5), (cx+6, cy+5), (cx-2, cy)])
            pygame.draw.polygon(surf, icon_color, [(cx-2, cy-5), (cx-2, cy+5), (cx-10, cy)])
        elif name == "S": 
            pygame.draw.rect(surf, icon_color, (cx-6, cy-4, 12, 1), border_radius=1)
            pygame.draw.rect(surf, icon_color, (cx-6, cy,   12, 1), border_radius=1)
            pygame.draw.rect(surf, icon_color, (cx-6, cy+4, 12, 1), border_radius=1)
        return pygame.transform.smoothscale(surf, (r * 2, r * 2))

    def _build_dpad(s):
        n = s.cl; r_real = int(n * 1.6); tr = r_real * 2
        surf = pygame.Surface((tr * 2, tr * 2), pygame.SRCALPHA); center = tr
        pygame.draw.circle(surf, (18, 18, 24), (center, center), tr)
        pygame.draw.circle(surf, (36, 36, 46), (center, center), tr, 1)
        pygame.draw.circle(surf, (12, 12, 16), (center, center), int(tr * 0.45))
        pygame.draw.circle(surf, (36, 36, 46), (center, center), int(tr * 0.45), 1)
        for d, ox, oy in DIRS:
            pygame.draw.circle(surf, (80, 80, 100), (center + ox * tr * 0.72, center + oy * tr * 0.72), 3)
        return pygame.transform.smoothscale(surf, (r_real * 2, r_real * 2)), r_real

    def _build(s):
        s._place(); s.ov, s.bt = {}, {}
        if not s.on: return
        n, r, (px, py) = s.cl, s.kr, s.dc
        s.dpad_base, s.dpad_r = s._build_dpad()
        s.dpad_pos = (px - s.dpad_r, py - s.dpad_r)
        for d, ox, oy in DIRS:
            ov_surf = pygame.Surface((s.dpad_r * 2, s.dpad_r * 2), pygame.SRCALPHA)
            pygame.draw.circle(ov_surf, (255, 255, 255, 15), (s.dpad_r + ox * s.dpad_r * 0.72, s.dpad_r + oy * s.dpad_r * 0.72), s.dpad_r * 0.4)
            s.ov[d] = (ov_surf, s.dpad_pos)
        for d, _, *_ in s.btn:
            is_play = (d == "A"); tr = r + 5 if is_play else r
            L = []
            for col, icol in (((18, 18, 24), (180, 180, 200)), ((36, 36, 46), (255, 255, 255))):
                L.append((s._draw_aa_button(d, tr, col, (40, 40, 50), icol, False), tr))
            if is_play:
                for col, icol in (((18, 18, 24), (180, 180, 200)), ((36, 36, 46), (255, 255, 255))):
                    L.append((s._draw_aa_button(d, tr, col, (40, 40, 50), icol, True), tr))
            s.bt[d] = (L, *s.bp[d])

    def _layout(s):
        if not s.canvas: return
        win = pygame.display.get_surface(); ww, wh = win.get_size(); lw, lh = s.view.get_size()
        sc = min(ww / lw, wh / lh); sz = (int(lw * sc), int(lh * sc))
        s.vp = (sc, (ww - sz[0]) // 2, (wh - sz[1]) // 2)
        return win, s.view, (ww, wh), sz

    def _mode(s):
        s.land, s.side = s._want(); s.ptr.clear(); s._dst = None
        cw, ch = (s.w + 2 * s.side, s.h) if s.land else (s.w, s.h + (s.ph if s.on else 0))
        # An toàn tuyệt đối cho Pydroid3
        FS = pygame.FULLSCREEN | pygame.SCALED if "ANDROID_ARGUMENT" in os.environ else pygame.RESIZABLE
        pygame.display.set_mode((cw, ch), FS)
        pygame.key.stop_text_input()
        if s.canvas: s._build(); s._layout()

    def show(s, v):
        if v != s.on: s.on = v; s._mode()

    def _fp(s, x, y):                                        # ngón tay (0..1 theo cửa sổ thật) -> toạ độ logic; bù viền đen của SCALED
        lw, lh = pygame.display.get_surface().get_size()
        try: ww, wh = pygame.display.get_window_size()
        except Exception: ww, wh = lw, lh
        k = min(ww / lw, wh / lh)
        return s._cc((x * ww - (ww - lw * k) / 2) / k, (y * wh - (wh - lh * k) / 2) / k)

    def _cc(s, x, y): sc, ox, oy = s.vp; return (x - ox) / sc + s.vo[0], (y - oy) / sc + s.vo[1]

    def event(s, e):
        t = e.type
        if t in _TOUCH:
            if not s._fs: s._fs = True; s.ptr.pop("m", None)
            s.show(True); s._layout()
            if t == pygame.FINGERDOWN:
                pos = s._fp(e.x, e.y)
                s.ptr[e.finger_id] = pos
                s.swipe_start[e.finger_id] = pos
            elif t == pygame.FINGERMOTION and e.finger_id in s.ptr:
                s.ptr[e.finger_id] = s._fp(e.x, e.y)
            elif t == pygame.FINGERUP:
                if e.finger_id in s.swipe_start:
                    start_x, start_y = s.swipe_start[e.finger_id]
                    end_x, end_y = s.ptr.get(e.finger_id, (start_x, start_y))
                    dx, dy = end_x - start_x, end_y - start_y
                    if max(abs(dx), abs(dy)) > 50 and end_x > SM + 60: 
                        if abs(dx) > abs(dy): s.pressed.add("B" if dx < 0 else "C")
                    del s.swipe_start[e.finger_id]
                s.ptr.pop(e.finger_id, None)
        elif t in _MOUSE:
            if getattr(e, "touch", False) and not s._fs: s.show(True)
            if not s.on: return
            s._layout()
            if t == pygame.MOUSEBUTTONUP: s.ptr.pop("m", None)
            elif (t == pygame.MOUSEBUTTONDOWN and e.button == 1) or (t == pygame.MOUSEMOTION and e.buttons[0] and "m" in s.ptr):
                s.ptr["m"] = s._cc(*e.pos)
        elif t in _LOST: s.ptr.clear()

    def _read(s):
        out, (px, py), reach_sq, dead_sq, hr_sq = set(), s.dc, (s.cl * 2.2)**2, (s.cl * 0.3)**2, (s.kr + 12)**2
        for x, y in s.ptr.values():
            if SM <= x < SM + s.w and y < s.h: continue
            for n, (bx, by) in s.bp.items():
                if (x - bx)**2 + (y - by)**2 < ((s.dpad_r * 0.45)**2 if n == "A" else hr_sq): 
                    out.add(n); break
            else:
                dx, dy = x - px, y - py
                if dead_sq < dx*dx + dy*dy < reach_sq:
                    out.add(("left" if dx < 0 else "right") if abs(dx) > abs(dy) else ("up" if dy < 0 else "down"))
        return out

    def update(s):
        now = s._read() if s.on else set()
        s.pressed, s.released, s.held = now - s.held, s.held - now, now

    def present(s):
        if s.on and s._want()[0] != s.land: s._mode()
        win, view, wsz, sz = s._layout()
        if s.on:
            c = s.canvas
            for (rx, ry, rw, rh) in s.pcs: c.fill((12, 12, 16), (rx, ry, rw, rh))
            c.blit(s.dpad_base, s.dpad_pos)
            for n in s.held:
                if n in s.ov: c.blit(*s.ov[n])
            for n, (L, x, y) in s.bt.items():
                base_idx = s.st.get(n, 0)
                idx = base_idx + (1 if n in s.held else 0)
                surf, tr = L[idx if idx < len(L) else (1 if n in s.held else 0)]
                c.blit(surf, (x - tr, y - tr))
        k = (sz, wsz, s.on, s.land, win)
        if not s._dst or s._dst[0] != k:
            win.fill((12, 12, 16)); s._dst = (k, win.subsurface((s.vp[1], s.vp[2], *sz)))
        if sz[0] > 0 and sz[1] > 0:
            pygame.transform.scale(view, sz, s._dst[1]); pygame.display.flip()
