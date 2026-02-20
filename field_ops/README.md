# Field Ops

This folder contains **field operations** artifacts for deploying EventPulse edge devices (Raspberry Pi sensors over LTE/5G) in a production-ish way:

- opinionated install scripts
- a hardened systemd unit to keep the edge-agent container running
- upgrade / rollback helpers
- an example `edge.env` file (device configuration)

These scripts are designed for:

- **Raspberry Pi OS 64-bit** (Debian-based)
- running the edge-agent as a **Docker container**
- a deployment model where devices call a **public Cloud Run** API and upload data to **GCS via signed URLs**

Start here:

- `docs/FIELD_OPS.md` — end-to-end runbook
- `field_ops/rpi/` — Pi install + systemd unit
