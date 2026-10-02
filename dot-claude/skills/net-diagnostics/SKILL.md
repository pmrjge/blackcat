---
name: net-diagnostics
description: Use to debug a network problem layer by layer — routes, DNS, ports, TLS, MTU, packet captures.
---
# Network diagnostics (macOS and Linux)

Part of `self-hosting-ops` (principles). Protocol background: `references/net-protocols.md` in `self-hosting-ops`; tunnels and firewalls: `self-hosting-ops` `references/vpn-firewall.md`; Tailscale specifics: `ops-tailscale`.

Work bottom-up and stop at the first layer that fails; record each command and its result.

## 1. Link and addresses
- Linux: `ip -br addr`, `ip route`, `ip route get <dest-ip>` (which interface and gateway a packet takes).
- macOS: `ifconfig`, `route -n get default`, `networksetup -listallhardwareports`, `scutil --nwi`.

## 2. Reachability and path
- `ping -c 4 <host>`; `mtr -rwc 100 <host>` (loss and latency per hop; loss only at one middle hop is usually ICMP rate limiting); `traceroute -n <host>`.
- MTU / blackholes (large transfers hang, small ones work): Linux `ping -M do -s 1472 <host>`, macOS `ping -D -s 1472 <host>`; lower the size until it passes (1472 + 28 header bytes = 1500).
- Tailnet: `tailscale status`, `tailscale ping <host>` (direct or via DERP relay), `tailscale netcheck`.

## 3. DNS
- `dig +short <name> A`, `dig +short <name> AAAA`; compare resolvers `dig @1.1.1.1 <name>` vs the system's; `dig +trace <name>` from the root.
- What the OS actually uses: Linux `resolvectl status` and `resolvectl query <name>` (systemd-resolved); macOS `scutil --dns`, `dscacheutil -q host -a name <name>`; flush on macOS `sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder`, on Linux `resolvectl flush-caches`.
- Check `/etc/hosts` before blaming DNS.

## 4. Ports and listeners
- Is it listening, and on which address: Linux `sudo ss -tlnup`; macOS `sudo lsof -iTCP -sTCP:LISTEN -nP`.
- Can I reach it: `nc -vz <host> <port>` (TCP), `nc -vzu <host> <port>` (UDP gives no reliable answer). A refusal means nothing listens; a timeout means a firewall drops it.

## 5. TLS and HTTP
- `openssl s_client -connect <host>:443 -servername <host> -showcerts </dev/null` (chain, SNI, protocol); expiry: pipe into `openssl x509 -noout -dates -subject -ext subjectAltName`.
- `curl -v https://<host>/` (DNS, connect, TLS, headers); timing: `curl -o /dev/null -s -w 'dns %{time_namelookup} connect %{time_connect} tls %{time_appconnect} ttfb %{time_starttransfer} total %{time_total}\n' <url>`; force an address with `--resolve <host>:443:<ip>`.

## 6. Packets and throughput
- `sudo tcpdump -i any -nn 'port 53'` (Linux; on macOS name the interface, e.g. `-i en0`); write `-w cap.pcap` and open it in Wireshark or `tshark -r cap.pcap`. Captures can contain secrets and personal data: keep them local and delete them after.
- Throughput between two hosts: `iperf3 -s` on one, `iperf3 -c <host>` (and `-R` for the reverse direction) on the other.

## Verify
- The failing layer is named with the command that shows it, and the same command passes after the fix.
- Temporary changes (flushed caches, test listeners, captures) are undone or deleted.
