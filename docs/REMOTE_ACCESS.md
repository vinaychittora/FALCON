# Private admin access and SSH

FALCON uses **Tailscale Serve**, which makes the interface available inside an
approved private Tailscale network. A copied address is not a public invitation:
the admin must be signed in to Tailscale and permitted by both its access policy
and FALCON's exact login allowlist. Media stays stored on the device; remote
admins can view it through the interface.

## One-time device setup

1. Install Tailscale on the Linux device and the admin's computer using the
   [official Linux instructions](https://tailscale.com/docs/install/linux).
2. Sign in on the device with `sudo tailscale up`. Complete account enrollment in
   its browser flow. Keep authorization keys and login URLs out of source control.
3. Allow the Linux account running FALCON to manage its Tailscale configuration:
   `sudo tailscale set --operator="$USER"`. Use a dedicated device account; operator
   permission covers more than this application's one Serve route.
4. Enable HTTPS for Serve when prompted in Tailscale's setup flow. For initial
   consent, run `tailscale serve --https=443 http://127.0.0.1:8000`, complete the
   displayed approval, then press Ctrl+C to close that foreground route. FALCON
   remains protected until its own allowlist/access setting is enabled.
5. Restrict the tailnet's network access rules to the admin identities/devices
   that need this device on TCP 443. FALCON's allowlist is an additional check,
   not a replacement for Tailscale policy.

No account token is entered into FALCON. The installer does not enroll the current
computer, alter firewall rules, or enable remote access automatically.

## Open and close from the interface

On the device, open **System → Device access**. Save the exact Tailscale login
emails for approved admins, then choose **Open admin access**. Copy the resulting
HTTPS address and share it privately. The admin opens it on an approved Tailscale
device. Access management is available locally; remote admins cannot change the
allowlist or open/close the route through the interface.

**Check connection** makes a bounded HTTPS request to Tailscale's public website.
A successful check shows internet reachability at that time; a failed check may
mean a blocked endpoint, DNS/TLS failure, or no internet. It is not a guarantee of
worldwide connectivity. Ordinary status reads inspect the local Tailscale daemon
without periodically transmitting media or making this external probe.

The Serve route is persistent after it is explicitly opened. It can recover with
Tailscale after a network interruption or reboot. **Close admin access** first
blocks FALCON requests, then removes only the route FALCON recognizes as its own.
An existing unrelated Serve/Funnel configuration is never overwritten or reset.
If CLI cleanup fails, the interface stays blocked; inspect Tailscale locally.

FALCON serves port 8000 on loopback and uses `--no-proxy-headers`. Remote requests
must arrive through that local proxy with the configured private Host and a
Tailscale identity header matching the allowlist. Cross-site browser requests
are rejected. Uploads are local-only with no default byte ceiling. The same
boundary applies to live WebSocket events and media reads.

## SSH for diagnosis

SSH is an operating-system facility, separate from the web interface. FALCON
does not run a browser terminal or accept shell commands through its API.

On the device, enable Tailscale SSH with `sudo tailscale set --ssh`. Configure
both a network rule for TCP 22 and a **Tailscale SSH rule** allowing the chosen
admin identity to the device's non-root Linux user. Prefer a `check` rule that
requires periodic reauthentication. Follow the
[official SSH policy guide](https://tailscale.com/docs/features/tailscale-ssh).

From the approved admin computer:

```bash
ssh device-user@device-name
```

Use the actual Linux username and MagicDNS name. Do not expose port 22 publicly
or enable password-based public SSH. Root escalation, if needed, remains an
explicit operating-system permission. Device sharing and tagged devices can
have additional SSH policy restrictions; verify access from the intended admin
account before deploying the device.

Useful diagnostics after connecting:

```bash
systemctl --user status falcon.service
journalctl --user -u falcon.service -n 100
tailscale status
df -h
```

Logs, profile metadata and source names may be private. Inspect them before sharing.
Closing the web route does not disable SSH; disable it separately with
`sudo tailscale set --ssh=false` or revoke its access policy.

## Deployment acceptance

No live Tailscale account was enrolled during the source review. Automated checks
exercise allowlists, cross-site rejection, WebSockets, remote upload rejection,
route ownership and fail-closed behavior with synthetic CLI responses. Verify
the actual private link, forbidden-user rejection, SSH policy, reboot recovery,
offline camera observation and reconnect on the intended device before field use.
Review key expiry and account recovery for an unattended installation.

References: [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve),
[Serve command and reboot behavior](https://tailscale.com/docs/reference/tailscale-cli/serve).
