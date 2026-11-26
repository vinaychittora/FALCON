#!/usr/bin/env bash
# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
# FALCON sensor node installer.
#
#   sudo bash node/install.sh            install or update, then start the node
#   sudo bash node/install.sh --uninstall
#
# Works on Raspberry Pi OS (Bookworm or newer, 32- or 64-bit) and on Debian or
# Ubuntu computers with a USB camera or microphone. Safe to run again: the
# existing node.conf and pairing key are kept. After installation the node
# starts by itself on every boot and begins streaming.
set -euo pipefail

MEDIAMTX_VERSION="v1.21.2"
declare -A MEDIAMTX_SHA256=(
  [arm64]="180a235374a548d9133cdd5e20f5dbd8b01317be1c86e0d7e66df585dc42ed6f"
  [armv7]="bff8951f51dcb0426c306fc3fad793232f03947916370b166d10e6c73dcf9ce2"
  [amd64]="121be6e00397e473a95d83c75f4fcd3819a6af3b0e1a50889cba43ab4fab6a27"
)
SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX=/opt/falcon-node
CONFIG_DIR=/etc/falcon-node
STATE_DIR=/var/lib/falcon-node
USER_NAME=falcon-node
FROM_BOOT=0
START=1
REBOOT_NEEDED=0

for argument in "$@"; do
  case "$argument" in
    --from-boot) FROM_BOOT=1 ;;
    --no-start) START=0 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "Unknown option: $argument" >&2; exit 2 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash $0 $*" >&2
  exit 1
fi

if [[ $FROM_BOOT -eq 1 ]]; then
  # First boot from the SD card: keep a log next to this script so it can be read on any computer.
  exec > >(tee -a "$SOURCE/install.log") 2>&1
fi

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
is_pi() { grep -qi "raspberry pi" /proc/device-tree/model 2>/dev/null; }

if [[ ${UNINSTALL:-0} -eq 1 ]]; then
  say "Removing the FALCON sensor node"
  systemctl disable --now falcon-node.service falcon-node-firstboot.service 2>/dev/null || true
  rm -f /etc/systemd/system/falcon-node.service /etc/systemd/system/falcon-node-firstboot.service
  rm -f /etc/polkit-1/rules.d/50-falcon-node.rules
  systemctl daemon-reload
  rm -rf "$PREFIX"
  echo "Removed the software. Settings ($CONFIG_DIR) and queued readings ($STATE_DIR) were kept;"
  echo "delete them by hand if you no longer need them."
  exit 0
fi

say "Installing system packages"
packages=(ffmpeg alsa-utils v4l-utils python3 ca-certificates curl)
if is_pi; then
  packages+=(i2c-tools)
  command -v rpicam-vid >/dev/null || command -v libcamera-vid >/dev/null || packages+=(rpicam-apps-lite)
fi
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  # The network may still be starting on the first boot.
  if apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends "${packages[@]}"; then
    break
  fi
  if [[ $attempt -eq 10 ]]; then
    echo "Packages could not be installed. Check the internet connection and run this script again." >&2
    exit 1
  fi
  echo "Package installation failed (attempt $attempt); retrying in 30 seconds..."
  sleep 30
done

if is_pi; then
  say "Enabling I2C for the BME280 weather sensor"
  if command -v raspi-config >/dev/null && [[ "$(raspi-config nonint get_i2c)" != "0" ]]; then
    raspi-config nonint do_i2c 0
    REBOOT_NEEDED=1
  fi
  boot_config=/boot/firmware/config.txt
  [[ -f $boot_config ]] || boot_config=/boot/config.txt
  # The DA7212 audio HAT is Raspberry Pi Codec Zero compatible. Its ID chip normally loads the
  # driver; when no capture device exists and no HAT ID was read, load the overlay explicitly.
  if ! arecord -l 2>/dev/null | grep -q "^card" && [[ ! -e /proc/device-tree/hat/product ]] \
      && ! grep -Eq "^dtoverlay=(rpi-codeczero|iqaudio-codec)" "$boot_config"; then
    say "Enabling the audio HAT driver"
    printf '\n# FALCON: DA7212 audio HAT (Codec Zero compatible)\ndtoverlay=rpi-codeczero\n' >> "$boot_config"
    REBOOT_NEEDED=1
  fi
fi

say "Installing MediaMTX $MEDIAMTX_VERSION (RTSP stream server)"
case "$(dpkg --print-architecture)" in
  arm64) mtx_arch=arm64 ;;
  armhf) mtx_arch=armv7 ;;
  amd64) mtx_arch=amd64 ;;
  *) echo "Unsupported processor architecture: $(dpkg --print-architecture)" >&2; exit 1 ;;
esac
archive="mediamtx_${MEDIAMTX_VERSION}_linux_${mtx_arch}.tar.gz"
mkdir -p "$PREFIX/mediamtx"
if [[ "$("$PREFIX/mediamtx/mediamtx" --version 2>/dev/null || true)" != "$MEDIAMTX_VERSION" ]]; then
  download="$(mktemp -d)"
  if [[ -f "$SOURCE/vendor/$archive" ]]; then
    cp "$SOURCE/vendor/$archive" "$download/"   # offline copy placed by prepare_sdcard.py --offline
  else
    curl -fsSL --retry 5 --retry-delay 10 -o "$download/$archive" \
      "https://github.com/bluenviron/mediamtx/releases/download/$MEDIAMTX_VERSION/$archive"
  fi
  echo "${MEDIAMTX_SHA256[$mtx_arch]}  $download/$archive" | sha256sum -c --quiet
  tar -xzf "$download/$archive" -C "$download"
  install -m 0755 "$download/mediamtx" "$PREFIX/mediamtx/mediamtx"
  install -m 0644 "$download/LICENSE" "$PREFIX/mediamtx/LICENSE"
  rm -rf "$download"
fi

say "Installing the FALCON node software"
id "$USER_NAME" >/dev/null 2>&1 || useradd --system --home-dir "$STATE_DIR" --no-create-home --shell /usr/sbin/nologin "$USER_NAME"
for group in video audio i2c gpio render; do
  getent group "$group" >/dev/null && usermod -aG "$group" "$USER_NAME"
done
rm -rf "$PREFIX/falcon_node"
cp -r "$SOURCE/falcon_node" "$PREFIX/falcon_node"
find "$PREFIX/falcon_node" -name "__pycache__" -prune -exec rm -rf {} +
mkdir -p "$PREFIX/audio"
cp "$SOURCE/audio/"* "$PREFIX/audio/"
[[ -f "$SOURCE/README.md" ]] && cp "$SOURCE/README.md" "$PREFIX/README.md"
chown -R root:root "$PREFIX"
chmod -R u=rwX,go=rX "$PREFIX"

mkdir -p "$CONFIG_DIR"
if [[ ! -f "$CONFIG_DIR/node.conf" ]]; then
  if [[ -f "$SOURCE/node.conf" ]]; then
    cp "$SOURCE/node.conf" "$CONFIG_DIR/node.conf"      # prepared on the SD card
  else
    cp "$SOURCE/node.conf.example" "$CONFIG_DIR/node.conf"
  fi
fi
conf="$CONFIG_DIR/node.conf"
if ! grep -Eq "^PAIRING_KEY=[A-Za-z2-7-]{16,}" "$conf"; then
  key="$(cd "$PREFIX" && python3 -c 'from falcon_node.auth import generate_key; print(generate_key())')"
  sed -i "/^PAIRING_KEY=/d" "$conf"
  echo "PAIRING_KEY=$key" >> "$conf"
fi
if ! grep -Eq "^NODE_ID=[A-Za-z0-9]" "$conf" || grep -q "^NODE_ID=falcon-node-01$" "$conf"; then
  sed -i "/^NODE_ID=/d" "$conf"
  echo "NODE_ID=$(hostname | tr -cd 'A-Za-z0-9_.:-' | cut -c1-100)" >> "$conf"
fi
chown root:"$USER_NAME" "$conf"
chmod 0640 "$conf"

install -m 0644 "$SOURCE/systemd/falcon-node.service" /etc/systemd/system/falcon-node.service
if [[ -d /etc/polkit-1/rules.d ]]; then
  install -m 0644 "$SOURCE/systemd/50-falcon-node.rules" /etc/polkit-1/rules.d/50-falcon-node.rules
fi
systemctl daemon-reload
systemctl enable falcon-node.service >/dev/null

# Keep the node minimal: extras that cost power and heat stay off until switched on
# from FALCON (Sensors → Node power) or the phone page. SSH, NetworkManager and the
# wired network are untouched. Set KEEP_EXTRAS=1 to skip this.
if is_pi && [[ "${KEEP_EXTRAS:-0}" != 1 ]]; then
  say "Switching off extras that only add heat (they can be started from FALCON)"
  if command -v nmcli >/dev/null && nmcli -t -f NAME connection show 2>/dev/null | grep -qx falcon-hotspot; then
    # The hotspot stays available but no longer starts by itself; the node starts it at
    # boot only when "start at boot" is chosen in FALCON.
    nmcli connection modify falcon-hotspot connection.autoconnect no || true
  fi
  for unit in bluetooth.service hciuart.service avahi-daemon.service avahi-daemon.socket \
              apt-daily.timer apt-daily-upgrade.timer man-db.timer; do
    if systemctl cat "$unit" >/dev/null 2>&1; then
      # Disabled, not masked: Bluetooth can still be started from FALCON.
      systemctl disable --now "$unit" >/dev/null 2>&1 || true
    fi
  done
fi
mkdir -p "$STATE_DIR"
(cd "$PREFIX" && python3 -c 'from falcon_node import VERSION; print(VERSION)') > "$STATE_DIR/.installed"

if [[ $FROM_BOOT -eq 1 ]]; then
  systemctl disable falcon-node-firstboot.service 2>/dev/null || true
fi

if [[ $START -eq 1 && $REBOOT_NEEDED -eq 0 ]]; then
  systemctl restart falcon-node.service
  sleep 3
fi

say "FALCON sensor node is installed"
(cd "$PREFIX" && python3 -m falcon_node pairing --config "$conf") || true
echo
(cd "$PREFIX" && python3 -m falcon_node check --config "$conf" --state-dir "$(mktemp -d)") 2>/dev/null || true
cat <<EOF

It starts by itself on every boot. Useful commands:
  systemctl status falcon-node        is it running?
  journalctl -u falcon-node -f        live log
  sudo nano $conf                     change settings, then: sudo systemctl restart falcon-node
  http://<this node>:8780             status page in a browser
EOF

if [[ $REBOOT_NEEDED -eq 1 ]]; then
  echo
  echo "I2C or the audio driver was just enabled; the node must restart once."
  if [[ $FROM_BOOT -eq 1 ]]; then
    echo "Restarting now..."
    systemctl reboot
  else
    echo "Run: sudo reboot"
  fi
fi
