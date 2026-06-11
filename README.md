# 🎯 MCHR-BL CLI (Mi-Community Hero Request-BL)

<details>
  <summary>🌐 <b>Select Language / Pilih Bahasa</b></summary>
  
  * [Bahasa Indonesia](README.md)
  * [English (US)](README.en.md)
</details>

---


![Python Version](https://img.shields.io/badge/Python-3.8%2B-blue?style=flat-square&logo=python)
![Platform](https://img.shields.io/badge/Platform-Termux%20%7C%20Linux%20%7C%20Windows-lightgrey?style=flat-square)
![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg?style=flat-square)
![Status](https://img.shields.io/badge/Status-Production%20Ready-success?style=flat-square)

**MCHR-BL CLI** adalah *bot script* tingkat lanjut (Level HFT - *High-Frequency Trading*) yang dirancang khusus untuk merebut tiket *Unlock Bootloader* (UBL) Xiaomi Global dengan presisi nanodetik. 

Dibangun dengan arsitektur memori yang brutal, skrip ini mem- *bypass* latensi library standar dengan langsung send packet **Raw HTTP Socket** langsung ke server Xiaomi tepat di milidetik *reset* harian.

---

## ⚡ Fitur Utama

| Fitur | Deskripsi |
| :--- | :--- |
| **Raw Socket Execution** | Mengirim *payload* HTTP murni tanpa *overhead* library untuk latensi serendah mungkin. |
| **Multiprocessing Design** | Terbebas dari Python GIL. Tiap "Hero" berjalan di proses memori yang terisolasi. |
| **Core Affinity** | Memaksa OS untuk mengikat eksekusi ke *Performance Core* (Anti-Throttle). |
| **High-Precision Timer** | Sinkronisasi waktu NTP dipadukan dengan resolusi *Hardware Clock* nanodetik. |
| **Dynamic Latency Bracket** | Menyebar tembakan secara cerdas berdasarkan fluktuasi PING *real-time* ke server. |
| **Hardware Counter** | Menghitung presisi waktu berdasarkan kalkulasi offset waktu global dan OS lalu di-lock dengan metode perf-counter. |

---
## 📸 Preview

![Hasil Approve](assets/preview-00.png)

---

## 🛠️ Persiapan (Prerequisites)

Terminal apapun itu

Jika kamu menggunakan **Termux** di Android wajib termux versi [F-Droid](https://f-droid.org/id/packages/com.termux/) atau versi [GitHub Release](https://github.com/termux/termux-app/releases) karena versi playstore sudah kadaluarsa.
Jalankan perintah ini terlebih dahulu untuk persiapan:
```bash
termux-setup-storage
```
lalu izinkan dan lanjutkan perintah berikutnya
```bash
pkg update && pkg upgrade -y
pkg install python git curl -y
```
lalu copy ini di terminal mu
```bash
bash <(curl -s https://raw.githubusercontent.com/ProjectRedis/mchrbl-cli/refs/heads/main/install.sh)
```
reload termux mu dan ketik
```bash
ubl-go
```

---

## 🔑 Cara ambil "Cookie" di Android

1. Install aplikasi network sniffer bebas.
    **(Proxyman, HTTP Toolkit**, HTTP Sniffer, PCAPdroid)**
2. Jalankan aplikasi sniffer
     biasanya akan meminta izin VPN.
3. Buka aplikasi **Xiaomi Community app**
     masuk ke halaman **Unlock Bootloader** di tab **Me** di pojok kanan bawah.
4. Setelah itu balik ke aplikasi sniffer
    matikan VPN atau service nya
    lalu cari:
   `https://sgp-api.buy.mi.com/bbs/api/global/apply/bl-auth`
5. Cari di bagian **Headers**
     apapun yg ada kata `Cookie:`. 
6. Salin/Copy text setelah kata `Cookie:` dengan awalan `new_bbs_serviceToken`.
7. Tempel/Paste di Terminal nya.
8. Selesai
