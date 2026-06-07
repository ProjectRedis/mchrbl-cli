#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import gc
import json
import os
import socket
import ssl
import getpass
import time
import threading
from datetime import datetime, timedelta, timezone

import ntplib
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    from colorama import Fore, Style, init as _colorama_init
    _colorama_init(autoreset=True)
    _COLORAMA = True
except ImportError:
    _COLORAMA = False
    class Fore:  # type: ignore
        MAGENTA = BLUE = GREEN = RED = YELLOW = CYAN = WHITE = ""
    class Style:  # type: ignore
        RESET_ALL = ""

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
SAFETY_MARGIN   = 30
CURRENT_VERSION = "v3.0.0-Rev.2026.06.08"

# ─────────────────────── RUNTIME FLAGS ─────────────────────── #

print_lock = threading.Lock()

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
        1: (Fore.GREEN, "[Approved.]", "Tiket didapat!"),
        2: (Fore.WHITE, "[Info.]",     "Sudah punya tiket"),
        3: (Fore.RED,   "[Failed.]",   "Kuota habis"),
        6: (Fore.RED,   "[Failed.]",   "Server sibuk"),
    }
    return table.get(code, (Fore.RED, "[Failed.]", f"Result code: {code}"))

# ─────────────────────── DNS PRE-RESOLVE ─────────────────────── #
def resolve_server(host: str = SERVER_HOST) -> str:
    try:
        ip = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
        log("[Info.]", f"{host} → {ip}", Fore.WHITE)
        return ip
    except Exception as e:
        log("[Warn!]", f"DNS pre-resolve gagal, pakai hostname: {e}", Fore.YELLOW)
        return host

# ─────────────────────── TIMING ─────────────────────── #
def get_ntp_offset() -> float:
    client = ntplib.NTPClient()
    for server in ("pool.ntp.org", "id.pool.ntp.org", "time.google.com"):
        try:
            r = client.request(server, version=3, timeout=5)
            log("[Connected.]", f"Terhubung ke '{server}'", Fore.GREEN)
            return r.offset * 1000.0
        except Exception:
            continue
    log("[Error]", "Semua server NTP gagal – offset = 0", Fore.RED)
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
            log("[Info.]", f"CPU{c} terdeteksi sebagai big core", Fore.WHITE)
    else:
        log("[Info.]", "Big core tidak terdeteksi (path /sys tidak tersedia)", Fore.WHITE)
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
            log("[Error.]", f"{label} Kadaluarsa / Need Login!", Fore.RED)
            return False

        data      = res_json.get("data", {})
        is_pass   = data.get("is_pass", -1)
        btn_state = data.get("button_state", -1)
        deadline  = data.get("deadline_format", "")

        if is_pass == 1:
            log("[Approved..]", f"Status {label}: APPROVED (Berlaku s/d {deadline})", Fore.GREEN)
            return True

        col, tag, msg = {
            (4, 1): (Fore.GREEN,  "[Valid.]",   f"Status {label}: ELIGIBLE (Siap War!)"),
            (4, 2): (Fore.RED,    "[Blocked.]", f"Status {label}: BLOCKED hingga {deadline}"),
            (4, 3): (Fore.YELLOW, "[Warn!.]",   f"Status {label}: Akun belum berumur 30 Hari!"),
        }.get(
            (is_pass, btn_state),
            (Fore.WHITE, "[Account.]", f"{label} Valid (Unknown is_pass: {is_pass})"),
        )
        log(tag, msg, col)
        return True

    except Exception as e:
        log("[Error.]", f"{label} Gagal terhubung: {e}", Fore.RED)
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
        log("[Error.]", f"Gagal cek update: {e}", Fore.RED)
        return

    remote_version: str | None = None
    for line in r.text.splitlines():
        if line.startswith("CURRENT_VERSION"):
            remote_version = line.split("=", 1)[1].strip().strip('"').strip("'")
            break

    if not remote_version:
        log("[Info.]", "Tidak bisa membaca versi di GitHub.", Fore.WHITE)
        return
    if remote_version == CURRENT_VERSION:
        log("[Info.]", f"Script sudah terbaru ({CURRENT_VERSION})", Fore.WHITE)
        return

    print()
    log("[Info.]", f"Update tersedia : {remote_version}", Fore.WHITE)
    log("[Info.]", f"Versi saat ini  : {CURRENT_VERSION}", Fore.WHITE)
    print()

    try:
        r2 = requests.get(url_changelog, timeout=5)
        r2.raise_for_status()
        for line in r2.text.strip().splitlines():
            print(" " * LABEL_WIDTH + line)
    except Exception:
        log("[Info.]", "Changelog tidak ditemukan.", Fore.WHITE)

    print()
    jawab = input(
        colored(f'{"[Input!]":<{LABEL_WIDTH}}', Fore.YELLOW) + " Update sekarang? (y/n): "
    ).strip().lower()

    if jawab != "y":
        log("[Info.]", "Melanjutkan menggunakan versi saat ini.", Fore.WHITE)
        return

    import sys
    try:
        script_path = os.path.abspath(sys.argv[0])
        r3          = requests.get(url_script, timeout=10)
        r3.raise_for_status()
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(r3.text)
        log("[Success.]", f"Berhasil update ke {remote_version}", Fore.GREEN)
        log("[Info.]",    "Silakan jalankan ulang script.",        Fore.WHITE)
        raise SystemExit(0)
    except SystemExit:
        raise
    except Exception as e:
        log("[Error.]", f"Gagal update otomatis: {e}", Fore.RED)

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
    if b"transfer-encoding: chunked" in headers_raw.lower():
        body = _decode_chunked(body)
    return json.loads(body.decode("utf-8", errors="ignore"))

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
            log("[Success.]", f"Hero-{id:02d} diikat ke core {core_id}", Fore.GREEN)
        except Exception as e:
            log("[Warn!]", f"Hero-{id:02d} floating (gagal pin core): {e}", Fore.YELLOW)
            
    payload = '{"is_retry": false}'
    raw_req = (
        f"POST /bbs/api/global/apply/bl-auth HTTP/1.1\r\n"
        f"Host: {SERVER_HOST}\r\n"
        f"User-Agent: {USER_AGENT}\r\n"
        f"Cookie: {cookie}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(payload)}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
        f"{payload}"
    ).encode("utf-8")

    sock = None
    try:
        sock = socket.create_connection((server_ip, 443), timeout=5)
        ctx  = ssl.create_default_context()
        with ctx.wrap_socket(sock, server_hostname=SERVER_HOST) as ssock:

            # ── Phase 1: Sleep kasar mendekati target ──
            while True:
                remain = target_ms - get_accurate_now_ms(base_time_ms, perf_base_ns, offset_ms)
                if remain > 20:
                    time.sleep((remain - 20) / 1000.0)
                elif remain > 2:
                    time.sleep(0)
                else:
                    break

            # ── Phase 2: Spin-lock presisi (shared GC ref counter) ──
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

            # ── Phase 3: Parse response ──
            try:
                raw_resp  = _recv_full(ssock)
                resp_json = _parse_response(raw_resp)
                result    = resp_json.get("data", {}).get("apply_result", -1)
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
    print(colored("             MI-COMMUNITY HERO REQ-BL",  Fore.WHITE))
    print(colored(f"                 {CURRENT_VERSION}",    Fore.YELLOW))
    print(colored("               GitHub @ProjectRedis",    Fore.BLUE))
    print(colored("=" * 56,                               Fore.CYAN))
    print()

    check_update()
    print()
    big_cores = get_big_cores()
    print()

    # ── 1. Input & validasi cookie ──
    while True:
        cookie_a = getpass.getpass(
            colored(f'{"[Input!]":<{LABEL_WIDTH}}', Fore.YELLOW) + " Paste Cookie A: "
        ).strip()
        if not cookie_a:
            log("[Error]", "Cookie A tidak boleh kosong!\n", Fore.RED)
            continue
        log("[Success.]", "Cookie A diterima: " + colored("**********", Fore.WHITE), Fore.GREEN)

        cookie_b = getpass.getpass(
            colored(f'{"[Input!]":<{LABEL_WIDTH}}', Fore.YELLOW) + " Paste Cookie B (Enter jika kosong): "
        ).strip()
        if cookie_b:
            log("[Success.]", "Cookie B diterima: " + colored("**********", Fore.WHITE), Fore.GREEN)
        print()
        log("[Check!]", "Memeriksa status Token-A...", Fore.MAGENTA)
        valid_a = test_cookie(cookie_a, "Token-A")
        valid_b = True
        if cookie_b:
            log("[Check!]", "Memeriksa status Token-B...", Fore.MAGENTA)
            valid_b = test_cookie(cookie_b, "Token-B")
        if valid_a and valid_b:
            break
        print()
        log("[Info.]", "Silakan masukkan ulang seluruh credential.\n", Fore.YELLOW)

    # ── 2. DNS Pre-resolve ──
    print()
    log("[Check!]", f"Pre-resolving {SERVER_HOST}...", Fore.MAGENTA)
    server_ip = resolve_server()

    # ── 3. NTP sync ──
    print()
    log("[Check!]", "Sinkronisasi waktu NTP...", Fore.MAGENTA)
    ntp_offset  = get_ntp_offset()
    perf_base   = time.perf_counter_ns()
    time_base   = int(time.time() * 1000)
    log("[Info.]", f"NTP Offset: {ntp_offset:.3f} ms", Fore.WHITE)

    # ── 4. Konfigurasi jadwal ──
    print()
    debug = (
        input(colored(f'{"[Input!]":<{LABEL_WIDTH}}', Fore.YELLOW) + " Mode Debug (y/n): ")
        .strip().lower() == "y"
    )
    target_ms = (
        get_accurate_now_ms(time_base, perf_base, ntp_offset) + 20_000
        if debug else
        get_next_beijing_midnight_ms()
    )

    raw_count     = input(
        colored(f'{"[Input!]":<{LABEL_WIDTH}}', Fore.YELLOW) + " Recruit Hero (Default 4): "
    ).strip()
    trigger_count = int(raw_count) if raw_count.isdigit() and int(raw_count) > 0 else 4

    # ── 5. Tunggu fase ping ──
    _countdown("Menunggu start:", target_ms - 15_000, time_base, perf_base, ntp_offset)

    # ── 6. Ping sampling ──
    log("[Info.]", f"Mulai PING! {PING_SAMPLES} kali ke {server_ip}...", Fore.WHITE)
    ping_samples: list[float] = []
    ping_weights: list[float] = []
    for i in range(PING_SAMPLES):
        sample = measure_latency(server_ip)
        ping_samples.append(sample)
        ping_weights.append(float(i + 1))
        log("[Ping!]", f"Sample latency: {sample:.1f}ms", Fore.MAGENTA)
        time.sleep(1)

    eff_latency  = weighted_median(ping_samples, ping_weights)
    base_send    = target_ms - eff_latency
    bracket_half = int(eff_latency * BRACKET_FACTOR) + 50
    log(
        "[Active.]",
        f"Dynamic Bracket ±{bracket_half}ms (Weighted Median: {eff_latency:.1f}ms)",
        Fore.GREEN,
    )

    # ── 7. Hitung offset tiap Hero ──
    if trigger_count > 1:
        span    = 2.0 * (bracket_half - SAFETY_MARGIN)
        offsets = [
            int(-bracket_half + SAFETY_MARGIN + span * i / (trigger_count - 1))
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
        log("[Info.]", f"Hero-{wave_id:02d} [{tok_label}] Standby at {ts} CST [Bracket: {wave_off:+}ms]")

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
    _countdown("Menunggu aba-aba", base_send - 1000, time_base, perf_base, ntp_offset)

    # ── 10. Tembak! ──
    log("[Active.]", "Hardware Spin-Lock mode active...", Fore.GREEN)
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    time.sleep(0.3)

    # ── 11. Laporan ──
    print()
    log("[Info.]", "Laporan hasil war.", Fore.WHITE)
    time.sleep(1)

    for i in range(trigger_count):
        item = output.get(i)
        if isinstance(item, tuple) and len(item) == 3:
            col, tag, detail = item
            log(tag.strip(), detail, col)
        else:
            log("[Failed.]", f"Hero-{i + 1:02d} mengalami gangguan koneksi.", Fore.RED)

    print()
    log("[Completed.]", "Pertempuran selesai.", Fore.GREEN)

if __name__ == "__main__":
    main()
    
