# Proxmox VE LXC deployment plan

**Deferred:** continue all development and tests on the existing Ubuntu test server. Create the LXC only after application functionality is validated.

Target: native Python service in an unprivileged Debian 13 LXC under Proxmox VE 9.x (user's host reports 9.2.32). No Docker, nesting, privileged container, or device passthrough required for this stage. Suggested starting allocation: 1–2 vCPU, 1 GiB RAM, 8–16 GiB root disk; standard bridged IPv4 networking with DNS and internet access. Adjust storage for original photos and retention later. Do not enable port forwarding or public inbound services. The container must be able to initiate HTTPS, HTTP snapshot downloads, UDP relay traffic and SMTP to the configured mail server. Allow stateful responses, DNS and package updates. The provider/backend may change destinations.

## Create the container in the Proxmox GUI

Choose an unused CT ID, download the current Debian 13 standard template, create an unprivileged CT, choose appropriate storage and a bridge on your LAN, and configure DHCP or a static IP as appropriate. Keep nesting off. Start and open its console. Commands below run inside the container as root unless noted.

```sh
apt update
apt install -y ca-certificates git python3 python3-venv python3-dev build-essential sqlite3 tzdata
adduser --disabled-password --gecos '' ucon
su - ucon
git clone https://github.com/nocusham/ucon-trailcam-smtp.git
cd ucon-trailcam-smtp
python3 --version
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest -v
```

Debian 13 supplies Python 3.13; the SDK requires Python 3.12+. Python 3.13 on the actual LXC and the pinned SDK installation still need a live test. If dependency installation fails, capture the actual build error rather than changing package versions blindly. Run the application as ucon, not root. Configure persistent private credentials using [CREDENTIALS.md](CREDENTIALS.md); interactive prompts are available for manual probes. The future service must use noninteractive credential loading. No background daemon is installed in this phase.

## SQLite discovery-only test

```sh
umask 077
python cloud_probe.py --day 2026-11-26 --queue-db data/events-test.sqlite3
python cloud_probe.py --day 2026-11-26 --queue-db data/events-test.sqlite3
sqlite3 -readonly data/events-test.sqlite3 'SELECT state, count(*) FROM events GROUP BY state;'
```

The first run should insert matching valid events; a second run with the same results should add zero and report them as known. If new PIR events arrive in between, the new count may increase. This is an explicitly historical **test** queue; do not promote this file to a production delivery queue. No original/thumbnail downloads, relay sessions, SMTP messages or background polling are initiated. Cloud API calls are the only network requests by the probe. Device UID and item ID form the composite identity; the six requested fields are stored separately as JSON. Signed URL and account credentials are not stored. A conflicting timestamp for the same identity rolls back the entire batch, and invalid records are counted separately. Cloud event-type filtering, freshness limits, pagination and initial production start policy remain to be validated; this stage stores valid own-device API records without asserting their types.

As of 2026-11-26, bounded authenticated cloud polling, timestamp matching, original batch download, persistent file and delivery receipts, per-camera SMTP profiles and persistent private credentials are implemented and tested individually on the existing Ubuntu server (108 tests passed). The remaining phases are continuous orchestration, persistent cursor and bounded retry/recovery, multi-day DEATTI DL04 validation (historically labelled H4), then native systemd deployment with a private state directory and protected credentials. No Revierwelt connection until the application is finished. Cloud preview remains development-only; production requires original images. The Proxmox host has not been modified by this project. A systemd unit and reboot test do not exist yet; this is a deferred deployment plan, not a production installation guide. The extra Ucon and UBox models are reserved for later compatibility work.

Keep data directories private and included in backups; use separate test and production database paths. Do not copy an active SQLite database without a consistent backup procedure.

## Repository packaging prerequisite

Before creating the production LXC, separate runtime modules, tests, diagnostic tools, deployment files and configuration templates; install a pinned validated release rather than the development checkout. See [REPOSITORY_LAYOUT.md](REPOSITORY_LAYOUT.md). No test data or private credentials are shipped. Perform the long-duration reference-server test before migrating.
