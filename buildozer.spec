[app]
title = Nghe Nhac
package.name = musicplayer
package.domain = com.phiduong
source.dir = .
source.include_exts = py
version = 1.0
# icon.filename = %(source.dir)s/icon.png
# presplash.filename = %(source.dir)s/presplash.png
presplash.color = #0c0c10

# quyền: đọc nhạc (Android 13+ / cũ), thông báo, service nền, giữ CPU, mạng (lấy lyric)
android.permissions = READ_MEDIA_AUDIO,READ_EXTERNAL_STORAGE,POST_NOTIFICATIONS,FOREGROUND_SERVICE,WAKE_LOCK,INTERNET

# pygame/ndk/p4a giữ y như bản game đã build ok; thêm pyjnius, android (xin quyền) và mutagen (đọc tag)
requirements = python3,pygame==2.1.2,pyjnius,android,mutagen
orientation = portrait
fullscreen = 1
android.archs = arm64-v8a
android.accept_sdk_license = True
android.ndk = 25b
android.api = 33
android.minapi = 24
p4a.branch = v2023.09.16

# service phát nhạc: tiến trình riêng, foreground, tự sống lại khi bị hệ thống kill
services = Player:service/main.py:foreground:sticky

[buildozer]
log_level = 2
warn_on_root = 1
