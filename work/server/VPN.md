# Play anywhere — VPN setup (Tailscale)

The problem away from home: the phone can't reach the home PC (a LAN IP), and on
cellular you can't set a custom DNS. A VPN fixes both at once. **Tailscale** is by
far the easiest (it's WireGuard under the hood, needs no port-forwarding, and works
on cellular). It puts the phone and the PC on the same private network from anywhere,
and lets us push our DNS to the phone.

> GPS note: "anywhere" means anywhere the phone gets a real GPS fix — i.e. outdoors.
> The VPN solves *network reach + DNS*; it doesn't change that PoGO 0.29 needs a real
> GPS lock (it won't accept a mock). Outside, that's automatic.

## 1. Install Tailscale on the PC
- Download from https://tailscale.com/download/windows, install, and **sign in**
  (Google/GitHub/email — free "Personal" plan is plenty).
- Get the PC's Tailscale IP:  open a terminal →  `tailscale ip -4`
  (it looks like `100.x.y.z`). Call this **TS_IP**.

## 2. Install Tailscale on the phone
- Play Store → **Tailscale** → sign in with the **same account**.
- Toggle it **on** (it adds a VPN profile; PoGO runs fine alongside it).

Now the phone can reach the PC at **TS_IP** from any network, anywhere.

## 3. Point the phone's DNS at our server (via Tailscale)
- Go to the admin console: https://login.tailscale.com/admin/dns
- Under **Nameservers → Add nameserver → Custom**, enter **TS_IP**.
- Turn **Override local DNS** ON.

Now every DNS lookup on the phone goes to our server over the tunnel: the Niantic/PTC
hosts resolve to TS_IP, everything else is forwarded normally.

## 4. Run the server bound to the Tailscale IP
```
pogo-server.exe 100.x.y.z        # use your real TS_IP
```
This makes the DNS hand out TS_IP for the PoGO hosts, which the phone can reach through
the tunnel from anywhere.

## 5. Play
Phone: Tailscale **on**, go outside, launch the game. It logs into your server and
spawns Pokémon/PokéStops around your real location — on any network, anywhere.

## Firewall
Allow inbound DNS + HTTPS so the tunneled phone can reach them (admin cmd prompt):
```
netsh advfirewall firewall add rule name="pogo-dns"  dir=in action=allow protocol=UDP localport=53
netsh advfirewall firewall add rule name="pogo-https" dir=in action=allow protocol=TCP localport=443
```

## Why Tailscale over raw WireGuard / port-forwarding
- No router config / port-forwarding (works behind CGNAT, dorms, cellular).
- No exposing port 53 to the open internet (no open-resolver abuse risk).
- DNS push is built in. Raw WireGuard works too but you'd manage keys, a public
  endpoint, and firewall rules yourself.
