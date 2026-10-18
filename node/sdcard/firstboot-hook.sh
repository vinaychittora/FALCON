#!/bin/bash
# Runs once, as root, from Raspberry Pi Imager's first-boot script (no argument)
# or from cloud-init (--now). It only schedules falcon-node-firstboot.service;
# that service runs install.sh after the network is up, then switches itself off.
set -e
BUNDLE="$(cd "$(dirname "$0")/.." && pwd)"
sed "s#@BUNDLE@#$BUNDLE#g" "$BUNDLE/systemd/falcon-node-firstboot.service" \
  > /etc/systemd/system/falcon-node-firstboot.service
systemctl enable falcon-node-firstboot.service
if [[ "${1:-}" == "--now" ]]; then
  # cloud-init runs during a normal boot: start without waiting for it to finish.
  systemctl start --no-block falcon-node-firstboot.service
fi
