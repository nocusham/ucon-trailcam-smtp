# Debian 13 LXC reference environment

The LXC is the owner's intended target, not a requirement for this
application. The same installation contract applies to Linux VMs,
bare-metal systems and ordinary unprivileged users. See
[deployment architecture](../deploy/README.md).

Target: unprivileged Debian 13 LXC under Proxmox VE, standard bridged
network, DNS and outbound HTTPS, HTTP snapshot downloads, UDP relay
traffic and SMTP. No Docker, nesting, privileged container, public
inbound service or device passthrough required. Suggested starting
allocation: 1–2 vCPU, 1 GiB RAM, 8–16 GiB storage; adjust for original media.

The administrator may provision OS dependencies (python3, python3-venv,
ca-certificates, tzdata, and build tools/python3-dev if native KCP requires
them) and optionally a service account. Application installation is
performed as the chosen non-root account into its selected directory,
default ~/ucon-trailcam-smtp. No fixed /opt, /etc or /var application
directories. A system unit is optional; user systemd or manual operation
are also supported by the planned architecture.

Debian 13 Python 3.13 and native dependency installation are not yet
validated. Do not silently change pinned dependencies to bypass a build
failure. Use a new queue and media directory, not the active reference
state. Proxmox backup can supplement the private application backup.

**Deferred:** do not create or activate the production LXC until the
simplified installer and reference acceptance have been tested and the
owner approves target testing. No current production installation
commands; see readiness gates in PRODUCTION_READINESS.md. Historical
LXC sketches remain in Git history.
