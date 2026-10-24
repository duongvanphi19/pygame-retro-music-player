package com.phiduong.musicplayer;

import android.content.Context;
import android.content.Intent;
import android.media.session.MediaSession;

/** Cầu nối MediaSession -> Python: MediaSession.Callback là lớp trừu tượng nên pyjnius không kế thừa được.
 *  Mỗi lệnh (nút tai nghe, màn hình khoá, Bluetooth, Android Auto) được đổi thành broadcast nội bộ,
 *  receiver Python trong service (đã dùng cho nút thông báo) xử lý tiếp. */
public class MsCallback extends MediaSession.Callback {
    private final Context ctx;
    private final String pkg;

    public MsCallback(Context ctx, String pkg) { this.ctx = ctx; this.pkg = pkg; }

    private void send(String action, long pos) {
        Intent i = new Intent(pkg + action);
        i.setPackage(ctx.getPackageName());
        i.putExtra("pos", pos);
        ctx.sendBroadcast(i);
    }

    @Override public void onPlay() { send("PLAY", 0); }
    @Override public void onPause() { send("PAUSE", 0); }
    @Override public void onStop() { send("PAUSE", 0); }
    @Override public void onSkipToNext() { send("NEXT", 0); }
    @Override public void onSkipToPrevious() { send("PREV", 0); }
    @Override public void onSeekTo(long pos) { send("SEEK", pos); }
}
