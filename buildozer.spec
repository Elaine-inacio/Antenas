[app]

title = Caracterizador de Antenas
package.name = myapp
package.domain = org.test
source.dir = .

source.include_exts = py,png,jpg,kv,atlas
version = 0.1

requirements = python3,kivy,pyjnius,numpy,matplotlib,pillow
p4a.fork = kivy
p4a.branch = master
p4a.python_version = 3.10
bootstrap = sdl2

icon.filename = icon.png
android.archs = arm64-v8a, armeabi-v7a

orientation = portrait
fullscreen = 0

android.permissions = \
    android.permission.BLUETOOTH,\
    android.permission.BLUETOOTH_ADMIN,\
    android.permission.BLUETOOTH_SCAN,\
    android.permission.BLUETOOTH_CONNECT,\
    android.permission.ACCESS_COARSE_LOCATION,\
    android.permission.ACCESS_FINE_LOCATION,\
    android.permission.READ_EXTERNAL_STORAGE,\
    android.permission.WRITE_EXTERNAL_STORAGE

android.api = 33
android.minapi = 26
android.ndk_api = 26
android.ndk = 25b


p4a.extra_env_vars = CFLAGS=-std=c++17
android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 1
