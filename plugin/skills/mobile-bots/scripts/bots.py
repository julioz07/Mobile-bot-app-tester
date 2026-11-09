#!/usr/bin/env python3
"""mobile-bots: a small fleet of Android emulators ("bots") for testing apps and games.

One file, Python 3.9+ standard library only. Works on Windows, Linux and macOS.
Run `python bots.py --help` or `python bots.py <command> --help`.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

VERSION = "0.1.0"
IS_WIN = os.name == "nt"
HOME = Path.home()
STATE_DIR = Path(os.environ.get("MOBILE_BOTS_HOME", HOME / ".mobile-bots"))
REGISTRY = STATE_DIR / "bots.json"
FIRST_PORT, LAST_PORT = 5554, 5584  # the emulator only accepts even ports in this range

# Device profiles. `device` is an avdmanager hardware id; if this SDK doesn't know it,
# a generic phone is used and the screen is set from w/h/dpi instead.
PROFILES = {
    "phone-small": dict(device="small_phone", w=720, h=1280, dpi=320, ram=2048,
                        desc="Small or older phone (720x1280). Finds cut-off text and buttons pushed off screen."),
    "phone": dict(device="medium_phone", w=1080, h=2400, dpi=420, ram=2048,
                  desc="Typical mid-range phone (1080x2400). The default."),
    "phone-large": dict(device="pixel_9_pro_xl", w=1344, h=2992, dpi=480, ram=2048,
                        desc="Large high-density phone (1344x2992)."),
    "foldable": dict(device="pixel_9_pro_fold", w=2076, h=2152, dpi=390, ram=2048,
                     desc="Foldable (2076x2152 open). Finds layouts that break on a near-square screen."),
    "tablet": dict(device="pixel_tablet", w=2560, h=1600, dpi=320, ram=3072,
                   desc="10-inch landscape tablet (2560x1600)."),
}
FALLBACK_DEVICES = ["medium_phone", "pixel_7", "pixel_6", "pixel_5", "pixel"]


# --------------------------------------------------------------------------- utils

def say(msg: str = "") -> None:
    print(msg, flush=True)


def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def now_tag() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def run(cmd: list[str], *, check: bool = False, timeout: float | None = 120, input: str | None = None,
        env: dict | None = None, binary: bool = False) -> subprocess.CompletedProcess:
    try:
        cp = subprocess.run(cmd, capture_output=True, timeout=timeout, input=input if not binary else None,
                            text=not binary, env=env,
                            **({"encoding": "utf-8", "errors": "replace"} if not binary else {}))
    except FileNotFoundError:
        die(f"command not found: {cmd[0]}")
    except subprocess.TimeoutExpired:
        die(f"timed out after {timeout}s: {' '.join(map(str, cmd[:6]))}")
    if check and cp.returncode != 0:
        err = cp.stderr if not binary else cp.stderr.decode("utf-8", "replace")
        die(f"{' '.join(map(str, cmd[:6]))} failed ({cp.returncode}): {err.strip()[:500]}")
    return cp


# --------------------------------------------------------------------------- SDK

def sdk_root() -> Path | None:
    for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        v = os.environ.get(var)
        if v and Path(v).is_dir():
            return Path(v)
    if IS_WIN:
        cands = [Path(os.environ.get("LOCALAPPDATA", HOME / "AppData/Local")) / "Android/Sdk"]
    elif sys.platform == "darwin":
        cands = [HOME / "Library/Android/sdk"]
    else:
        cands = [HOME / "Android/Sdk", HOME / "Android/sdk", Path("/opt/android-sdk"), Path("/usr/lib/android-sdk")]
    return next((c for c in cands if c.is_dir()), None)


def _exe(name: str) -> str:
    return name + (".exe" if IS_WIN else "")


def tool(name: str, required: bool = True) -> str | None:
    """Path to adb, emulator, avdmanager or sdkmanager."""
    root = sdk_root()
    found: Path | None = None
    if root:
        if name == "adb":
            p = root / "platform-tools" / _exe("adb")
            found = p if p.exists() else None
        elif name == "emulator":
            p = root / "emulator" / _exe("emulator")
            found = p if p.exists() else None
        else:  # avdmanager / sdkmanager live in cmdline-tools/<version>/bin
            script = name + (".bat" if IS_WIN else "")
            dirs = [root / "cmdline-tools/latest/bin"]
            dirs += sorted((root / "cmdline-tools").glob("*/bin"), reverse=True) if (root / "cmdline-tools").is_dir() else []
            dirs += [root / "tools/bin"]
            found = next((d / script for d in dirs if (d / script).exists()), None)
    if not found:
        w = shutil.which(name)
        found = Path(w) if w else None
    if not found and required:
        hint = {"adb": "Android SDK Platform-Tools", "emulator": "Android Emulator",
                "avdmanager": "Android SDK Command-line Tools", "sdkmanager": "Android SDK Command-line Tools"}[name]
        die(f"{name} not found. Install '{hint}' (Android Studio > SDK Manager) or set ANDROID_HOME.")
    return str(found) if found else None


def _java_major(java_home: Path | None) -> int:
    java = (java_home / "bin" / _exe("java")) if java_home else shutil.which("java")
    if not java or not Path(java).exists():
        return 0
    try:
        out = subprocess.run([str(java), "-version"], capture_output=True, text=True, timeout=30).stderr
    except Exception:
        return 0
    m = re.search(r'version "(\d+)(?:\.(\d+))?', out)
    if not m:
        return 0
    major = int(m.group(1))
    return int(m.group(2) or 0) if major == 1 else major


_JAVA_ENV: dict | None = None


def java_env() -> dict:
    """avdmanager/sdkmanager need Java 17+. Use JAVA_HOME if new enough, else the one
    Android Studio ships (jbr), else java on PATH."""
    global _JAVA_ENV
    if _JAVA_ENV is not None:
        return _JAVA_ENV
    env = dict(os.environ)
    if env.get("JAVA_HOME") and _java_major(Path(env["JAVA_HOME"])) >= 17:
        _JAVA_ENV = env
        return env
    cands = []
    if IS_WIN:
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("LOCALAPPDATA", "")):
            if base:
                cands += [Path(base) / "Android/Android Studio/jbr", Path(base) / "Programs/Android Studio/jbr"]
    elif sys.platform == "darwin":
        cands += [Path("/Applications/Android Studio.app/Contents/jbr/Contents/Home")]
    else:
        cands += [Path("/opt/android-studio/jbr"), HOME / "android-studio/jbr",
                  Path("/snap/android-studio/current/jbr"), Path("/usr/local/android-studio/jbr")]
    for c in cands:
        if _java_major(c) >= 17:
            env["JAVA_HOME"] = str(c)
            _JAVA_ENV = env
            return env
    if _java_major(None) >= 17:
        env.pop("JAVA_HOME", None)
    _JAVA_ENV = env
    return env


def has_java(env: dict) -> bool:
    home = env.get("JAVA_HOME")
    return _java_major(Path(home) if home else None) >= 17


def avd_home() -> Path:
    v = os.environ.get("ANDROID_AVD_HOME")
    if v:
        return Path(v)
    base = Path(os.environ["ANDROID_USER_HOME"]) if os.environ.get("ANDROID_USER_HOME") else HOME / ".android"
    return base / "avd"


def host_abi() -> str:
    m = platform.machine().lower()
    return "arm64-v8a" if m in ("arm64", "aarch64") else "x86_64"


# --------------------------------------------------------------------------- memory

def ram_mb() -> tuple[int | None, int | None]:
    """(total, available) in MB, None when unknown."""
    try:
        if IS_WIN:
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            s = MS()
            s.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
            return s.ullTotalPhys // 2**20, s.ullAvailPhys // 2**20
        if sys.platform == "darwin":
            total = int(run(["sysctl", "-n", "hw.memsize"]).stdout.strip()) // 2**20
            return total, None
        info = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":", 1)
            info[k] = int(v.split()[0]) // 1024
        return info.get("MemTotal"), info.get("MemAvailable")
    except Exception:
        return None, None


# --------------------------------------------------------------------------- registry

def load_reg() -> dict:
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {"bots": {}}


def save_reg(reg: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, indent=2), encoding="utf-8")
    tmp.replace(REGISTRY)


def free_port(reg: dict) -> int:
    used = {b["port"] for b in reg["bots"].values()}
    for p in range(FIRST_PORT, LAST_PORT + 1, 2):
        if p not in used:
            return p
    die("no free emulator port (max 16 bots)")
    return 0


def list_avds() -> list[str]:
    cp = run([tool("emulator"), "-list-avds"])
    return [l.strip() for l in cp.stdout.splitlines() if l.strip() and not l.startswith(("INFO", "WARNING"))]


# --------------------------------------------------------------------------- adb

def adb(serial: str | None, *args: str, timeout: float | None = 60, check: bool = False, binary: bool = False):
    cmd = [tool("adb")] + (["-s", serial] if serial else []) + list(args)
    return run(cmd, timeout=timeout, check=check, binary=binary)


def sh(serial: str, command: str, timeout: float | None = 60) -> str:
    return adb(serial, "shell", command, timeout=timeout).stdout.strip()


def running() -> dict[int, str]:
    """port -> serial for emulators adb sees as online."""
    out = {}
    for line in adb(None, "devices").stdout.splitlines():
        m = re.match(r"emulator-(\d+)\s+device$", line.strip())
        if m:
            out[int(m.group(1))] = f"emulator-{m.group(1)}"
    return out


def serial_of(bot: dict) -> str:
    return f"emulator-{bot['port']}"


def pick(names: list[str], *, need_running: bool = True) -> list[tuple[str, dict, str]]:
    """Resolve bot names ('all' = every registered bot) to (name, bot, serial)."""
    reg = load_reg()
    if not reg["bots"]:
        die("no bots yet. Create one with `create` or register an existing AVD with `adopt`.")
    if not names or names == ["all"]:
        names = list(reg["bots"])
        if need_running:
            live = running()
            names = [n for n in names if reg["bots"][n]["port"] in live]
            if not names:
                die("no bot is running. Start some with `start`.")
    out = []
    live = running() if need_running else {}
    for n in names:
        b = reg["bots"].get(n)
        if not b:
            die(f"unknown bot '{n}'. Known: {', '.join(reg['bots'])}")
        if need_running and b["port"] not in live:
            die(f"bot '{n}' is not running. Start it with `start {n}`.")
        out.append((n, b, serial_of(b)))
    return out


def parallel(items, fn):
    """Run fn(item) for each item in threads, keep order, re-raise nothing (fn prints)."""
    results = [None] * len(items)

    def work(i, it):
        try:
            results[i] = fn(it)
        except SystemExit as e:  # die() inside a thread
            results[i] = e
        except Exception as e:  # noqa: BLE001
            results[i] = e
            say(f"[{it[0] if isinstance(it, tuple) else it}] error: {e}")

    ts = [threading.Thread(target=work, args=(i, it)) for i, it in enumerate(items)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return results


# --------------------------------------------------------------------------- commands: setup

def cmd_doctor(a):
    ok = True
    say(f"mobile-bots {VERSION} on {platform.system()} {platform.machine()}, Python {platform.python_version()}")
    root = sdk_root()
    say(f"Android SDK:     {root or 'NOT FOUND (install Android Studio, or set ANDROID_HOME)'}")
    ok &= root is not None
    for t in ("adb", "emulator", "avdmanager", "sdkmanager"):
        p = tool(t, required=False)
        say(f"{t + ':':16} {p or 'NOT FOUND'}")
        ok &= p is not None
    env = java_env()
    java = has_java(env)
    say(f"Java 17+ (for avdmanager): {(env.get('JAVA_HOME') or shutil.which('java')) if java else 'NOT FOUND (Android Studio ships one; or point JAVA_HOME to a JDK 17+)'}")
    ok &= java
    emu = tool("emulator", required=False)
    if emu:
        cp = run([emu, "-accel-check"], timeout=60)
        txt = (cp.stdout + cp.stderr).strip().splitlines()
        usable = "usable" in " ".join(txt).lower() and cp.returncode == 0
        say(f"Hardware acceleration: {'OK' if usable else 'NOT AVAILABLE'} ({txt[-1] if txt else ''})")
        if not usable:
            ok = False
            say("  Windows: enable 'Windows Hypervisor Platform' in Windows Features. "
                "Linux: enable KVM (/dev/kvm) and add your user to the 'kvm' group.")
    total, avail = ram_mb()
    if total:
        cap = max(0, int((total / 1024 - 6) // 3))
        say(f"RAM: {total // 1024} GB total" + (f", {avail // 1024} GB free now" if avail else "")
            + f" -> about {cap} bot(s) at once (each takes ~2-3 GB; keep ~6 GB for the system and IDE)")
    root and say(f"Disk free on SDK drive: {shutil.disk_usage(root).free // 2**30} GB (each bot needs ~6-10 GB)")
    say(f"Host image ABI: {host_abi()}")
    say(f"Registry: {REGISTRY}")
    say("\nREADY" if ok else "\nNOT READY: fix the items above")
    return 0 if ok else 1


def cmd_profiles(a):
    for k, p in PROFILES.items():
        say(f"{k:12} {p['w']}x{p['h']} @{p['dpi']}dpi  RAM {p['ram'] // 1024} GB  - {p['desc']}")


def _image(api: int, play: bool, abi: str) -> str:
    return f"system-images;android-{api};{'google_apis_playstore' if play else 'google_apis'};{abi}"


def _image_installed(img: str) -> bool:
    root = sdk_root()
    return bool(root) and (root / Path(*img.split(";"))).is_dir()


def _set_config(avd: str, values: dict) -> None:
    cfg = avd_home() / f"{avd}.avd" / "config.ini"
    lines = cfg.read_text(encoding="utf-8").splitlines() if cfg.exists() else []
    keys = {}
    for i, l in enumerate(lines):
        if "=" in l:
            keys[l.split("=", 1)[0].strip()] = i
    for k, v in values.items():
        if k in keys:
            lines[keys[k]] = f"{k}={v}"
        else:
            lines.append(f"{k}={v}")
    cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_create(a):
    reg = load_reg()
    name = a.name
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        die("bot name may only use letters, digits, '.', '_' and '-'")
    if name in reg["bots"]:
        die(f"bot '{name}' already exists")
    prof = PROFILES.get(a.profile) or die(f"unknown profile '{a.profile}'. See `profiles`.")
    avd = f"bot_{name}"
    if avd in list_avds():
        die(f"an AVD called {avd} already exists. Register it with `adopt {avd} --name {name}`.")
    env = java_env()
    if not has_java(env):
        die("Java not found (needed by avdmanager). Install Android Studio or set JAVA_HOME.")
    abi = a.abi or host_abi()
    img = _image(a.api, a.play, abi)
    if not _image_installed(img):
        if not a.download:
            die(f"system image not installed: {img}\n"
                f"Re-run with --download to install it (~1.5 GB). This accepts the Android SDK licenses.")
        say(f"Downloading {img} ...")
        run([tool("sdkmanager"), "--licenses"], input="y\n" * 20, env=env, timeout=300)
        run([tool("sdkmanager"), img], input="y\n" * 5, env=env, timeout=3600, check=True)
    devs = [l.strip() for l in run([tool("avdmanager"), "list", "device", "-c"], env=env, check=True).stdout.splitlines()]
    device = prof["device"] if prof["device"] in devs else next((d for d in FALLBACK_DEVICES if d in devs), None)
    say(f"Creating {avd} ({a.profile}, {img}, device {device or 'default'}) ...")
    cmd = [tool("avdmanager"), "create", "avd", "-n", avd, "-k", img]
    if device:
        cmd += ["-d", device]
    cp = run(cmd, input="no\n", env=env, check=True, timeout=300)
    if not (avd_home() / f"{avd}.avd" / "config.ini").exists():  # avdmanager can fail with exit code 0
        die(f"avdmanager did not create the AVD:\n{(cp.stdout + cp.stderr).strip()[-800:]}")
    cfg = {"hw.ramSize": prof["ram"], "hw.keyboard": "yes", "hw.gpu.enabled": "yes", "hw.gpu.mode": "auto",
           "disk.dataPartition.size": "8G", "showDeviceFrame": "no", "fastboot.forceColdBoot": "no"}
    if device != prof["device"]:  # unknown hardware id: set the screen by hand
        cfg.update({"hw.lcd.width": prof["w"], "hw.lcd.height": prof["h"], "hw.lcd.density": prof["dpi"]})
    _set_config(avd, cfg)
    reg["bots"][name] = {"avd": avd, "port": free_port(reg), "profile": a.profile, "play": a.play, "api": a.api,
                         "protected": False, "created": _dt.date.today().isoformat(), "note": a.note or ""}
    save_reg(reg)
    say(f"OK: bot '{name}' -> AVD {avd}, port {reg['bots'][name]['port']}. Start it with `start {name}`.")
    if a.play:
        say("Play Store image: sign in with a Google account by hand once, then `snapshot save` and `protect` it.")


def cmd_adopt(a):
    reg = load_reg()
    if a.avd not in list_avds():
        die(f"no AVD called '{a.avd}'. Existing: {', '.join(list_avds()) or 'none'}")
    name = a.name or a.avd
    if name in reg["bots"]:
        die(f"bot '{name}' already exists")
    if any(b["avd"] == a.avd for b in reg["bots"].values()):
        die(f"AVD {a.avd} is already registered")
    port = a.port or free_port(reg)
    if port % 2 or not FIRST_PORT <= port <= LAST_PORT:
        die(f"port must be even, {FIRST_PORT}-{LAST_PORT}")
    if any(b["port"] == port for b in reg["bots"].values()):
        die(f"port {port} is taken")
    cfg = avd_home() / f"{a.avd}.avd" / "config.ini"
    play = "playstore" in (cfg.read_text(encoding="utf-8", errors="replace") if cfg.exists() else "")
    reg["bots"][name] = {"avd": a.avd, "port": port, "profile": a.profile or "custom", "play": play, "api": None,
                         "protected": a.protect, "created": _dt.date.today().isoformat(), "note": a.note or ""}
    save_reg(reg)
    say(f"OK: '{name}' registered (AVD {a.avd}, port {port}{', protected' if a.protect else ''}).")


def cmd_list(a):
    reg = load_reg()
    if a.avds:
        known = {b["avd"] for b in reg["bots"].values()}
        others = [v for v in list_avds() if v not in known]
        say("Emulators on this computer that are not bots yet: " + (", ".join(others) or "none"))
        if others:
            say("Register one with `adopt <avd> --name <bot> [--protect]`.")
        say("")
    if not reg["bots"]:
        say("no bots yet. `create` one or `adopt` an existing AVD.")
        return
    live = running()
    say(f"{'NAME':18} {'STATE':8} {'SERIAL':15} {'PROFILE':12} {'PLAY':5} {'PROT':5} AVD / NOTE")
    for n, b in reg["bots"].items():
        st = "running" if b["port"] in live else "stopped"
        say(f"{n:18} {st:8} {serial_of(b):15} {b['profile']:12} {'yes' if b.get('play') else 'no':5} "
            f"{'yes' if b.get('protected') else 'no':5} {b['avd']}{('  - ' + b['note']) if b.get('note') else ''}")


def cmd_start(a):
    reg = load_reg()
    names = list(reg["bots"]) if a.bots == ["all"] else a.bots
    if not names:
        die("say which bots to start, or 'all'")
    live = running()
    todo = []
    for n in names:
        b = reg["bots"].get(n) or die(f"unknown bot '{n}'")
        if b["port"] in live:
            other = adb(serial_of(b), "emu", "avd", "name").stdout.strip().splitlines()
            if other and other[0].strip() != b["avd"]:
                die(f"port {b['port']} is used by another emulator ({other[0].strip()}). Stop it, or re-register "
                    f"'{n}' on another port with `adopt`.")
            say(f"[{n}] already running ({serial_of(b)})")
        else:
            todo.append((n, b))
    if not todo:
        return
    need = sum(PROFILES.get(b["profile"], {"ram": 2048})["ram"] + 1024 for _, b in todo)
    total, avail = ram_mb()
    if avail and avail < need + 2048 and not a.force:
        die(f"starting {len(todo)} bot(s) needs ~{need // 1024 + 2} GB free, only {avail // 1024} GB available. "
            f"Close something, start fewer, or pass --force.")
    STATE_DIR.joinpath("logs").mkdir(parents=True, exist_ok=True)
    for n, b in todo:
        cmd = [tool("emulator"), "-avd", b["avd"], "-port", str(b["port"]), "-no-boot-anim"]
        if a.headless:
            cmd += ["-no-window", "-gpu", "swiftshader_indirect", "-no-audio"]
        if a.cold:
            cmd += ["-no-snapshot-load"]
        if a.snapshot:
            cmd += ["-snapshot", a.snapshot]
        log = open(STATE_DIR / "logs" / f"{n}.log", "w", encoding="utf-8")
        kw = {"creationflags": 0x00000008 | 0x00000200} if IS_WIN else {"start_new_session": True}
        subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kw)
        say(f"[{n}] starting on {serial_of(b)} ...")
        time.sleep(2)
    if a.no_wait:
        return

    def wait(item):
        n, b = item
        s = serial_of(b)
        t0 = time.time()
        while time.time() - t0 < a.timeout:
            if b["port"] in running() and sh(s, "getprop sys.boot_completed", timeout=15) == "1":
                say(f"[{n}] ready in {int(time.time() - t0)}s")
                return True
            time.sleep(3)
        say(f"[{n}] not ready after {a.timeout}s; see {STATE_DIR / 'logs' / (n + '.log')}")
        return False

    res = parallel(todo, wait)
    if not all(r is True for r in res):
        sys.exit(1)


def cmd_stop(a):
    for n, b, s in pick(a.bots):
        adb(s, "emu", "kill")
        say(f"[{n}] stopping")


def cmd_protect(a, on=True):
    reg = load_reg()
    for n in a.bots:
        if n not in reg["bots"]:
            die(f"unknown bot '{n}'")
        reg["bots"][n]["protected"] = on
        say(f"[{n}] {'protected: delete will refuse it' if on else 'no longer protected'}")
    save_reg(reg)


def cmd_delete(a):
    reg = load_reg()
    b = reg["bots"].get(a.bot) or die(f"unknown bot '{a.bot}'")
    if b.get("protected"):
        die(f"'{a.bot}' is protected (for example it has a Google login). Run `unprotect {a.bot}` first if you are sure.")
    if not a.yes:
        say(f"This permanently deletes AVD {b['avd']} and everything on it. Re-run with --yes to confirm.")
        return
    if b["port"] in running():
        adb(serial_of(b), "emu", "kill")
        time.sleep(4)
    if not a.keep_avd:
        run([tool("avdmanager"), "delete", "avd", "-n", b["avd"]], env=java_env(), check=True)
    del reg["bots"][a.bot]
    save_reg(reg)
    say(f"OK: '{a.bot}' deleted" + (" (AVD kept)" if a.keep_avd else ""))


def cmd_snapshot(a):
    (n, b, s), = pick([a.bot])
    if a.action == "list":
        say(adb(s, "emu", "avd", "snapshot", "list").stdout.strip())
        return
    if not a.snap:
        die("give a snapshot name")
    out = adb(s, "emu", "avd", "snapshot", a.action, a.snap, timeout=300).stdout.strip()
    say(f"[{n}] snapshot {a.action} {a.snap}: {out.splitlines()[-1] if out else 'done'}")


# --------------------------------------------------------------------------- commands: apps

def _bundletool() -> list[str]:
    jar = os.environ.get("BUNDLETOOL") or str(STATE_DIR / "bundletool.jar")
    if not Path(jar).exists():
        die("installing .aab/.apks needs bundletool. Download bundletool-all-<ver>.jar from "
            f"https://github.com/google/bundletool/releases and save it as {STATE_DIR / 'bundletool.jar'} "
            "(or set BUNDLETOOL to its path).")
    env = java_env()
    java = Path(env["JAVA_HOME"]) / "bin" / _exe("java") if env.get("JAVA_HOME") else shutil.which("java")
    if not java:
        die("Java not found (needed by bundletool)")
    return [str(java), "-jar", jar]


def cmd_install(a):
    path = Path(a.file)
    if not path.exists():
        die(f"not found: {path}")
    targets = pick(a.bots)
    apks = None
    if path.suffix == ".aab":
        apks = STATE_DIR / f"tmp-{now_tag()}.apks"
        say("Building device APKs from the bundle (debug-signed, for testing) ...")
        run(_bundletool() + ["build-apks", f"--bundle={path}", f"--output={apks}", "--overwrite"],
            check=True, timeout=900)

    def one(t):
        n, b, s = t
        if path.is_dir():
            files = sorted(str(p) for p in path.glob("*.apk"))
            cp = adb(s, "install-multiple", "-r", *(["-g"] if a.grant else []), *files, timeout=600)
        elif path.suffix in (".aab", ".apks"):
            cp = run(_bundletool() + ["install-apks", f"--apks={apks or path}", f"--device-id={s}",
                                      f"--adb={tool('adb')}"], timeout=600)
        else:
            cp = adb(s, "install", "-r", *(["-g"] if a.grant else []), str(path), timeout=600)
        txt = (cp.stdout + cp.stderr).strip()
        okk = cp.returncode == 0 and "Failure" not in txt
        say(f"[{n}] {'installed' if okk else 'FAILED: ' + txt.splitlines()[-1] if txt else 'FAILED'}")
        if not okk and "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in txt:
            say(f"[{n}]   a copy signed with another key is installed (e.g. from the Play Store). "
                f"Uninstall it first, which erases its data.")
        if not okk and "VERSION_DOWNGRADE" in txt:
            say(f"[{n}]   a newer versionCode is installed; uninstall it first, which erases its data.")
        return okk

    res = parallel(targets, one)
    if apks and apks.exists():
        apks.unlink()
    if not all(r is True for r in res):
        sys.exit(1)


def cmd_launch(a):
    for n, b, s in pick(a.bots):
        out = sh(s, f"monkey -p {a.package} -c android.intent.category.LAUNCHER 1")
        say(f"[{n}] {'launched' if 'Events injected: 1' in out else 'FAILED: ' + out.splitlines()[-1] if out else 'FAILED'}")


def cmd_appctl(a):
    for n, b, s in pick(a.bots):
        if a.action == "stop":
            sh(s, f"am force-stop {a.package}")
        elif a.action == "clear":
            sh(s, f"pm clear {a.package}")
        elif a.action == "uninstall":
            say(f"[{n}] " + adb(s, "uninstall", a.package).stdout.strip())
            continue
        say(f"[{n}] {a.action} {a.package}: done")


def cmd_info(a):
    for n, b, s in pick(a.bots):
        props = {k: sh(s, f"getprop {k}") for k in ("ro.product.model", "ro.build.version.release",
                                                     "ro.build.version.sdk", "persist.sys.locale")}
        size = sh(s, "wm size").replace("\n", ", ")
        dens = sh(s, "wm density").replace("\n", ", ")
        say(f"[{n}] {props['ro.product.model']}, Android {props['ro.build.version.release']} "
            f"(API {props['ro.build.version.sdk']}), {size}; {dens}; font {sh(s, 'settings get system font_scale')}; "
            f"night {sh(s, 'cmd uimode night').replace('Night mode: ', '')}")
        if a.package:
            d = sh(s, f"dumpsys package {a.package}")
            vn = re.search(r"versionName=(\S+)", d)
            vc = re.search(r"versionCode=(\d+)", d)
            inst = re.search(rf"package:\S*{re.escape(a.package)}\s+installer=(\S+)",
                             sh(s, f"pm list packages -i {a.package}"))
            if vn:
                say(f"[{n}]   {a.package} {vn.group(1)} ({vc.group(1) if vc else '?'}), installer "
                    f"{inst.group(1) if inst else '?'} (com.android.vending = Play Store, null = adb)")
            else:
                say(f"[{n}]   {a.package} not installed")


# --------------------------------------------------------------------------- commands: look and touch

def _resize(png: Path, max_side: int) -> float:
    """Shrink the screenshot so its longest side is max_side. Returns the factor to multiply
    screenshot coordinates by to get device coordinates (1.0 if nothing changed)."""
    try:
        from PIL import Image  # optional
    except ImportError:
        return 1.0
    im = Image.open(png)
    side = max(im.size)
    if side <= max_side:
        return 1.0
    f = side / max_side
    im.resize((round(im.width / f), round(im.height / f))).save(png)
    return round(f, 4)


def cmd_shot(a):
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    label = f"-{a.label}" if a.label else ""

    def one(t):
        n, b, s = t
        cp = adb(s, "exec-out", "screencap", "-p", binary=True, timeout=60)
        if cp.returncode != 0 or not cp.stdout.startswith(b"\x89PNG"):
            say(f"[{n}] screenshot FAILED")
            return
        p = out / f"{n}{label}-{now_tag()}.png"
        p.write_bytes(cp.stdout)
        w, h = int.from_bytes(cp.stdout[16:20], "big"), int.from_bytes(cp.stdout[20:24], "big")
        f = _resize(p, a.max) if a.max else 1.0
        say(f"[{n}] {p}  device {w}x{h}" + (f"  scale {f} (pass --scale {f} to tap with these pixels)" if f != 1.0 else ""))

    parallel(pick(a.bots), one)


def cmd_record(a):
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    secs = min(a.seconds, 180)

    def one(t):
        n, b, s = t
        remote = f"/sdcard/mbt-{n}.mp4"
        say(f"[{n}] recording {secs}s ...")
        adb(s, "shell", f"screenrecord --time-limit {secs} {remote}", timeout=secs + 30)
        time.sleep(1)
        p = out / f"{n}{('-' + a.label) if a.label else ''}-{now_tag()}.mp4"
        adb(s, "pull", remote, str(p), timeout=120)
        adb(s, "shell", f"rm {remote}")
        say(f"[{n}] {p}" if p.exists() else f"[{n}] recording FAILED")

    parallel(pick(a.bots), one)


def _ui_nodes(s: str) -> list[dict]:
    adb(s, "shell", "uiautomator dump /sdcard/mbt-ui.xml", timeout=60)
    xml = adb(s, "exec-out", "cat", "/sdcard/mbt-ui.xml", binary=True).stdout
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    nodes = []
    for e in root.iter("node"):
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", e.get("bounds", ""))
        if not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        nodes.append({"x": (x1 + x2) // 2, "y": (y1 + y2) // 2, "w": x2 - x1, "h": y2 - y1,
                      "text": e.get("text", ""), "desc": e.get("content-desc", ""),
                      "id": e.get("resource-id", "").split("/")[-1], "cls": e.get("class", "").split(".")[-1],
                      "click": e.get("clickable") == "true", "scroll": e.get("scrollable") == "true",
                      "checked": e.get("checked") == "true", "enabled": e.get("enabled") == "true"})
    return nodes


def cmd_ui(a):
    (n, b, s), = pick([a.bot])
    nodes = _ui_nodes(s)
    shown = [x for x in nodes if a.all or x["text"] or x["desc"] or x["click"] or x["scroll"]]
    if not shown:
        say(f"[{n}] no UI elements visible to Android. This is normal for games and canvas apps "
            f"(Unity, Godot, Flutter Flame...): use `shot` and `tap X Y` instead.")
        return
    say("X,Y        FLAGS  TEXT | DESCRIPTION | ID  (size)")
    for x in shown:
        flags = ("C" if x["click"] else "-") + ("S" if x["scroll"] else "-") + ("x" if x["checked"] else "-") \
            + ("" if x["enabled"] else "!")
        label = " | ".join(v.replace("\n", " / ") for v in (x["text"], x["desc"], x["id"]) if v) or x["cls"]
        say(f"{x['x']},{x['y']:<6} {flags:5}  {label[:110]}  ({x['w']}x{x['h']})")
    say("FLAGS: C clickable, S scrollable, x checked, ! disabled")


def _tap(s: str, x: float, y: float) -> None:
    sh(s, f"input tap {int(round(x))} {int(round(y))}")


def cmd_tap(a):
    for n, b, s in pick(a.bots):
        _tap(s, a.x * a.scale, a.y * a.scale)
        say(f"[{n}] tap {int(a.x * a.scale)},{int(a.y * a.scale)}")


def cmd_tap_text(a):
    rx = re.compile(a.pattern, re.I)
    for n, b, s in pick(a.bots):
        hit = next((x for x in _ui_nodes(s) if rx.search(x["text"]) or rx.search(x["desc"]) or rx.search(x["id"])), None)
        if not hit:
            say(f"[{n}] nothing matches /{a.pattern}/")
            continue
        _tap(s, hit["x"], hit["y"])
        say(f"[{n}] tap {hit['x']},{hit['y']} '{(hit['text'] or hit['desc'] or hit['id'])[:60]}'")


def cmd_swipe(a):
    k = a.scale
    for n, b, s in pick(a.bots):
        sh(s, f"input swipe {int(a.x1 * k)} {int(a.y1 * k)} {int(a.x2 * k)} {int(a.y2 * k)} {a.ms}")
        say(f"[{n}] swipe")


def cmd_type(a):
    txt = a.text.replace("\\", "\\\\").replace(" ", "%s")
    for ch in "\"'`$&|;<>()":
        txt = txt.replace(ch, "\\" + ch)
    for n, b, s in pick(a.bots):
        sh(s, f"input text {txt}")
        say(f"[{n}] typed")


KEYS = {"back": 4, "home": 3, "enter": 66, "menu": 82, "recents": 187, "delete": 67, "tab": 61,
        "up": 19, "down": 20, "left": 21, "right": 22, "power": 26, "volup": 24, "voldown": 25, "end": 123}


def cmd_key(a):
    code = KEYS.get(a.key.lower(), a.key)
    for n, b, s in pick(a.bots):
        sh(s, f"input keyevent {code}")
        say(f"[{n}] key {a.key}")


def cmd_rotate(a):
    for n, b, s in pick(a.bots):
        if a.to == "auto":
            sh(s, "settings put system accelerometer_rotation 1")
        else:
            sh(s, "settings put system accelerometer_rotation 0")
            sh(s, f"settings put system user_rotation {0 if a.to == 'portrait' else 1}")
        say(f"[{n}] rotation {a.to}")


def cmd_variants(a):
    if not any([a.lang, a.dark, a.font, a.screen, a.reset]):
        die("nothing to change: use --lang, --dark, --font, --screen or --reset")
    for n, b, s in pick(a.bots):
        if a.reset:
            sh(s, "wm size reset; wm density reset; settings put system font_scale 1.0; cmd uimode night no")
            if a.package:
                sh(s, f"cmd locale set-app-locales {a.package} --user current --locales ''")
            say(f"[{n}] screen, font, theme{' and app language' if a.package else ''} reset")
            continue
        if a.lang:
            if not a.package:
                die("--lang changes the app's language (Android 13+) and needs --package")
            out = sh(s, f"cmd locale set-app-locales {a.package} --user current --locales {a.lang}")
            say(f"[{n}] {a.package} language {a.lang}" + (f" ({out})" if out else ""))
        if a.dark:
            sh(s, f"cmd uimode night {'yes' if a.dark == 'on' else 'no'}")
            say(f"[{n}] dark mode {a.dark}")
        if a.font:
            sh(s, f"settings put system font_scale {a.font}")
            say(f"[{n}] font scale {a.font}")
        if a.screen:
            m = re.fullmatch(r"(\d+)x(\d+)(?:@(\d+))?", a.screen) or die("--screen like 720x1280 or 720x1280@320")
            sh(s, f"wm size {m.group(1)}x{m.group(2)}")
            if m.group(3):
                sh(s, f"wm density {m.group(3)}")
            say(f"[{n}] screen {a.screen} (undo with --reset)")


# --------------------------------------------------------------------------- commands: hunting bugs

CRASH_RX = re.compile(r"FATAL EXCEPTION|ANR in |Fatal signal|Application Not Responding|"
                      r"Force finishing activity|E/Unity|E/flutter|Unhandled Exception")


def _watch(serial: str, name: str, package: str | None, stop: threading.Event, out: Path, events: list):
    since = sh(serial, "date +'%m-%d %H:%M:%S.000'")  # only what happens from now on; the log is not cleared
    p = subprocess.Popen([tool("adb"), "-s", serial, "logcat", "-v", "time", "-b", "main", "-b", "system", "-b", "crash",
                          "-T", since],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    ctx = 0
    with open(out, "w", encoding="utf-8") as f:
        def reader():
            nonlocal ctx
            for line in p.stdout:
                if stop.is_set():
                    break
                if CRASH_RX.search(line) and (not package or package in line or "FATAL" in line or "Fatal signal" in line
                                              or "E/Unity" in line or "E/flutter" in line):
                    events.append((name, line.strip()))
                    say(f"[{name}] !! {line.strip()[:160]}")
                    f.write("\n" + "=" * 70 + "\n")
                    ctx = 30
                if ctx:
                    f.write(line)
                    ctx -= 1
        t = threading.Thread(target=reader, daemon=True)
        t.start()
        stop.wait()
        p.terminate()
        t.join(timeout=3)


def _run_watchers(targets, package, out: Path, until):
    out.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()
    events: list = []
    files = {}
    threads = []
    for n, b, s in targets:
        files[n] = out / f"crashes-{n}-{now_tag()}.log"
        t = threading.Thread(target=_watch, args=(s, n, package, stop, files[n], events), daemon=True)
        t.start()
        threads.append(t)
    try:
        until()
    except KeyboardInterrupt:
        say("stopping ...")
    stop.set()
    for t in threads:
        t.join(timeout=5)
    return events, files


def cmd_crashwatch(a):
    targets = pick(a.bots)
    say(f"Watching {len(targets)} bot(s) for crashes and ANRs"
        + (f" in {a.package}" if a.package else "") + f" for {a.minutes} min (Ctrl+C to stop early) ...")
    events, files = _run_watchers(targets, a.package, Path(a.out), lambda: time.sleep(a.minutes * 60))
    say(f"\n{len(events)} event(s).")
    for n, f in files.items():
        cnt = sum(1 for e in events if e[0] == n)
        say(f"[{n}] {cnt} event(s){': ' + str(f) if cnt else ''}")
        if not cnt and f.exists():
            f.unlink()


def cmd_monkey(a):
    targets = pick(a.bots)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    results = {}

    def go():
        def one(t):
            n, b, s = t
            seed = a.seed if a.seed is not None else int(time.time()) % 100000
            cmd = (f"monkey -p {a.package} -s {seed} --throttle {a.throttle} --pct-syskeys 0 --pct-anyevent 0 "
                   f"{'--ignore-crashes --ignore-timeouts ' if a.keep_going else ''}-v {a.events}")
            say(f"[{n}] monkey: {a.events} events, seed {seed} ...")
            cp = adb(s, "shell", cmd, timeout=a.events * (a.throttle + 150) / 1000 + 300)
            txt = cp.stdout + cp.stderr
            f = out / f"monkey-{n}-{now_tag()}.txt"
            f.write_text(txt, encoding="utf-8")
            crash = len(re.findall(r"// CRASH:", txt))
            anr = len(re.findall(r"// NOT RESPONDING:", txt))
            done = re.search(r"Events injected: (\d+)", txt)
            results[n] = (seed, crash, anr, done.group(1) if done else "?", f)
        parallel(targets, one)

    events, files = _run_watchers(targets, a.package, out, go)
    say("")
    for n, (seed, crash, anr, done, f) in results.items():
        say(f"[{n}] seed {seed}: {done}/{a.events} events, {crash} crash(es), {anr} ANR(s). Log: {f}")
    for n, f in files.items():
        if f.exists() and not any(e[0] == n for e in events):
            f.unlink()
        elif f.exists():
            say(f"[{n}] crash details: {f}")
    say("Repeat a run exactly with the same --seed.")


def cmd_logcat(a):
    (n, b, s), = pick([a.bot])
    args = ["logcat", "-d", "-v", "time", "-t", str(a.lines)]
    if a.package:
        pid = sh(s, f"pidof {a.package}").split()
        if not pid:
            die(f"{a.package} is not running on {n}")
        args += [f"--pid={pid[0]}"]
    if a.errors:
        args += ["*:E"]
    say(adb(s, *args, timeout=60).stdout.strip() or "(empty)")


# --------------------------------------------------------------------------- main

def main(argv=None):
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252; app texts are often not
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    p = argparse.ArgumentParser(prog="bots", description="A fleet of Android emulators (bots) for testing apps and games.")
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="cmd", required=True, metavar="command")

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_, description=help_)
        sp.set_defaults(fn=fn)
        return sp

    def bots_arg(sp, help_="bot names, or 'all' (default: all running)"):
        sp.add_argument("bots", nargs="*", default=["all"], help=help_)

    add("doctor", cmd_doctor, "check the SDK, Java, acceleration and RAM; say how many bots fit")
    add("profiles", cmd_profiles, "list device profiles")

    sp = add("create", cmd_create, "create a new bot from a profile")
    sp.add_argument("name")
    sp.add_argument("--profile", default="phone", choices=list(PROFILES))
    sp.add_argument("--play", action="store_true", help="Play Store image (for closed tests; needs a manual Google login)")
    sp.add_argument("--api", type=int, default=35, help="Android API level (default 35 = Android 15)")
    sp.add_argument("--abi", help="override image ABI (default: x86_64, or arm64-v8a on ARM hosts)")
    sp.add_argument("--download", action="store_true", help="download the system image if missing (accepts SDK licenses)")
    sp.add_argument("--note", help="free text shown in `list`")

    sp = add("adopt", cmd_adopt, "register an AVD you already have as a bot")
    sp.add_argument("avd")
    sp.add_argument("--name")
    sp.add_argument("--port", type=int)
    sp.add_argument("--profile")
    sp.add_argument("--protect", action="store_true")
    sp.add_argument("--note")

    sp = add("list", cmd_list, "list bots and whether they are running")
    sp.add_argument("--avds", action="store_true", help="also show emulators on this computer that aren't bots yet")

    sp = add("start", cmd_start, "start bots and wait until they have booted")
    sp.add_argument("bots", nargs="+", help="bot names or 'all'")
    sp.add_argument("--headless", action="store_true", help="no window (servers, CI)")
    sp.add_argument("--cold", action="store_true", help="cold boot, ignore the quick-boot snapshot")
    sp.add_argument("--snapshot", help="boot from this snapshot")
    sp.add_argument("--no-wait", action="store_true")
    sp.add_argument("--timeout", type=int, default=420)
    sp.add_argument("--force", action="store_true", help="start even if RAM looks too low")

    sp = add("stop", cmd_stop, "shut bots down")
    bots_arg(sp)

    sp = add("protect", cmd_protect, "mark bots as precious: delete refuses them")
    sp.add_argument("bots", nargs="+")
    sp = add("unprotect", lambda a: cmd_protect(a, on=False), "remove the protection")
    sp.add_argument("bots", nargs="+")

    sp = add("delete", cmd_delete, "permanently delete a bot (refuses protected bots)")
    sp.add_argument("bot")
    sp.add_argument("--yes", action="store_true", help="really delete")
    sp.add_argument("--keep-avd", action="store_true", help="only forget it; keep the AVD on disk")

    sp = add("snapshot", cmd_snapshot, "save, load or list emulator snapshots of a running bot")
    sp.add_argument("action", choices=["save", "load", "list"])
    sp.add_argument("bot")
    sp.add_argument("snap", nargs="?")

    sp = add("install", cmd_install, "install an .apk, .aab, .apks or a folder of split APKs")
    sp.add_argument("file")
    bots_arg(sp)
    sp.add_argument("--grant", action="store_true", help="grant all runtime permissions")

    sp = add("launch", cmd_launch, "open an app")
    sp.add_argument("package")
    bots_arg(sp)

    sp = add("app", cmd_appctl, "stop, clear data of, or uninstall an app")
    sp.add_argument("action", choices=["stop", "clear", "uninstall"])
    sp.add_argument("package")
    bots_arg(sp)

    sp = add("info", cmd_info, "device facts, and an app's installed version")
    bots_arg(sp)
    sp.add_argument("--package")

    sp = add("shot", cmd_shot, "screenshot bots")
    bots_arg(sp)
    sp.add_argument("--out", default="bot-reports/shots")
    sp.add_argument("--label")
    sp.add_argument("--max", type=int, help="shrink to this longest side (needs Pillow); prints the tap scale")

    sp = add("record", cmd_record, "record the screen (max 180 s)")
    bots_arg(sp)
    sp.add_argument("--seconds", type=int, default=20)
    sp.add_argument("--out", default="bot-reports/videos")
    sp.add_argument("--label")

    sp = add("ui", cmd_ui, "list on-screen elements with tap coordinates (apps; games show none)")
    sp.add_argument("bot")
    sp.add_argument("--all", action="store_true", help="include unlabeled, non-clickable elements")

    sp = add("tap", cmd_tap, "tap a point (device pixels, or screenshot pixels with --scale)")
    sp.add_argument("x", type=float)
    sp.add_argument("y", type=float)
    bots_arg(sp)
    sp.add_argument("--scale", type=float, default=1.0)

    sp = add("tap-text", cmd_tap_text, "tap the first element whose text/description/id matches a regex")
    sp.add_argument("pattern")
    bots_arg(sp)

    sp = add("swipe", cmd_swipe, "swipe from x1,y1 to x2,y2")
    for k in ("x1", "y1", "x2", "y2"):
        sp.add_argument(k, type=float)
    bots_arg(sp)
    sp.add_argument("--ms", type=int, default=400)
    sp.add_argument("--scale", type=float, default=1.0)

    sp = add("type", cmd_type, "type text into the focused field")
    sp.add_argument("text")
    bots_arg(sp)

    sp = add("key", cmd_key, f"press a key: {', '.join(KEYS)} or a keycode")
    sp.add_argument("key")
    bots_arg(sp)

    sp = add("rotate", cmd_rotate, "portrait, landscape or auto")
    sp.add_argument("to", choices=["portrait", "landscape", "auto"])
    bots_arg(sp)

    sp = add("variants", cmd_variants, "app language, dark mode, font size, simulated screen size")
    bots_arg(sp)
    sp.add_argument("--package", help="app whose language --lang changes")
    sp.add_argument("--lang", help="e.g. pt-PT, en-US, es-ES (Android 13+)")
    sp.add_argument("--dark", choices=["on", "off"])
    sp.add_argument("--font", type=float, help="e.g. 1.3 for large text")
    sp.add_argument("--screen", help="e.g. 720x1280@320 to fake a small phone")
    sp.add_argument("--reset", action="store_true")

    sp = add("crashwatch", cmd_crashwatch, "watch logcat for crashes and ANRs while someone (or Claude) plays")
    bots_arg(sp)
    sp.add_argument("--package")
    sp.add_argument("--minutes", type=float, default=10)
    sp.add_argument("--out", default="bot-reports")

    sp = add("monkey", cmd_monkey, "random taps and swipes on an app, counting crashes and ANRs")
    sp.add_argument("package")
    bots_arg(sp)
    sp.add_argument("--events", type=int, default=3000)
    sp.add_argument("--throttle", type=int, default=150, help="ms between events")
    sp.add_argument("--seed", type=int)
    sp.add_argument("--keep-going", action="store_true", help="don't stop at the first crash")
    sp.add_argument("--out", default="bot-reports")

    sp = add("logcat", cmd_logcat, "recent log lines of a bot")
    sp.add_argument("bot")
    sp.add_argument("--package")
    sp.add_argument("--errors", action="store_true")
    sp.add_argument("--lines", type=int, default=300)

    a = p.parse_args(argv)
    rc = a.fn(a)
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
