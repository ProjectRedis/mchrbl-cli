#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import gc
import gzip
import json
import os
import socket
import ssl
import sys
import getpass
import time
import threading
import subprocess
import random
import re
from datetime import datetime, timedelta, timezone

def auto_install(package: str):
    print(f"[!] Installing missing module's: {package}...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", package, "-q"])

try:
    import ntplib
except ImportError:
    auto_install("ntplib")
    import ntplib

try:
    import requests
except ImportError:
    auto_install("requests")
    import requests

try:
    from colorama import Fore, Style, init as _colorama_init
except ImportError:
    auto_install("colorama")
    from colorama import Fore, Style, init as _colorama_init

from requests.adapters import HTTPAdapter
from urllib3.util import Retry
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_colorama_init(autoreset=True)
_COLORAMA = True

# ─────────────────────── KONFIGURASI ─────────────────────── #
STATE_URL       = "https://sgp-api.buy.mi.com/bbs/api/global/user/bl-switch/state"
UNLOCK_URL      = "https://sgp-api.buy.mi.com/bbs/api/global/apply/bl-auth"
SERVER_HOST     = "sgp-api.buy.mi.com"
USER_AGENT      = "okhttp/4.12.0"
TIMEOUT         = (5, 5)
BEIJING_TZ      = timezone(timedelta(hours=8))
LABEL_WIDTH     = 14
TAG_WIDTH       = 12
MSG_WIDTH       = 16
PING_SAMPLES    = 5
BRACKET_FACTOR  = 0.8
CURRENT_VERSION = "v3.3.2-Rev.2026.06.14"

# ─────────────────────── RUNTIME FLAGS ─────────────────────── #
print_lock = threading.Lock()

# ─────────────────────── LANGUAGE MANAGER (i18n) ─────────────────────── #
SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
LANG_FILE = os.path.join(SCRIPT_DIR, ".lang_config")
LOCALE_DIR = os.path.join(SCRIPT_DIR, "locales")

GITHUB_LOCALE_URL = "https://raw.githubusercontent.com/ProjectRedis/mchrbl-cli/main/locales/"

MENU_BAHASA = {
    "1": {"code": "id", "name": "Bahasa Indonesia"},
    "2": {"code": "en", "name": "English"}
}

TEXTS = {}

def init_language() -> None:
    global TEXTS
    
    force_change = "--lang" in sys.argv
    force_update = "--update-lang" in sys.argv
    lang_code = "id"
    
    if not force_change and os.path.exists(LANG_FILE):
        try:
            with open(LANG_FILE, "r", encoding="utf-8") as f:
                lang_code = f.read().strip()
        except Exception:
            pass
    else:
        print(colored("\n[Input!] Select Language:", Fore.BLUE))
        for k, v in MENU_BAHASA.items():
            print(f"  [{k}] {v['name']}")
            
        pilih = input(colored("Pilihan / Choice (1/2): ", Fore.YELLOW)).strip()
        if pilih in MENU_BAHASA:
            lang_code = MENU_BAHASA[pilih]["code"]
            
        try:
            with open(LANG_FILE, "w", encoding="utf-8") as f:
                f.write(lang_code)
        except Exception:
            pass
            
    if not os.path.exists(LOCALE_DIR):
        os.makedirs(LOCALE_DIR)
        
    json_path = os.path.join(LOCALE_DIR, f"{lang_code}.json")
    
    if force_update and os.path.exists(json_path):
        os.remove(json_path)
        log("[DL.]", "Force updating language pack...", Fore.CYAN)
    # ───────────────────────────────────────────────────────────────────────
    
    if not os.path.exists(json_path):
        print()
        log("[DL.]", f"Downloading language pack ({lang_code.upper()})...", Fore.CYAN)
        try:
            r = requests.get(f"{GITHUB_LOCALE_URL}{lang_code}.json", timeout=10)
            r.raise_for_status()
            with open(json_path, "w", encoding="utf-8") as f:
                f.write(r.text)
            log("[Success.]", "Language pack installed!", Fore.GREEN)
        except Exception as e:
            log("[Error.]", f"Failed to download language: {e}", Fore.RED)
            return
            
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            TEXTS = json.load(f)
    except Exception as e:
        log("[Error.]", f"Failed to load language file: {e}", Fore.RED)

def _t(key: str, *args) -> str:
    teks = TEXTS.get(key, key)
    if args:
        try:
            return teks.format(*args)
        except Exception:
            return teks
    return teks

# ─────────────────────── THREAD-SAFE GC ─────────────────────── #
_gc_ref_lock = threading.Lock()
_gc_ref_cnt  = 0

def _gc_disable() -> None:
    global _gc_ref_cnt
    with _gc_ref_lock:
        if _gc_ref_cnt == 0:
            gc.disable()
        _gc_ref_cnt += 1

def _gc_enable() -> None:
    global _gc_ref_cnt
    with _gc_ref_lock:
        _gc_ref_cnt = max(0, _gc_ref_cnt - 1)
        if _gc_ref_cnt == 0:
            gc.enable()

# ─────────────────────── HELPERS ─────────────────────── #
def colored(msg: str, color: str) -> str:
    return f"{color}{msg}{Style.RESET_ALL}" if _COLORAMA else msg

def log(label: str, msg: str, color: str = Fore.WHITE) -> None:
    with print_lock:
        print(f"{colored(f'{label:<{LABEL_WIDTH}}', color)} {msg}")

def get_result_meaning(code: int) -> tuple[str, str, str]:
    table = {
        1: (Fore.GREEN, "[Approved.]", _t("ticke_got")),
        2: (Fore.WHITE, "[Info.]",     _t("ticket_has")),
        3: (Fore.RED,   "[Failed.]",   _t("ticket_0")),
        6: (Fore.RED,   "[Failed.]",   _t("ticket_bussy")),
    }
    return table.get(code, (Fore.RED, "[Failed.]", f"Result code: {code}"))

# ─────────────────────── DNS PRE-RESOLVE ─────────────────────── #
def resolve_server(host: str = SERVER_HOST) -> str:
    try:
        ip = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
        log("[Info.]", f"{host} → {ip}", Fore.WHITE)
        return ip
    except Exception as e:
        log("[Warn!]", _t("dns_pre", e), Fore.YELLOW)
        return host

# ─────────────────────── TIMING ─────────────────────── #
def get_ntp_offset() -> float:
    client = ntplib.NTPClient()
    for server in ("pool.ntp.org", "id.pool.ntp.org", "time.google.com"):
        try:
            r = client.request(server, version=3, timeout=5)
            log("[Connected.]", _t("ntp_conn", server), Fore.GREEN)
            return r.offset * 1000.0
        except Exception:
            continue
    log("[Error.]", _t("ntp_err"), Fore.RED)
    return 0.0

def get_accurate_now_ms(base_time_ms: int, perf_base_ns: int, offset_ms: float) -> float:
    return base_time_ms + (time.perf_counter_ns() - perf_base_ns) / 1_000_000.0 + offset_ms

def get_next_beijing_midnight_ms() -> float:
    now_beijing   = datetime.now(BEIJING_TZ)
    next_midnight = now_beijing.replace(
        hour=0, minute=0, second=0, microsecond=0
    ) + timedelta(days=1)
    return next_midnight.timestamp() * 1000.0

# ─────────────────────── LATENCY ─────────────────────── #
def measure_latency(server_ip: str, n: int = 3) -> float:
    session = requests.Session()
    adapter = HTTPAdapter(
        max_retries=Retry(
            total=2, backoff_factor=0.3,
            status_forcelist=[502, 503, 504],
            allowed_methods={"HEAD"},
        )
    )
    session.mount("https://", adapter)
    samples: list[float] = []
    try:
        for _ in range(n):
            try:
                t0 = time.perf_counter()
                session.head(
                    f"https://{server_ip}",
                    timeout=TIMEOUT,
                    headers={"User-Agent": USER_AGENT, "Host": SERVER_HOST},
                    verify=False,
                )
                samples.append((time.perf_counter() - t0) * 1000.0)
            except requests.RequestException:
                pass
    finally:
        session.close()
    return sum(samples) / len(samples) if samples else 300.0

def weighted_median(data: list[float], weights: list[float] | None = None) -> float:
    if not data:
        return 0.0
    if weights is None:
        weights = [1.0] * len(data)
    combined   = sorted(zip(data, weights), key=lambda x: x[0])
    half       = sum(weights) / 2.0
    cumulative = 0.0
    for val, w in combined:
        cumulative += w
        if cumulative >= half:
            return val
    return combined[-1][0]

# ─────────────────────── CPU / BIG CORE DETECTION ─────────────────────── #
def get_big_cores(threshold: int = 2_000_000) -> list[int]:
    cpu_dir = "/sys/devices/system/cpu/"
    cores: list[int] = []
    for i in range(os.cpu_count() or 1):
        try:
            with open(f"{cpu_dir}cpu{i}/cpufreq/cpuinfo_max_freq") as f:
                if int(f.read().strip()) >= threshold:
                    cores.append(i)
        except OSError:
            continue
    cores.sort()
    if cores:
        for c in cores:
            log("[Info.]", f"CPU{c} " + _t("cpu_ok"), Fore.WHITE)
    else:
        log("[Info.]", _t("cpu_no"), Fore.WHITE)
    return cores
    
# ─────────────────────── TOKEN CHECK ─────────────────────── #
def test_cookie(cookie: str, label: str) -> bool:
    try:
        res      = requests.get(
            STATE_URL,
            headers={"Cookie": cookie, "User-Agent": USER_AGENT},
            timeout=10,
            verify=True,
        )
        res_json = res.json()
        code     = res_json.get("code", -1)

        if code == 100004:
            log("[Error.]", f"{label} " + _t("cookie_err"), Fore.RED)
            return False

        data      = res_json.get("data", {})
        is_pass   = data.get("is_pass", -1)
        btn_state = data.get("button_state", -1)
        deadline  = data.get("deadline_format", "")

        if is_pass == 1:
            log("[Approved.]", f"Status {label}: " + _t("acc_got", deadline), Fore.GREEN)
            return True

        col, tag, msg = {
            (4, 1): (Fore.GREEN,  "[Valid.]",   f"Status {label}: " + _t("acc_ok")),
            (4, 2): (Fore.RED,    "[Blocked.]", f"Status {label}: " + _t("acc_block", deadline)),
            (4, 3): (Fore.YELLOW, "[Warn!.]",   f"Status {label}: " + _t("acc_warn")),
        }.get(
            (is_pass, btn_state),
            (Fore.WHITE, "[Account.]", f"{label} " + _t("acc_pass", is_pass)),
        )
        log(tag, msg, col)
        
        if (is_pass, btn_state) == (4, 1):
            return True
        
        return False

    except Exception as e:
        log("[Error.]", f"{label} " + _t("acc_down", e), Fore.RED)
        return False

# ─────────────────────── UPDATE CHECKER ─────────────────────── #
def check_update() -> None:
    BASE          = "https://raw.githubusercontent.com/ProjectRedis/mchrbl-cli/refs/heads/main/"
    url_script    = BASE + "herorbl.py"
    url_changelog = BASE + "changelog.txt"

    try:
        r = requests.get(url_script, timeout=5)
        r.raise_for_status()
    except Exception as e:
        log("[Error.]", _t("up_err", e), Fore.RED)
        return

    remote_version: str | None = None
    for line in r.text.splitlines():
        if line.startswith("CURRENT_VERSION"):
            remote_version = line.split("=", 1)[1].strip().strip('"').strip("'")
            break

    if not remote_version:
        log("[Info.]", _t("up_no"), Fore.WHITE)
        return
        
    if remote_version == CURRENT_VERSION:
        log("[Info.]", _t("up_ok", CURRENT_VERSION), Fore.WHITE)
        return

    print()
    log("[Info.]", _t("up_up", remote_version), Fore.WHITE)
    log("[Info.]", _t("up_now", CURRENT_VERSION), Fore.WHITE)
    print()
    log("[Changelog.]", "", Fore.YELLOW)

    try:
        r2 = requests.get(url_changelog, timeout=5)
        r2.raise_for_status()

        target_version = remote_version.split('-')[0]
        
        capture = False
        captured_lines = []
        
        for line in r2.text.splitlines():
            line_stripped = line.strip()
            
            if capture and line_stripped.startswith("----"):
                break
                
            if line_stripped.startswith(target_version):
                capture = True
                
            if capture:
                captured_lines.append(line_stripped)

        if captured_lines:
            for line in captured_lines:
                if line:
                    print(" " * LABEL_WIDTH + line)
                else:
                    print()
        else:
            for line in r2.text.strip().splitlines()[:10]:
                if line.strip():
                    print(" " * LABEL_WIDTH + line)

    except Exception:
        log("[Info.]", _t("change_no"), Fore.WHITE)

    print()
    jawab = input(
        colored(f'{"[Input!]":<{LABEL_WIDTH}}', Fore.BLUE) + _t("up_ask")
    ).strip().lower()

    if jawab != "y":
        log("[Info.]", _t("up_late"), Fore.WHITE)
        return

    import sys
    try:
        script_path = os.path.abspath(sys.argv[0])
        r3          = requests.get(url_script, timeout=10)
        r3.raise_for_status()
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(r3.text)
            
        if os.path.exists(LOCALE_DIR):
            import shutil
            shutil.rmtree(LOCALE_DIR, ignore_errors=True)
        # ───────────────────────────────────────────────────────────
            
        log("[Success.]", _t("up_done", remote_version), Fore.GREEN)
        log("[Info.]", _t("up_go"), Fore.WHITE)
        raise SystemExit(0)
    except SystemExit:
        raise
    except Exception as e:
        log("[Error.]", _t("up_fail", e), Fore.RED)
        
# ─────────────────────── HTTP HELPERS ─────────────────────── #
def _recv_full(ssock: ssl.SSLSocket, buf: int = 4096) -> bytes:
    data = b""
    while True:
        try:
            chunk = ssock.recv(buf)
        except (ssl.SSLError, OSError):
            break
        if not chunk:
            break
        data += chunk
        if b"\r\n\r\n" not in data:
            continue
        headers_raw, body = data.split(b"\r\n\r\n", 1)
        if b"transfer-encoding: chunked" in headers_raw.lower():
            if data.endswith(b"0\r\n\r\n"):
                break
        else:
            cl = None
            for line in headers_raw.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    cl = int(line.split(b":", 1)[1].strip())
                    break
            if cl is None or len(body) >= cl:
                break
    return data

def _decode_chunked(body: bytes) -> bytes:
    out = b""
    while body:
        idx = body.find(b"\r\n")
        if idx == -1:
            break
        try:
            size = int(body[:idx], 16)
        except ValueError:
            break
        if size == 0:
            break
        out  += body[idx + 2: idx + 2 + size]
        body  = body[idx + 2 + size + 2:]
    return out

def _parse_response(raw: bytes) -> dict:
    if b"\r\n\r\n" not in raw:
        return {}

    headers_raw, body = raw.split(b"\r\n\r\n", 1)
    headers_lower = headers_raw.lower()

    if b"transfer-encoding: chunked" in headers_lower:
        body = _decode_chunked(body)

    if b"content-encoding: gzip" in headers_lower:
        try:
            body = gzip.decompress(body)
        except Exception:
            pass

    try:
        return json.loads(
            body.decode("utf-8", errors="ignore")
        )
    except Exception:
        return {}

# ─────────────────────── SEND WAVE (THREAD) ─────────────────────── #
def send_wave(
    id:           int,
    target_ms:    float,
    cookie:       str,
    server_ip:    str,
    base_time_ms: int,
    perf_base_ns: int,
    offset_ms:    float,
    label:        str,
    output:       dict,
    core_id:      int | None = None,
) -> None:

    if core_id is not None:
        try:
            os.sched_setaffinity(0, {core_id})
            log("[Success.]", _t("pin_ok", id, core_id), Fore.GREEN)
        except Exception as e:
            log("[Warn!]", _t("pin_no", id, e), Fore.YELLOW)
             
    hex_chars = "0123456789ABCDEF"
    fake_device_id = ''.join(random.choices(hex_chars, k=39))
    
    payload = '{"is_retry":false}' if id == 1 else '{"is_retry":true}'
    payload_bytes = payload.encode("utf-8")
    
    dynamic_cookie = cookie
    if "deviceId=" in dynamic_cookie:
        dynamic_cookie = re.sub(r'deviceId=[^;]+', f'deviceId={fake_device_id}', dynamic_cookie)
    else:
        dynamic_cookie = dynamic_cookie if dynamic_cookie.endswith(';') else dynamic_cookie + ';'
        dynamic_cookie += f'deviceId={fake_device_id};'

    raw_req = (
        f"POST /bbs/api/global/apply/bl-auth HTTP/1.1\r\n"
        f"Cookie: {dynamic_cookie}\r\n"
        f"Accept: application/json\r\n"
        f"Content-Type: application/json; charset=utf-8\r\n"
        f"Content-Length: {len(payload_bytes)}\r\n"
        f"Host: {SERVER_HOST}\r\n"
        f"Connection: close\r\n"
        f"Accept-Encoding: gzip\r\n"
        f"User-Agent: {USER_AGENT}\r\n"
        f"\r\n"
    ).encode("utf-8") + payload_bytes
    
    # ─────────────────────────────────────────────────────────

    sock = None
    try:
        sock = socket.create_connection((server_ip, 443), timeout=5)
        ctx  = ssl.create_default_context()
        with ctx.wrap_socket(sock, server_hostname=SERVER_HOST) as ssock:

            while True:
                remain = target_ms - get_accurate_now_ms(base_time_ms, perf_base_ns, offset_ms)
                if remain > 20:
                    time.sleep((remain - 20) / 1000.0)
                elif remain > 2:
                    time.sleep(0)
                else:
                    break

            _gc_disable()
            try:
                while get_accurate_now_ms(base_time_ms, perf_base_ns, offset_ms) < target_ms:
                    pass
                ssock.sendall(raw_req)
                drift = get_accurate_now_ms(base_time_ms, perf_base_ns, offset_ms) - target_ms
            except Exception as e:
                output[id - 1] = (
                    Fore.RED,
                    f"{'[Failed.]':<{TAG_WIDTH}}",
                    f"{'Send Error':<{MSG_WIDTH}} [Hero-{id:02d}] | {e}",
                )
                return
            finally:
                _gc_enable()

            try:
                raw_resp  = _recv_full(ssock)
                resp_json = _parse_response(raw_resp)
                result = (resp_json.get("data") or {}).get("apply_result", -1)
                col, tag, msg = get_result_meaning(result)
                output[id - 1] = (
                    col,
                    f"{tag:<{TAG_WIDTH}}",
                    f"{msg:<{MSG_WIDTH}} [Hero-{id:02d}]   | Drift: {drift:+.2f}ms",
                )
            except Exception as e:
                output[id - 1] = (
                    Fore.RED,
                    f"{'[Failed.]':<{TAG_WIDTH}}",
                    f"{'Parse Error':<{MSG_WIDTH}} [Hero-{id:02d}]   | Drift: {drift:+.2f}ms | {e}",
                )

    except Exception as e:
        if sock:
            try:
                sock.close()
            except Exception:
                pass
        output[id - 1] = (
            Fore.RED,
            f"{'[Failed.]':<{TAG_WIDTH}}",
            f"{'SSL/Connect Error':<{MSG_WIDTH}} [Hero-{id:02d}] | {e}",
        )

# ─────────────────────── COUNTDOWN ─────────────────────── #
def _format_remain(ms: float) -> str:
    s = int(ms / 1000)
    h, rem = divmod(abs(s), 3600)
    m, s_  = divmod(rem, 60)
    return f"{h % 24:02d}:{m:02d}:{s_:02d}" if s > 59 else f"{s_:02d}s"

def _countdown(
    label:        str,
    until_ms:     float,
    base_time_ms: int,
    perf_base_ns: int,
    offset_ms:    float,
) -> None:
    prefix = colored(f"{'[Wait!]':<{LABEL_WIDTH}}", Fore.CYAN)
    while True:
        remain = until_ms - get_accurate_now_ms(base_time_ms, perf_base_ns, offset_ms)
        if remain <= 0:
            break
        dots = "." * (int(time.time() * 2) % 4)
        print(f"{prefix} {label} {_format_remain(remain):<8} {dots:<3}", end="\r", flush=True)
        time.sleep(0.05)
    print()

# ─────────────────────── MAIN ─────────────────────── #
def main() -> None:
    print(colored("=" * 56,                               Fore.CYAN))
    print(colored("                 MI-COMMUNITY HERO REQ-BL",  Fore.WHITE))
    print(colored(f"                  {CURRENT_VERSION}",    Fore.YELLOW))
    print(colored("                   GitHub @ProjectRedis",    Fore.BLUE))
    print(colored("=" * 56,                               Fore.CYAN))
    print()

    init_language()

    check_update()
    print()
    big_cores = get_big_cores()
    print()

    # ── 1. Input & validasi cookie ──
    valid_a = False
    valid_b = False
    cookie_a = ""
    cookie_b = ""

    while not (valid_a or valid_b):
        
        if not valid_a:
            cookie_a = getpass.getpass(
                colored(f'{"[Input!]":<{LABEL_WIDTH}}', Fore.BLUE) + " " + _t("cookie_a") + _t("cookie_skip")
            ).strip()
            
            if cookie_a:
                log("[Success.]", _t("cookie_acc", "A") + colored("**********", Fore.WHITE), Fore.GREEN)
                log("[Check!]", _t("cookie_check", "A"), Fore.MAGENTA)
                if test_cookie(cookie_a, "Token-A"):
                    valid_a = True
                else:
                    log("[Error.]", _t("cookie_ax"), Fore.RED)
            else:
                log("[Info.]", _t("cookie_as"), Fore.WHITE)

        print()

        if not valid_b:
            cookie_b = getpass.getpass(
                colored(f'{"[Input!]":<{LABEL_WIDTH}}', Fore.BLUE) + " " + _t("cookie_b") + _t("cookie_skip")
            ).strip()
            
            if cookie_b:
                log("[Success.]", _t("cookie_acc", "B") + colored("**********", Fore.WHITE), Fore.GREEN)
                log("[Check!]", _t("cookie_check", "B"), Fore.MAGENTA)
                if test_cookie(cookie_b, "Token-B"):
                    valid_b = True
                else:
                    log("[Error.]", _t("cookie_bx"), Fore.RED)
            else:
                log("[Info.]", _t("cookie_bs"), Fore.WHITE)

        if not valid_a and not valid_b:
            print()
            log("[Warn!]", _t("cookie_warn"), Fore.YELLOW)
            print()
            
    print()
    log("[Success.]", _t("cookie_ready"), Fore.GREEN)
    
    # ── 2. DNS Pre-resolve ──
    print()
    log("[Check!]", _t("dns_pre_start", SERVER_HOST), Fore.MAGENTA)
    server_ip = resolve_server()

    # ── 3. NTP sync ──
    print()
    log("[Check!]", _t("ntp_sync"), Fore.MAGENTA)
    ntp_offset  = get_ntp_offset()
    perf_base   = time.perf_counter_ns()
    time_base   = int(time.time() * 1000)
    log("[Info.]", _t("ntp_offset", ntp_offset), Fore.WHITE)

    # ── 4. Konfigurasi jadwal ──
    print()
    debug = (
        input(colored(f'{"[Input!]":<{LABEL_WIDTH}}', Fore.BLUE) + _t("input_debug"))
        .strip().lower() == "y"
    )
    target_ms = (
        get_accurate_now_ms(time_base, perf_base, ntp_offset) + 20_000
        if debug else
        get_next_beijing_midnight_ms()
    )

    raw_count     = input(
        colored(f'{"[Input!]":<{LABEL_WIDTH}}', Fore.BLUE) + " " + _t("input_hero")
    ).strip()
    trigger_count = int(raw_count) if raw_count.isdigit() and int(raw_count) > 0 else 4

    raw_margin    = input(
        colored(f'{"[Input!]":<{LABEL_WIDTH}}', Fore.BLUE) + " " + _t("input_margin")
    ).strip()
    safety_margin = int(raw_margin) if raw_margin.lstrip('-').isdigit() else 30
    
    # ── 5. Tunggu fase ping ──
    _countdown(_t("wait_start"), target_ms - 15_000, time_base, perf_base, ntp_offset)

    # ── 6. Ping sampling ──
    log("[Info.]", _t("ping_go", PING_SAMPLES, server_ip), Fore.WHITE)
    ping_samples: list[float] = []
    ping_weights: list[float] = []
    for i in range(PING_SAMPLES):
        sample = measure_latency(server_ip)
        ping_samples.append(sample)
        ping_weights.append(float(i + 1))
        log("[Ping!]", _t("ping_sample", sample), Fore.MAGENTA)
        time.sleep(1)

    eff_latency  = weighted_median(ping_samples, ping_weights)
    base_send    = target_ms - eff_latency
    bracket_half = int(eff_latency * BRACKET_FACTOR) + 50
    log("[Active.]", _t("dyn_bracket", bracket_half, eff_latency), Fore.GREEN)

    # ── 7. Hitung offset tiap Hero ──
    if trigger_count > 1:
        span    = 2.0 * (bracket_half - safety_margin)
        offsets = [
            int(-bracket_half + safety_margin + span * i / (trigger_count - 1))
            for i in range(trigger_count)
        ]
    else:
        offsets = [0]

    # ── 8. Siapkan thread Hero ──
    output: dict[int, tuple] = {}
    threads: list[threading.Thread] = []

    for idx, wave_off in enumerate(offsets):
        wave_id    = idx + 1
        use_b      = bool(cookie_b) and (wave_id % 2 == 0)
        tok_label  = "Tok-B" if use_b else "Tok-A"
        cookie_use = cookie_b if use_b else cookie_a
        wave_target = base_send + wave_off

        dt_cst = datetime.fromtimestamp(wave_target / 1000.0, BEIJING_TZ)
        ts     = f"{dt_cst.strftime('%H:%M:%S')}.{int(wave_target % 1000):03d}"
        log("[Info.]", _t("hero_standby", wave_id, tok_label, ts, wave_off))

        core_id = big_cores[idx % len(big_cores)] if big_cores else None
        t = threading.Thread(
            target=send_wave,
            args=(
                wave_id, wave_target, cookie_use, server_ip,
                time_base, perf_base, ntp_offset,
                tok_label, output, core_id,
            ),
            daemon=True,
        )
        threads.append(t)
        time.sleep(0.3)

    # ── 9. Countdown menuju aba-aba ──
    _countdown(_t("wait_war"), base_send - 1000, time_base, perf_base, ntp_offset)

    # ── 10. Tembak! ──
    log("[Active.]", _t("spin_lock_active"), Fore.GREEN)
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    time.sleep(0.3)

    # ── 11. Laporan ──
    print()
    log("[Info.]", _t("war_log"), Fore.WHITE)
    time.sleep(1)

    for i in range(trigger_count):
        item = output.get(i)
        if isinstance(item, tuple) and len(item) == 3:
            col, tag, detail = item
            log(tag.strip(), detail, col)
        else:
            log("[Failed.]", _t("hero_down", i + 1), Fore.RED)

    print()
    log("[Completed.]", _t("war_done"), Fore.GREEN)

if __name__ == "__main__":
    main()
