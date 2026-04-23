# Future Scope — SysInfo Dashboard

A collection of ideas, thoughts, and potential directions for evolving this project beyond its current form.

---

## 1. Real-Time Monitoring & Alerts

**Current state:** Dashboard refreshes on demand via a manual Refresh button.

**Future idea:** Move to WebSocket-based push updates so the UI reflects live CPU/memory spikes without user action. Pair this with a configurable threshold alert system — e.g., notify when CPU usage exceeds 90% for more than 10 seconds, or when free disk space drops below 5 GB. Alerts could be delivered as browser notifications, a local macOS notification via `osascript`, or even an email/Slack webhook.

---

## 2. Historical Data & Trend Charts

**Current state:** Every refresh shows only a point-in-time snapshot.

**Future idea:** Log metrics to a local SQLite database at regular intervals (e.g., every 30 seconds). Add a "History" tab with time-series line charts (using Chart.js or D3) showing CPU load, RAM usage, network throughput, and battery charge over the last hour/day/week. This turns the tool from a snapshot viewer into a lightweight observability system — useful for spotting memory leaks, overnight processes, or thermal throttling patterns.

---

## 3. Multi-Machine Support

**Current state:** The server only reports on the machine it's running on.

**Future idea:** Allow multiple instances of the server (on different machines) to register with a central "hub" instance. The hub aggregates all endpoints and presents a unified multi-machine dashboard — useful for a home lab, small office, or personal fleet of devices. Each machine's card would show a live health summary with click-through for full details.

---

## 4. Cross-Platform Feature Parity

**Current state:** macOS has full feature coverage (Wi-Fi detail, speed test, battery health, etc.). Linux and Windows are more limited.

**Future idea:**
- **Linux:** Add Wi-Fi info via `iwconfig`/`iw`, battery via `/sys/class/power_supply`, and speed test via `speedtest-cli`.
- **Windows:** Add Wi-Fi detail via `netsh wlan show interfaces`, speed test via `networkQuality` equivalent, and richer GPU info via WMI.
- Goal: feature parity across all three platforms so the tool is equally useful regardless of OS.

---

## 5. Process Manager

**Current state:** The Overview tab shows total process and thread count.

**Future idea:** Add a "Processes" tab that lists running processes (name, PID, CPU%, RAM usage) sortable by any column — similar to Activity Monitor or Task Manager, but in the browser. Include the ability to send a `SIGTERM` to a selected process (with a confirmation prompt), making it useful for quick triage without opening a terminal.

---

## 6. Progressive Web App (PWA)

**Current state:** Plain HTML served over HTTP — must be accessed via a browser tab.

**Future idea:** Add a `manifest.json` and a Service Worker so the dashboard can be installed as a PWA on macOS/Windows/Android. The installed app would appear in the dock/taskbar, launch directly to the dashboard, and could cache the last known system state for offline viewing.

---

## 7. Authentication & Remote Access

**Current state:** Server binds only to `localhost` with no auth — safe but limited to local use.

**Future idea:** Add an optional `--remote` flag that binds to all interfaces and enables token-based authentication (a simple Bearer token or TOTP). Combined with a self-signed TLS cert (auto-generated via `ssl` stdlib), this would allow secure remote monitoring from a phone or another machine on the same network — without exposing raw system data to anyone on the LAN.

---

## 8. Plugin / Custom Metrics System

**Current state:** All metrics are hardcoded into `system-info-server.py`.

**Future idea:** Introduce a `plugins/` directory where each Python file can expose a `collect()` function returning a dict of custom metrics. The server auto-discovers and loads these at startup, and the UI renders them in a generic "Custom Metrics" card. This would let users add things like Docker container stats, Homebrew outdated packages, Time Machine backup age, or any shell command output — without modifying core files.

---

## 9. Data Export & Reporting

**Future idea:** Add an "Export" button that downloads the current system snapshot as:
- A formatted PDF report (via browser print API)
- A JSON file for scripting/archiving
- A CSV of historical metrics if history logging is enabled

Useful for sharing system specs with support teams, auditing machine health over time, or building an inventory of devices.

---

## 10. Docker & Packaging

**Current state:** Requires Python 3 installed manually; launched via terminal command.

**Future idea:**
- **Docker image:** A minimal `python:3.12-slim` image so the server can be run with a single `docker run` command — useful for Linux servers or NAS devices.
- **Standalone binary:** Package with `PyInstaller` or `Nuitka` into a self-contained executable for macOS/Windows so non-technical users can double-click to launch, no Python install required.
- **Homebrew formula / winget package:** For one-line install on macOS/Windows.

---

## Closing Thoughts

The core strength of this project is its **zero-dependency philosophy** — a single Python file and a single HTML file, nothing to install. Any future additions should be careful not to break that simplicity for the default use case. Optional features (history logging, remote access, plugins) should be opt-in via flags or a config file, keeping the baseline experience as frictionless as possible.

The project also has potential as a **learning resource** — the codebase deliberately avoids frameworks and abstractions, making it a good example of raw HTTP servers, OS-level data collection, and vanilla JS DOM manipulation. Keeping it readable and well-documented is as valuable as adding features.
