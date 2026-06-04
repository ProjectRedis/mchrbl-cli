#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import getpass
import statistics
import threading
import time
from datetime import datetime, timedelta, timezone

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

def colored(msg, color):
    return f"{color}{msg}{Style.RESET_ALL}" if hasattr(Fore, "MAGENTA") else msg

# ================= KONFIG ================= #
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

# ================= UTIL ================= #
def log(label, msg, color=Fore.WHITE):
    print(f"{colored(f'{label:<{LABEL_WIDTH}}', color)} {msg}")

def get_big_cores(num_big=4):
    """Deteksi big cores otomatis dan log [Info.]"""
    cores = []
    cpu_dir = "/sys/devices/system/cpu/"
    for i in range(os.cpu_count()):
        try:
            with open(f"{cpu_dir}cpu{i}/cpufreq/cpuinfo_max_freq") as f:
                maxf = int(f.read().strip())
            with open(f"{cpu_dir}cpu{i}/cpufreq/cpuinfo_min_freq") as f:
                minf = int(f.read().strip())
            cores.append((i, maxf, minf))
        except:
            continue
    cores.sort(key=lambda x: x[1], reverse=True)
    big_cores = [c[0] for c in cores[:num_big]]
    for c in big_cores:
        log("[Info.]", f"CPU{c} terdeteksi sebagai big core", Fore.WHITE)
    return big_cores

def get_ntp_offset():
    client = ntplib.NTPClient()
    for server in ["pool.ntp.org","id.pool.ntp.org","time.google.com"]:
        try:
            r = client.request(server, version=3, timeout=5)
            log("[Connected.]", f"Terhubung ke '{server}'", Fore.GREEN)
            return int(r.offset*1000)
        except: continue
    log("[Error]", "Semua server NTP gagal", Fore.RED)
    return 0

def get_accurate_now_ms(base, perf, offset):
    return int(base + (time.perf_counter()-perf)*1000) + offset

def get_next_beijing_midnight_ms():
    now_utc = datetime.now(timezone.utc)
    now_beijing = now_utc.astimezone(BEIJING_TZ)
    next_midnight = now_beijing + timedelta(days=1)
    next_midnight = next_beijing.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(next_midnight.timestamp()*1000)

def measure_latency():
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=Retry(total=2, backoff_factor=0.3,
                                                           status_forcelist=[502,503,504],
                                                           allowed_methods={"HEAD"})))
    times=[]
    for _ in range(3):
        try:
            start=time.time()
            session.head("https://sgp-api.buy.mi.com", timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
            times.append((time.time()-start)*1000)
        except: pass
    session.close()
    return int(sum(times)/len(times)) if times else 300

def test_cookie(cookie,label):
    headers={"Cookie":cookie,"User-Agent":USER_AGENT}
    try:
        code = requests.get(STATE_URL, headers=headers, timeout=TIMEOUT).json().get("code")
        if code==100004:
            log("[Failed.]", f"{label} Kadaluarsa", Fore.RED)
            return False
        log("[Success.]", f"{label} Valid", Fore.GREEN)
        return True
    except:
        log("[Error]", f"Gagal cek {label}", Fore.RED)
        return False

def get_result_meaning(code):
    if code==1: return Fore.GREEN, "[Approved.]", "Tiket didapat!"
    if code==2: return Fore.WHITE, "[Info.]", "Sudah punya tiket"
    if code==3: return Fore.RED, "[Failed.]", "Kuota habis"
    if code==6: return Fore.RED, "[Failed.]", "Server sibuk"
    return Fore.RED, "[Failed.]", f"Result code:{code}"

def send_wave(id, target_wave, cookie, base, perf, offset, label, output_list, core_id=None):
    if core_id is not None:
        try:
            os.sched_setaffinity(0, {core_id})
            log("[Success.]", f"Hero-{id:02d} berhasil diikat ke core {core_id}", Fore.GREEN)
        except Exception as e:
            log("[Error]", f"Hero-{id:02d} gagal diikat ke core {core_id}: {e}", Fore.RED)

    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=Retry(total=2, backoff_factor=0.3)))
    headers = {"Cookie": cookie, "User-Agent": USER_AGENT, "Content-Type": "application/json"}
    payload = {"is_retry": False}

    try: session.get(INFO_URL, headers=headers, timeout=TIMEOUT)
    except: pass

    while True:
        now = get_accurate_now_ms(base, perf, offset)
        remain = target_wave - now
        if remain > 15:
            time.sleep((remain-15)/1000.0)
        elif remain <= 0:
            drift = get_accurate_now_ms(base, perf, offset) - target_wave
            break
        else: pass

    try:
        result = session.post(UNLOCK_URL, headers=headers, json=payload, timeout=TIMEOUT)\
                        .json().get("data", {}).get("apply_result", -1)
        col, tag, msg = get_result_meaning(result)
        tag_padded = f"{tag:<{TAG_WIDTH}}"
        msg_padded = f"{msg:<{MSG_WIDTH}}"
        hero_tag = f"[Hero-{id:02d}]"
        output_list[id-1] = (col, tag_padded, f"{msg_padded} {hero_tag:<12} | Drift: {drift:+.1f}ms")
    except:
        tag_padded = f"{'[Failed.]':<{TAG_WIDTH}}"
        msg_padded = f"{'Error/Timeout':<{MSG_WIDTH}}"
        hero_tag = f"[Hero-{id:02d}]"
        output_list[id-1] = (Fore.RED, tag_padded, f"{msg_padded} {hero_tag:<12} | Drift: {drift:+.1f}ms")
    session.close()

# ================= MAIN ================= #
def main():
    print(colored("="*60, Fore.CYAN))
    print(colored("                  MI-COMMUNITY HERO REQ-BL", Fore.WHITE))
    print(colored("                    v1.9-Rev.2026.06.04", Fore.YELLOW))
    print(colored("="*60, Fore.CYAN))

    big_cores = get_big_cores()

    while True:
        cookie_a = getpass.getpass(colored(f'{"[Input!]":<14}', Fore.YELLOW)+" Paste Cookie A: ").strip()
        if not cookie_a:
            print(colored(f'{"[Error]":<14}', Fore.RED)+" Cookie A tidak boleh kosong!\n")
            continue
        log("[Success.]", "Cookie A diterima: "+colored("**********", Fore.WHITE), Fore.GREEN)

        cookie_b = getpass.getpass(colored(f'{"[Input!]":<14}', Fore.YELLOW)+" Paste Cookie B (Enter jika kosong): ").strip()
        if cookie_b:
            log("[Success.]", "Cookie B diterima: "+colored("**********", Fore.WHITE), Fore.GREEN)

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

    log("[Check!]", "Singkronasi waktu NTP...", Fore.MAGENTA)
    ntp_offset = get_ntp_offset()
    log("[Info.]", f"NTP Offset: {ntp_offset} ms", Fore.WHITE)
    base_perf = time.perf_counter()
    base_time = int(time.time()*1000)

    debug = input(colored(f'{"[Input!]":<14}', Fore.YELLOW)+" Mode Debug (y/n): ").lower()=='y'
    target_ms = get_accurate_now_ms(base_time, base_perf, ntp_offset)+20000 if debug else get_next_beijing_midnight_ms()

    count_input = input(colored(f'{"[Input!]":<14}', Fore.YELLOW)+" Recruit Hero (Default 12): ")
    trigger_count = int(count_input) if count_input.isdigit() else 12

    # Countdown start
    target_ping_ms = target_ms - 15000
    prefix_wait_start = colored(f"{'[Wait!]':<{LABEL_WIDTH}}", Fore.YELLOW)
    while True:
        now = get_accurate_now_ms(base_time, base_perf, ntp_offset)
        remain_ms = target_ping_ms - now
        if remain_ms <=0: break
        remain_sec = remain_ms//1000
        h, rem = divmod(remain_sec, 3600)
        m, s = divmod(rem, 60)
        countdown_str = f"{h:02d}:{m:02d}:{s:02d}" if remain_sec>59 else f"{s:02d}s"
        dots = "."*(int(time.time()*2)%4)
        print(f"{prefix_wait_start} Menunggu start: {countdown_str:<8} {dots:<3}", end='\r', flush=True)
        time.sleep(0.05)
    print()

    ping_samples=[]
    log("[Ping!]", f"Mulai sampling ping ({PING_SAMPLES} kali)...", Fore.MAGENTA)
    for _ in range(PING_SAMPLES):
        latency_sample = measure_latency()
        ping_samples.append(latency_sample)
        log("[Ping!]", f"Sample latency: {latency_sample}ms", Fore.MAGENTA)
        time.sleep(1)

    latency_avg=int(statistics.mean(ping_samples))
    base_send = target_ms - latency_avg
    bracket_half = int(latency_avg*BRACKET_FACTOR)+50
    log("[Active.]", f"Dynamic Bracket ±{bracket_half}ms (Avg Ping: {latency_avg}ms)", Fore.GREEN)

    offsets = [int(-bracket_half + (2*bracket_half*i)/(trigger_count-1)) if trigger_count>1 else 0 for i in range(trigger_count)]
    threads=[]
    output_list=[""]*trigger_count

    for idx, offset in enumerate(offsets):
        wave_id = idx+1
        label_tok = "Tok-B" if cookie_b and wave_id%2==0 else "Tok-A"
        cookie_use = cookie_b if label_tok=="Tok-B" else cookie_a
        target_wave = base_send+offset
        ts = datetime.fromtimestamp(target_wave/1000, BEIJING_TZ).strftime("%H:%M:%S.%f")[:-3]
        log("[Info.]", f"Hero-{wave_id:02d} [{label_tok}] Standby at {ts} CST [Bracket: {offset:+}ms]")
        core_id = big_cores[idx % len(big_cores)]
        t = threading.Thread(target=send_wave, args=(wave_id, target_wave, cookie_use, base_time, base_perf, ntp_offset, label_tok, output_list, core_id))
        threads.append(t)

    prefix_wait = colored(f"{'[Wait!]':<{LABEL_WIDTH}}", Fore.YELLOW)
    while get_accurate_now_ms(base_time, base_perf, ntp_offset)<base_send-1000:
        remain_ms = base_send - get_accurate_now_ms(base_time, base_perf, ntp_offset)
        remain_sec = remain_ms//1000
        h, rem = divmod(remain_sec, 3600)
        m, s = divmod(rem,60)
        countdown_str = f"{h:02d}:{m:02d}:{s:02d}" if remain_sec>59 else f"{s:02d}s"
        dots = "."*(int(time.time()*2)%4)
        print(f"{prefix_wait} Menunggu aba-aba {countdown_str:<8} {dots:<3}", end='\r', flush=True)
        time.sleep(0.05)
    print()

    log("[Active.]", "Hardware Spin-Lock mode active...", Fore.GREEN)
    for t in threads: t.start()
    for t in threads: t.join()

    print("\n"+colored("=== Hasil Rekrut Hero ===", Fore.CYAN))
    for item in output_list:
        if isinstance(item, tuple):
            col, tag_padded, sisa_teks = item
            log(tag_padded.strip(), sisa_teks, col)
        else:
            log("[Failed.]", "Hero mengalami gangguan koneksi.", Fore.RED)

    print()
    log("[Completed.]", "Pertempuran selesai", Fore.GREEN)


if __name__=="__main__":
    main()
