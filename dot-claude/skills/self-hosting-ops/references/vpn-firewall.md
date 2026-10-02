# VPN tunnels and host firewalls

Read from `self-hosting-ops` (principles: ask before opening ports or changing a remote firewall). Tailscale (WireGuard with key distribution and ACLs done for you) is the default for personal machines: `ops-tailscale`. Debugging: `net-diagnostics`.

## WireGuard by hand (when Tailscale or headscale does not fit)
```ini
# /etc/wireguard/wg0.conf  (chmod 600)
[Interface]
Address = 10.66.0.1/24
ListenPort = 51820
PrivateKey = <server private key>

[Peer]
PublicKey = <client public key>
AllowedIPs = 10.66.0.2/32
# client side adds: Endpoint = <server>:51820 and PersistentKeepalive = 25 (behind NAT)
```
- Keys: `umask 077; wg genkey | tee wg.key | wg pubkey > wg.pub`; private keys never leave their host.
- `AllowedIPs` is both the routing table and the access list ("cryptokey routing"): a peer may only send from, and receives traffic for, those ranges. `0.0.0.0/0, ::/0` on a client routes everything through the tunnel.
- `sudo wg-quick up wg0` / `down wg0`; at boot `sudo systemctl enable --now wg-quick@wg0`; status `sudo wg show` (latest handshake under ~2 minutes = alive).
- Routing for other hosts behind the server needs IP forwarding (`net.ipv4.ip_forward = 1`) and a NAT or route on the far side.

## Linux firewalls
- nftables is the kernel firewall; ufw (Ubuntu) and firewalld (Fedora and others) are front ends that write its rules. Use one front end per host.
- Baseline: deny incoming, allow outgoing, allow loopback and established traffic, then open services one by one and preferably only on the tailnet interface (`sudo ufw allow in on tailscale0`).
- ufw: `sudo ufw status verbose`, `sudo ufw allow from 100.64.0.0/10 to any port 22 proto tcp`, `sudo ufw delete <rule>`. firewalld: `sudo firewall-cmd --get-active-zones`, `--zone=<z> --add-service=https --permanent`, then `--reload`.
- Docker publishes ports by writing its own rules ahead of ufw/firewalld: bind published ports to `127.0.0.1` or the tailnet address.
- Inspect what is really loaded: `sudo nft list ruleset`.

## macOS
- Application Firewall: `/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate` (and `--setglobalstate on`, with the user's consent).
- pf for packet rules: anchors under `/etc/pf.anchors/`, load with `sudo pfctl -f /etc/pf.conf`, check `sudo pfctl -sr`; macOS updates can reset `/etc/pf.conf`, so keep custom rules in an anchor file.

## Changing a remote firewall without locking yourself out
- Keep a second session open; allow the management path (SSH over the tailnet) before tightening anything else.
- Schedule an automatic undo before applying (e.g. `sudo systemd-run --on-active=5min ufw disable`, or a timed restore of the saved ruleset) and cancel it only after a fresh connection succeeds.
- Save the ruleset before the change (`sudo nft list ruleset > /root/nft-before.conf`).

## Verify
- `sudo wg show` has a recent handshake on every peer; traffic for `AllowedIPs` flows, nothing else does.
- From outside the host (another machine, not the tailnet) only the intended ports answer (`nc -vz`); from the tailnet the management path still works; the saved pre-change ruleset is kept until the change is confirmed.
