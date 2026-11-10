#!/usr/bin/env bash
# Print the one-time Windows commands that let phones on the home network reach FALCON
# inside WSL (NAT networking). Run them in PowerShell opened with "Run as administrator".
# The WSL address can change after Windows restarts; run `make lan` again and re-paste
# the first line when the phone stops connecting.
set -euo pipefail
wsl_ip="$(hostname -I | awk '{print $1}')"
lan_ips="$(powershell.exe -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { \$_.InterfaceAlias -notmatch 'WSL|Loopback|vEthernet|Bluetooth' -and \$_.IPAddress -notlike '169.254.*' } | Select-Object -ExpandProperty IPAddress" 2>/dev/null | tr -d '\r' || true)"
# Listen only on the Wi-Fi/Ethernet address: a proxy on 0.0.0.0 would also capture
# http://localhost:8000 on this PC, which FALCON then refuses as "another device".
echo "Paste in PowerShell (Run as administrator):"
echo
for ip in $lan_ips; do
  echo "netsh interface portproxy set v4tov4 listenaddress=$ip listenport=8000 connectaddress=$wsl_ip connectport=8000"
done
cat <<EOF
New-NetFirewallRule -DisplayName "FALCON 8000 (home network)" -Direction Inbound -Protocol TCP -LocalPort 8000 -Profile Private -Action Allow

Then open on the phone:
EOF
for ip in $lan_ips; do echo "  http://$ip:8000"; done
echo
echo "To undo:"
for ip in $lan_ips; do echo "netsh interface portproxy delete v4tov4 listenaddress=$ip listenport=8000"; done
echo 'Remove-NetFirewallRule -DisplayName "FALCON 8000 (home network)"'
