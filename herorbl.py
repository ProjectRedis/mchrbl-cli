#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import gc
import socket
import ssl
import json
import getpass
import statistics
import time
from datetime import datetime, timedelta, timezone
import multiprocessing as mp

import ntplib
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

try:
    from colorama import Fore, Style, init
    init(autoreset=True)
except ImportError:
    class Fore:
        MAGENTA = GREEN = RED = YELLOW = CYAN = WHITE = ""
    class Style:
        RESET_ALL = ""

# ================= KONFIGURASI ================= #
INFO_URL = "https://sgp-api.buy.mi.com/bbs/api/global/user/dialog"
UNLOCK_URL = "https://sgp-api.buy.mi.com/bbs/api/global/apply/bl-auth"
STATE_URL = "https://sgp-api.buy.mi.com/bbs/api/global/user/bl-switch/state"
USER_AGENT = "okhttp/4.12.0"
TIMEOUT = (5, 5)
BEIJING_TZ = timezone(timedelta(hours=8))
LABEL_WIDTH = 14
TAG_WIDTH = 12
MSG_WIDTH = 16
PING_SAMPLES = 5
BRACKET_FACTOR = 0.8
CURRENT_VERSION = "v2.3.1-Rev.2026.06.07"

print_lock = mp.Lock()

def colored(msg, color):
    return f"{color}{msg}{Style.RESET_ALL}" if hasattr(Fore, "MAGENTA") else msg

def log(label, msg, color=Fore.WHITE):
    with print_lock:
        print(f"{colored(f'{label:<{LABEL_WIDTH}}', color)} {msg}")

def get_result_meaning(code):
    if code == 1: return Fore.GREEN, "[Approved.]", "Tiket didapat!"
    if code == 2: return Fore.WHITE, "[Info.]", "Sudah punya tiket"
    if code == 3: return Fore.RED, "[Failed.]", "Kuota habis"
    if code == 6: return Fore.RED, "[Failed.]", "Server sibuk"
    return Fore.RED, "[Failed.]", f"Result code:{code}"

# ================= CORE DETECTION ================= #
def get_big_cores(threshold=2000000):
    cores = []
    cpu_dir = "/sys/devices/system/cpu/"
    for i in range(os.cpu_count() or 1):
        try:
            with open(f"{cpu_dir}cpu{i}/cpufreq/cpuinfo_max_freq") as f:
                maxf = int(f.read().strip())
            if maxf >= threshold:
                cores.append(i)
        except:
            continue
    cores.sort()
    for c in cores:
        log("[Info.]", f"CPU{c} terdeteksi sebagai big core", Fore.WHITE)
    return cores

def get_ntp_offset():
    client = ntplib.NTPClient()
    for server in ["pool.ntp.org", "id.pool.ntp.org", "time.google.com"]:
        try:
            r = client.request(server, version=3, timeout=5)
            log("[Connected.]", f"Terhubung ke '{server}'", Fore.GREEN)
            return int(r.offset * 1000)
        except: 
            continue
    log("[Error]", "Semua server NTP gagal", Fore.RED)
    return 0

def get_accurate_now_ms(base_time_ms, perf_base_ns, offset):
    now_perf_ns = time.perf_counter_ns()
    elapsed_ns = now_perf_ns - perf_base_ns
    elapsed_ms = elapsed_ns // 1_000_000
    return base_time_ms + elapsed_ms + offset

def get_next_beijing_midnight_ms():
    now_beijing = datetime.now(BEIJING_TZ)
    today_midnight = now_beijing.replace(hour=0, minute=0, second=0, microsecond=0)
    if now_beijing >= today_midnight:
        next_midnight = today_midnight + timedelta(days=1)
    else:
        next_midnight = today_midnight
    return int(next_midnight.timestamp() * 1000)

def measure_latency():
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=Retry(total=2, backoff_factor=0.3,
                                                           status_forcelist=[502, 503, 504],
                                                           allowed_methods={"HEAD"})))
    times = []
    for _ in range(3):
        try:
            start = time.time()
            session.head("https://sgp-api.buy.mi.com", timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
            times.append((time.time() - start) * 1000)
        except requests.RequestException: 
            pass
    session.close()
    return int(sum(times) / len(times)) if times else 300

# ================= PURE PYTHON WEIGHTED MEDIAN ================= #
def weighted_median(data, weights=None):
    """
    Weighted median tanpa numpy.
    """
    data = list(data)
    if weights is None:
        weights = [1]*len(data)
    combined = sorted(zip(data, weights), key=lambda x: x[0])
    total_weight = sum(weights)
    cum_weight = 0
    for val, w in combined:
        cum_weight += w
        if cum_weight >= total_weight / 2:
            return val
    return combined[-1][0]

# ================= CORE API TASK ================= #
def test_cookie(cookie, token_label):
    headers = {"Cookie": cookie, "User-Agent": USER_AGENT}
    try:
        res = requests.get(STATE_URL, headers=headers, timeout=10, verify=True)
        res_json = res.json()
        code = res_json.get("code", -1)

        if code == 100004:
            log("[Error.]", f"{token_label} Kadaluarsa / Need Login!", Fore.RED)
            return False

        data = res_json.get("data", {})
        is_pass = data.get("is_pass", -1)
        btn_state = data.get("button_state", -1)
        deadline = data.get("deadline_format", "")

        if is_pass == 1:
            col, tag, msg = Fore.GREEN, "[Approved..]", f"Status {token_label}: APPROVED (Berlaku s/d {deadline})"
        else:
            status_map = {
                (4, 1): (Fore.GREEN, "[Valid.]", f"Status {token_label}: ELIGIBLE (Siap War!)"),
                (4, 2): (Fore.RED, "[Blocked.]", f"Status {token_label}: BLOCKED hingga {deadline}"),
                (4, 3): (Fore.YELLOW, "[Warn!.]", f"Status {token_label}: Akun belum berumur 30 Hari!"),
            }
            col, tag, msg = status_map.get(
                (is_pass, btn_state),
                (Fore.WHITE, "[Account.]", f"{token_label} Valid (Unknown is_pass: {is_pass})")
            )
        log(tag, msg, col)
        return True

    except Exception as e:
        log("[Error.]", f"{token_label} Gagal terhubung: {e}", Fore.RED)
        return False

# ================= UPDATE CHECKER ================= #
def check_update():
    url_version = "https://raw.githubusercontent.com/ProjectRedis/mchrbl-cli/refs/heads/main/herorbl.py"
    url_changelog = "https://raw.githubusercontent.com/ProjectRedis/mchrbl-cli/refs/heads/main/changelog.txt"

    try:
        r = requests.get(url_version, timeout=5)
        r.raise_for_status()

        remote_version = None
        for line in r.text.splitlines():
            if line.startswith("CURRENT_VERSION"):
                remote_version = (
                    line.split("=")[1]
                    .strip()
                    .strip('"')
                    .strip("'")
                )
                break

        if not remote_version:
            log("[Info.]", "Tidak bisa membaca versi di GitHub.", Fore.WHITE)
            return

        if remote_version == CURRENT_VERSION:
            log("[Info.]", f"Script sudah terbaru ({CURRENT_VERSION})", Fore.WHITE)
            return

        print()
        log(
            "[Info.]",
            f"Update tersedia: {remote_version}",
            Fore.WHITE
        )
        log(
            "[Info.]",
            f"Versi saat ini : {CURRENT_VERSION}",
            Fore.WHITE
        )

        print()

        try:
            r2 = requests.get(url_changelog, timeout=5)
            r2.raise_for_status()

            #log("[Changelog.]", "", Fore.WHITE)

            for line in r2.text.strip().splitlines():
                print(" " * LABEL_WIDTH + line)

        except Exception:
            log("[Info.]", "Changelog tidak ditemukan.", Fore.WHITE)

        print()

        jawab = input(
            colored(f'{"[Input!]":<{LABEL_WIDTH}}', Fore.YELLOW)
            + " Update sekarang? (y/n): "
        ).strip().lower()

        if jawab == "y":
            try:
                import sys

                script_path = os.path.abspath(sys.argv[0])

                r3 = requests.get(url_version, timeout=10)
                r3.raise_for_status()

                with open(script_path, "w", encoding="utf-8") as f:
                    f.write(r3.text)

                log("[Success.]", f"Berhasil update ke {remote_version}", Fore.GREEN)
                log("[Info.]", "Silakan jalankan ulang script.", Fore.WHITE)

                raise SystemExit(0)

            except Exception as e:
                log("[Error.]", f"Gagal update otomatis: {e}", Fore.RED)

        else:
            log("[Info.]", "Melanjutkan menggunakan versi saat ini.", Fore.WHITE)

    except Exception as e:
        log("[Error.]", f"Gagal cek update: {e}", Fore.RED)
        
# ===================== SEND WAVE ===================== #
def send_wave(id, target_wave, cookie, base_time_ms, perf_base_ns, offset, label, output_dict, core_id=None):
    if core_id is not None:
        try:
            os.sched_setaffinity(0, {core_id})
            log("[Success.]", f"Hero-{id:02d} berhasil diikat ke core {core_id}", Fore.GREEN)
        except Exception as e:
            log("[Error.]", f"Hero-{id:02d} gagal diikat ke core {core_id}: {e}", Fore.RED)

    host = "sgp-api.buy.mi.com"
    path = "/bbs/api/global/apply/bl-auth"
    payload_str = '{"is_retry": false}'
    raw_http_request = (
        f"POST {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"User-Agent: {USER_AGENT}\r\n"
        f"Cookie: {cookie}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(payload_str)}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
        f"{payload_str}"
    ).encode('utf-8')

    try:
        sock = socket.create_connection((host, 443), timeout=5)
        context = ssl.create_default_context()
        with context.wrap_socket(sock, server_hostname=host) as ssock:
            gc.disable()
            # Sleep & yield
            while True:
                now = get_accurate_now_ms(base_time_ms, perf_base_ns, offset)
                remain = target_wave - now
                if remain > 20:
                    time.sleep((remain - 20) / 1000.0)
                elif remain > 2:
                    time.sleep(0)
                else:
                    break
            # Spin-lock
            while (base_time_ms + ((time.perf_counter_ns() - perf_base_ns)//1_000_000) + offset) < target_wave:
                pass
            # Trigger
            try:
                ssock.sendall(raw_http_request)
                drift = get_accurate_now_ms(base_time_ms, perf_base_ns, offset) - target_wave
            except Exception as e_send:
                gc.enable()
                output_dict[id-1] = (Fore.RED, f"{'[Failed.]':<{TAG_WIDTH}}", f"{'Send Error':<{MSG_WIDTH}} [Hero-{id:02d}] | {e_send}")
                return
            gc.enable()
            # Parse response
            try:
                resp_bytes = ssock.recv(4096)
                resp_str = resp_bytes.decode('utf-8', errors='ignore')
                if "\r\n\r\n" in resp_str:
                    body = resp_str.split("\r\n\r\n",1)[1]
                    resp_json = json.loads(body)
                    result = resp_json.get("data", {}).get("apply_result",-1)
                else:
                    result = -1
                col, tag, msg = get_result_meaning(result)
                tag_padded = f"{tag:<{TAG_WIDTH}}"
                msg_padded = f"{msg:<{MSG_WIDTH}}"
                hero_tag = f"[Hero-{id:02d}]"
                output_dict[id-1] = (col, tag_padded, f"{msg_padded} {hero_tag:<12} | Drift: {drift:+.1f}ms")
            except Exception as e_parse:
                tag_padded = f"{'[Failed.]':<{TAG_WIDTH}}"
                msg_padded = f"{'Parse Error':<{MSG_WIDTH}}"
                hero_tag = f"[Hero-{id:02d}]"
                output_dict[id-1] = (Fore.RED, tag_padded, f"{msg_padded} {hero_tag:<12} | Drift: {drift:+.1f}ms | {e_parse}")
    except Exception as e_outer:
        try: sock.close()
        except: pass
        output_dict[id-1] = (Fore.RED, f"{'[Failed.]':<{TAG_WIDTH}}", f"{'SSL/Connect Error':<{MSG_WIDTH}} [Hero-{id:02d}] | {e_outer}")

# ================= MAIN ================= #
def main():
    print(colored("="*60,Fore.CYAN))
    print(colored("                  MI-COMMUNITY HERO REQ-BL",Fore.WHITE))
    print(colored(f"                    {CURRENT_VERSION}",Fore.YELLOW))
    print(colored("="*60,Fore.CYAN))
    print()

    check_update()
    print()
    big_cores = get_big_cores()
    print()

    while True:
        cookie_a = getpass.getpass(colored(f'{"[Input!]":<14}', Fore.YELLOW) + " Paste Cookie A: ").strip()
        if not cookie_a:
            print(colored(f'{"[Error]":<14}', Fore.RED) + " Cookie A tidak boleh kosong!\n")
            continue
        log("[Success.]", "Cookie A diterima: " + colored("**********", Fore.WHITE), Fore.GREEN)

        cookie_b = getpass.getpass(colored(f'{"[Input!]":<14}', Fore.YELLOW) + " Paste Cookie B (Enter jika kosong): ").strip()
        if cookie_b:
            log("[Success.]", "Cookie B diterima: " + colored("**********", Fore.WHITE), Fore.GREEN)

        print()
        log("[Check!]", "Memeriksa status Token-A...", Fore.MAGENTA)
        valid_a = test_cookie(cookie_a, "Token-A")
        valid_b = True
        if cookie_b:
            log("[Check!]", "Memeriksa status Token-B...", Fore.MAGENTA)
            valid_b = test_cookie(cookie_b, "Token-B")
        if valid_a and valid_b: break
        print()
        log("[Info.]", "Silakan masukkan ulang seluruh credential.\n", Fore.YELLOW)

    print()
    log("[Check!]", "Singkronasi waktu NTP...", Fore.MAGENTA)
    ntp_offset = get_ntp_offset()
    log("[Info.]", f"NTP Offset: {ntp_offset} ms", Fore.WHITE)
    base_perf = time.perf_counter_ns()
    base_time = int(time.time() * 1000)

    debug = input(colored(f'{"[Input!]":<14}', Fore.YELLOW) + " Mode Debug (y/n): ").lower() == 'y'
    target_ms = get_accurate_now_ms(base_time, base_perf, ntp_offset) + 20000 if debug else get_next_beijing_midnight_ms()

    count_input = input(colored(f'{"[Input!]":<14}', Fore.YELLOW) + " Recruit Hero (Default 12): ")
    trigger_count = int(count_input) if count_input.isdigit() else 12

    # ===== Countdown start =====
    target_ping_ms = target_ms - 15000
    prefix_wait_start = colored(f"{'[Wait!]':<{LABEL_WIDTH}}", Fore.CYAN)
    while True:
        now = get_accurate_now_ms(base_time, base_perf, ntp_offset)
        remain_ms = target_ping_ms - now
        if remain_ms <= 0: break
        remain_sec = remain_ms // 1000
        h, rem = divmod(abs(remain_sec), 3600)
        m, s = divmod(rem, 60)
        h %= 24
        countdown_str = f"{h:02d}:{m:02d}:{s:02d}" if remain_sec > 59 else f"{s:02d}s"
        dots = "." * (int(time.time() * 2) % 4)
        print(f"{prefix_wait_start} Menunggu start: {countdown_str:<8} {dots:<3}", end='\r', flush=True)
        time.sleep(0.05)
    print()

    # ===== Ping sampling & Weighted Median =====
    ping_samples = []
    weights = []
    log("[Info.]", f"Mulai PING! {PING_SAMPLES} kali...", Fore.WHITE)
    for i in range(PING_SAMPLES):
        latency_sample = measure_latency()
        ping_samples.append(latency_sample)
        weights.append(i+1)  # bobot lebih tinggi untuk sample terbaru
        log("[Ping!]", f"Sample latency: {latency_sample}ms", Fore.MAGENTA)
        time.sleep(1)

    latency_effective = int(weighted_median(ping_samples, weights))
    base_send = target_ms - latency_effective
    bracket_half = int(latency_effective * BRACKET_FACTOR) + 50
    log("[Active.]", f"Dynamic Bracket ±{bracket_half}ms (Weighted Median Ping: {latency_effective}ms)", Fore.GREEN)

    # ===== Distribusi offset & thread Hero =====
    safety_margin = 30
    offsets = [int(-bracket_half + safety_margin + (2 * (bracket_half - safety_margin) * i) / (trigger_count - 1)) if trigger_count > 1 else 0 for i in range(trigger_count)]
    
    manager = mp.Manager()
    output_dict = manager.dict()
    processes = []

    for idx, offset in enumerate(offsets):
        wave_id = idx + 1
        label_tok = "Tok-B" if cookie_b and wave_id % 2 == 0 else "Tok-A"
        cookie_use = cookie_b if label_tok == "Tok-B" else cookie_a
        target_wave = base_send + offset
        dt_beijing = datetime.fromtimestamp(target_wave / 1000.0, BEIJING_TZ)
        milliseconds = int(target_wave % 1000)
        ts = f"{dt_beijing.strftime('%H:%M:%S')}.{milliseconds:03d}"
        log("[Info.]", f"Hero-{wave_id:02d} [{label_tok}] Standby at {ts} CST [Bracket: {offset:+}ms]")
        core_id = big_cores[idx % len(big_cores)] if big_cores else None
        p = mp.Process(target=send_wave, args=(wave_id, target_wave, cookie_use, base_time, base_perf, ntp_offset, label_tok, output_dict, core_id))
        processes.append(p)
        time.sleep(0.3)

    # ===== Countdown menunggu aba-aba =====
    prefix_wait = colored(f"{'[Wait!]':<{LABEL_WIDTH}}", Fore.CYAN)
    while get_accurate_now_ms(base_time, base_perf, ntp_offset) < base_send - 1000:
        remain_ms = base_send - get_accurate_now_ms(base_time, base_perf, ntp_offset)
        remain_sec = remain_ms // 1000
        h, rem = divmod(abs(remain_sec), 3600)
        m, s = divmod(rem, 60)
        h %= 24
        countdown_str = f"{h:02d}:{m:02d}:{s:02d}" if remain_sec > 59 else f"{s:02d}s"
        dots = "." * (int(time.time() * 2) % 4)
        print(f"{prefix_wait} Menunggu aba-aba {countdown_str:<8} {dots:<3}", end='\r', flush=True)
        time.sleep(0.05)
    print()

    log("[Active.]", "Hardware Spin-Lock mode active...", Fore.GREEN)
    for p in processes: p.start()
    for p in processes: p.join()
    time.sleep(0.3)

    print()
    log("[Info.]", "Laporan hasil war.", Fore.WHITE)
    time.sleep(1)

    for i in range(trigger_count):
        item = output_dict.get(i)
        if isinstance(item, tuple):
            col, tag_padded, sisa_teks = item
            log(tag_padded.strip(), sisa_teks, col)
        else:
            log("[Failed.]", f"Hero-{i+1:02d} mengalami gangguan koneksi.", Fore.RED)

    print()
    log("[Completed.]", "Pertempuran selesai", Fore.GREEN)

if __name__ == "__main__":
    mp.freeze_support() 
    main()
        
