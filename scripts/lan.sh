#!/usr/bin/env bash
# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
# Print the one-time Windows commands that let phones on the home network reach FALCON
# inside WSL (NAT networking). Run them in PowerShell opened with "Run as administrator".
# The WSL address can change after Windows restarts; run `make lan` again and re-paste
# the portproxy lines when the phone stops connecting.
set -euo pipefail
wsl_ip="$(hostname -I | awk '{print $1}')"
lan_ips="$(powershell.exe -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { \$_.InterfaceAlias -notmatch 'WSL|Loopback|vEthernet|Bluetooth' -and \$_.IPAddress -notlike '169.254.*' } | Select-Object -ExpandProperty IPAddress" 2>/dev/null | tr -d '\r' || true)"
# Listen only on the Wi-Fi/Ethernet address: a proxy on 0.0.0.0 would also capture
# http://localhost:8000 on this PC, which FALCON then refuses as "another device".
echo "Paste in PowerShell (Run as administrator):"
echo
for ip in $lan_ips; do
  echo "netsh interface portproxy set v4tov4 listenaddress=$ip listenport=8000 connectaddress=$wsl_ip connectport=8000"
  # Port 80 too, so http://falcon.lan (a Pi-hole local DNS record) works without :8000.
  echo "netsh interface portproxy set v4tov4 listenaddress=$ip listenport=80 connectaddress=$wsl_ip connectport=8000"
done
cat <<EOF
New-NetFirewallRule -DisplayName "FALCON 8000 (home network)" -Direction Inbound -Protocol TCP -LocalPort 8000 -Profile Private -Action Allow
New-NetFirewallRule -DisplayName "FALCON 80 (home network)" -Direction Inbound -Protocol TCP -LocalPort 80 -Profile Private -Action Allow

Then open on the phone:
  http://falcon.lan   (after a Pi-hole Local DNS record falcon.lan -> this PC's address)
EOF
for ip in $lan_ips; do echo "  http://$ip:8000"; done
echo
echo "To undo:"
for ip in $lan_ips; do
  echo "netsh interface portproxy delete v4tov4 listenaddress=$ip listenport=8000"
  echo "netsh interface portproxy delete v4tov4 listenaddress=$ip listenport=80"
done
echo 'Remove-NetFirewallRule -DisplayName "FALCON 8000 (home network)"'
echo 'Remove-NetFirewallRule -DisplayName "FALCON 80 (home network)"'
