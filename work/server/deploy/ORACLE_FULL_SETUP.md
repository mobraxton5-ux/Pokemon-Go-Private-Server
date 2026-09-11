# Hosting the PoGO server publicly on Oracle Always Free — full walkthrough

End-to-end: from a fresh Oracle account to a phone catching Pokémon against a
public server. Cost $0. Assumes you already signed up and can reach the console.

Placeholders used throughout:
- `PUBLIC_IP` — the VM's public IPv4 (you get it in step 2)
- `~/.ssh/pogo_key` — your SSH private key

---

## Step 0 — SSH key (on your PC, Git Bash)

Skip if you already made one.

```bash
ssh-keygen -t ed25519 -f ~/.ssh/pogo_key
```

Press Enter twice to skip the passphrase. Then print the **public** half — you
paste this into Oracle in the next step:

```bash
cat ~/.ssh/pogo_key.pub
```

---

## Step 1 — Create the VM

Console → hamburger menu → **Compute → Instances → Create instance**.

| Field | Value |
|---|---|
| Name | `pogo` (anything) |
| Image | **Canonical Ubuntu 24.04** (Edit → Change image) |
| Shape | **VM.Standard.A1.Flex**, 4 OCPU / 24 GB — or **VM.Standard.E2.1.Micro** if A1 has no capacity |
| Boot volume | leave default (~47 GB) — do not raise it |
| SSH keys | **Paste public keys** → paste `pogo_key.pub` |

Every choice must show the green **Always Free-eligible** label. That label is
the only thing standing between you and a bill.

If Create fails with **"Out of host capacity"**, that's the A1 shortage — go
back, switch the shape to E2.1.Micro, create again. It's a smaller box but this
server is one Python process; it does not care.

Wait for **RUNNING**, then copy the **Public IP address** from the instance
details page. That's `PUBLIC_IP`.

### Optional but recommended: budget alarm
**Billing → Budgets → Create Budget**, amount `$1`, alert at 100%. It doesn't
block anything, but you get an email the moment something non-free starts
accruing.

---

## Step 2 — Open ports 53/udp and 443/tcp in Oracle's firewall

This is the cloud-side filter. Two rules.

Console → **Networking → Virtual Cloud Networks** → your VCN → **Security
Lists** → *Default Security List* → **Add Ingress Rules**:

| Stateless | Source CIDR | Protocol | Destination Port |
|---|---|---|---|
| no | `0.0.0.0/0` | TCP | 443 |
| no | `0.0.0.0/0` | UDP | 53 |

Leave "Stateless" unchecked on both. Port 22 is already open by default.

> An open UDP/53 resolver on a public IP can be abused for DNS amplification.
> `dns_redirect.py` only ever answers with your redirect IP, so the reflection
> gain is tiny — but if you know your players' IPs, put those in the Source
> field instead of `0.0.0.0/0`.

---

## Step 3 — Upload the server

From `work/server/` on your PC, in Git Bash:

```bash
bash deploy/upload.sh ubuntu@PUBLIC_IP ~/.ssh/pogo_key
```

Oracle's Ubuntu image logs in as `ubuntu`, not `root`. Say `yes` to the host
key prompt. This rsyncs the whole server dir to `/opt/pogo`, including `certs/`
— the certs are SAN-based on hostnames with no IP baked in, so the CA and leaf
you already have keep working on the public IP untouched.

---

## Step 4 — One-time setup on the VM

```bash
ssh -i ~/.ssh/pogo_key ubuntu@PUBLIC_IP
```

then on the box:

```bash
sudo bash /opt/pogo/deploy/setup-vm.sh
```

That installs Python + `s2sphere`, opens the VM's local iptables (Oracle's
image blocks everything but SSH by default — this is *separate* from step 2 and
both are required), installs the systemd unit with `RUN_IP=PUBLIC_IP`, and
starts it.

If it can't auto-detect the IP:

```bash
sudo PUBLIC_IP_OVERRIDE=203.0.113.7 bash /opt/pogo/deploy/setup-vm.sh
```

### If port 53 won't bind
Check the logs:

```bash
journalctl -u pogo-server -n 40
```

An "address already in use" on 53 means `systemd-resolved` grabbed it.
Uncomment the two lines near the bottom of `deploy/setup-vm.sh`
(`systemctl disable --now systemd-resolved` and the `resolv.conf` line) and
re-run the script.

---

## Step 5 — Verify from your PC, before touching a phone

DNS redirect working?

```bash
nslookup pgorelease.nianticlabs.com PUBLIC_IP
```

Must answer with `PUBLIC_IP` itself. If it times out: step 2's UDP rule, or the
local iptables from step 4.

Game server answering TLS?

```bash
curl -vk https://PUBLIC_IP/ --resolve pgorelease.nianticlabs.com:443:PUBLIC_IP
```

You want a completed TLS handshake showing `O=PoGO Private Server`. Connection
refused means the service isn't up (`journalctl`); timeout means a firewall.

Don't move on until both pass. Debugging this from the phone is far worse.

---

## Step 6 — Set up each phone

Per player, one time.

1. **Install the patched APK** — `work/pogo-0.29.0.objection.apk`. Uninstall any
   existing Pokémon GO first (different signature). See `DEVICE_SETUP.md`.
2. **Trust the CA** — send them `certs/ca.crt`. Settings → Security →
   *Encryption & credentials* → **Install a certificate → CA certificate** →
   pick `ca.crt` → accept the "network may be monitored" warning. The game
   targets API 23, so user CAs are trusted.
3. **Point DNS at the server** — Wi-Fi settings → the network → Modify →
   Advanced → **IP settings: Static** → keep the assigned IP/gateway, set
   **DNS 1 = `PUBLIC_IP`**. Save.
4. **Check it** — phone browser to `https://pgorelease.nianticlabs.com`. You
   want a response from *our* server (empty reply or a cert notice), not
   Niantic.
5. Launch the game → **Pokémon Trainer Club** → any username, any password.

### The cellular limitation
Step 3 only works on Wi-Fi. Android gives you no per-SIM DNS control, so a
public VPS cannot serve players on mobile data. If you want cellular play, run
Tailscale alongside this and push DNS from the tailnet admin console — see
`VPN.md`. Both can serve the same box at once.

---

## Running it

```bash
journalctl -u pogo-server -f      # live logs
```

```bash
sudo systemctl restart pogo-server
```

```bash
sudo systemctl stop pogo-server
```

Pushing code changes: re-run `upload.sh` from your PC, then restart the
service. No rebuild — this deploys the Python source, not the `.exe`.

### World Manager (admin.py, port 8080)
Deliberately bound to localhost and **not** exposed. Reach it through an SSH
tunnel:

```bash
ssh -i ~/.ssh/pogo_key -L 8080:127.0.0.1:8080 ubuntu@PUBLIC_IP
```

then open `http://127.0.0.1:8080` in your own browser.

---

## Billing sanity check

The **$300 / 30-day Free Trial** and **Always Free** are different things
running in parallel. When the trial expires Oracle does not bill you — the
account drops to Always Free, over-limit resources get reclaimed, Always Free
resources keep running. Being charged requires manually clicking *Upgrade to
Pay As You Go*.

Always Free ceilings, for reference:

| Resource | Limit |
|---|---|
| Ampere A1 | 4 OCPU + 24 GB RAM **total across all instances** |
| AMD E2.1.Micro | 2 instances |
| Block storage | 200 GB total, max 2 volumes |
| Outbound transfer | 10 TB/month |

One VM with a default boot volume is nowhere near any of these.

---

## Before you invite people

Untested: how `admin.py` and the player-state files behave with several
accounts hitting them at once. Pokémon uids must be globally unique because the
client keys on them — worth confirming that holds across concurrent players in
a controlled two-phone test before a group session, not during one.
