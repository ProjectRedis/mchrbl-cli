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

**MCHR-BL CLI** is an advanced bot script (Level HFT – *High-Frequency Trading*) specifically designed to grab Xiaomi Global *Unlock Bootloader* (UBL) tickets with nanosecond precision.

Built with a brutal memory architecture, this script bypasses standard library latency by sending **Raw HTTP Socket** packets directly to Xiaomi’s server at the exact millisecond of the daily *reset*.

---
## ⚡ Key Features
| Feature | Description |
|---|---|
| **Raw Socket Execution** | Sends pure HTTP payloads without library overhead for the lowest possible latency. |
| **Multiprocessing Design** | Completely free from the Python GIL. Each "Hero" runs in an isolated memory process. |
| **Core Affinity** | Forces the OS to bind execution to Performance Cores (Anti-Throttling). |
| **High-Precision Timer** | NTP time synchronization combined with nanosecond Hardware Clock resolution. |
| **Dynamic Latency Bracket** | Intelligently spreads requests based on real-time PING fluctuations to the server. |
| **Hardware Counter** | Calculates precise timing based on global and OS time offsets, then locks it using the perf-counter method. |
## 📸 Preview
![Hasil Approve](assets/preview-00.png)

---
## 🛠️ Prerequisites
Works on any terminal environment.
If you are using **Termux** on Android, you must use the [F-Droid](https://f-droid.org/id/packages/com.termux/) or [GitHub Release](https://github.com/termux/termux-app/releases) version, as the Play Store version is severely outdated.
Run this command first for initial preparation:

```bash
termux-setup-storage
```
Then grant permission and proceed with the following commands:

```bash
pkg update && pkg upgrade -y
pkg install python git curl -y
```

Next, copy and paste this into your terminal:

```bash
bash <(curl -s https://raw.githubusercontent.com/ProjectRedis/mchrbl-cli/refs/heads/main/install.sh)
```

Restart/reload your Termux and type:

```bash
ubl-go
```

---
## 🔑 How to Get "Cookie" on Android
 1. Install a network sniffer application (**Proxyman**, **HTTP Toolkit**, **HTTP Sniffer**, or **PCAPdroid**)—choose whichever you prefer.
 2. Run the sniffer app; it will typically prompt for VPN permissions.
 3. Open the **Xiaomi Community** app, navigate to the **Unlock Bootloader** page, located under the **Me** tab in the bottom right corner.
 4. After that, return to the sniffer app, turn off the VPN or service, and search for:
   [https://sgp-api.buy.mi.com/bbs/api/global/apply/bl-auth](https://sgp-api.buy.mi.com/bbs/api/global/apply/bl-auth)
 5. Under the **Headers** section, look for anything containing Cookie:.
 6. Copy the long string of text following Cookie: that starts with new_bbs_serviceToken.
 7. That's it! Just paste it into the tool.
