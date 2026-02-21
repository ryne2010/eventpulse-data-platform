# Raspberry Pi Field Ops

This folder contains everything you need to run the **EventPulse edge agent** as a long-running
system service on a Raspberry Pi.

## Files

- `install.sh` — installs Docker (if missing), installs systemd unit + helper scripts
- `uninstall.sh` — removes systemd unit + scripts (keeps config/spool by default)
- `eventpulse-edge-agent.service` — systemd unit
- `eventpulse-edge-agent-run` — starts the Docker container (used by systemd)
- `eventpulse-edge-agent-update` — pulls a new image and restarts the service
- `edge.env.example` — example config file to copy/edit

## Quick install

```bash
# From the repo root on the Pi:
sudo bash field_ops/rpi/install.sh \
  --api-base-url "https://YOUR_CLOUD_RUN_URL" \
  --enroll-token "PASTE_EDGE_ENROLL_TOKEN"

# Tail logs
sudo journalctl -u eventpulse-edge-agent -f
```

## Config

- Config file: `/etc/eventpulse-edge/edge.env`
- Spool directory: `/var/lib/eventpulse-edge/spool`

Edit config and restart:

```bash
sudo nano /etc/eventpulse-edge/edge.env
sudo systemctl restart eventpulse-edge-agent
```

## Updates

If you publish a new container image:

```bash
sudo eventpulse-edge-agent-update
```

If you distribute images as a tarball (airgapped), re-load the image and restart:

```bash
gunzip -c /tmp/eventpulse-edge-agent_latest.tar.gz | docker load
sudo systemctl restart eventpulse-edge-agent
```

## Multi-arch image builds (M2 + x86)

From the repo root:

```bash
# Native for Raspberry Pi OS 64-bit (recommended on M2 Macs)
make edge-image-build EDGE_IMAGE_PLATFORM=linux/arm64

# Cross-build for x86 Linux edge hosts
make edge-image-build EDGE_IMAGE_PLATFORM=linux/amd64
```

For one tag that supports both platforms, use Docker Buildx directly:

```bash
docker buildx build \
  --platform linux/arm64,linux/amd64 \
  -t YOUR_REGISTRY/eventpulse-edge-agent:TAG \
  -f services/edge_agent/Dockerfile \
  --push .
```

## Optional: camera snapshots

If you attach a USB webcam or Pi camera and you enabled `ENABLE_EDGE_MEDIA=true` on the API,
use:

- `field_ops/rpi/camera/capture_and_upload.sh`

It captures a snapshot and uploads it via the edge media signed-URL flow.
