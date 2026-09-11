# Deploying the PoGO server to a free Oracle Cloud VM

This puts the server on a real box with a public IP and open ports 53/udp +
443/tcp — the two things a Pokémon GO client needs to be tricked into hitting
your server. Cost: $0 on Oracle's Always Free tier.

## Part A — create the VM (you do this in Oracle's console)

1. **Sign up:** https://www.oracle.com/cloud/free/ → "Start for free".
   You must give a real name, email, phone, and a credit/debit card for
   identity verification. The Always Free resources are **not** charged; the
   card is only a fraud check. Choose your **Home Region** carefully — it can't
   be changed later; pick one near your players.
2. **Create the instance:** Console → hamburger menu → **Compute → Instances →
   Create instance**.
   - **Image:** Canonical **Ubuntu** (22.04 or 24.04).
   - **Shape:** click *Change shape* → **Ampere / VM.Standard.A1.Flex**
     (Arm, Always Free — 4 OCPU / 24 GB is free). If Ampere shows "out of
     capacity", either try again later, switch to a nearby region, or use the
     Always-Free **VM.Standard.E2.1.Micro** (AMD) instead — it's smaller but
     fine for this.
   - **SSH keys:** choose *Generate a key pair* and **download the private
     key** (you'll need it to log in). Save it somewhere like
     `C:\Users\mobra\.ssh\oracle_key`.
   - Click **Create**. When it's running, copy the **Public IP address**.
3. **Open the ports in Oracle's firewall (Security List / NSG):**
   Console → Networking → **Virtual Cloud Networks** → your VCN → **Security
   Lists** → *Default Security List* → **Add Ingress Rules**, twice:
   - Source `0.0.0.0/0`, IP Protocol **TCP**, Destination port **443**
   - Source `0.0.0.0/0`, IP Protocol **UDP**, Destination port **53**
   (This is the cloud-side firewall. The VM also has a local firewall, which
   `setup-vm.sh` opens for you.)

## Part B — deploy the server (from your PC, Git Bash)

From `work/server/`:

```bash
bash deploy/upload.sh ubuntu@YOUR_PUBLIC_IP  C:/Users/mobra/.ssh/oracle_key
```

Then log in and run the one-time setup:

```bash
ssh -i C:/Users/mobra/.ssh/oracle_key ubuntu@YOUR_PUBLIC_IP
sudo bash /opt/pogo/deploy/setup-vm.sh
```

That installs Python + `s2sphere`, opens the VM's local firewall, installs a
systemd service, and starts the server pointed at the VM's public IP. It prints
the IP to aim phones at.

## Part C — point a phone at it

Same as your local setup, but with the **public IP** instead of your LAN IP:

1. Wi-Fi settings → set **DNS** to `YOUR_PUBLIC_IP`.
2. Install your CA cert (`certs/ca.crt`) on the phone and trust it — see
   `DEVICE_SETUP.md`. The certs already shipped up with the server; the CA is
   host-based, so the same one keeps working on the public IP.
3. Launch the game.

## Running it

```bash
journalctl -u pogo-server -f          # live logs
sudo systemctl restart pogo-server    # restart
sudo systemctl stop pogo-server       # stop
```

To push code changes later: re-run `upload.sh`, then
`sudo systemctl restart pogo-server`.

## Notes / gotchas

- **An open UDP/53 resolver on a public IP can be abused** (DNS amplification).
  `dns_redirect.py` only answers with your redirect IP, so it's low-risk, but
  if you want to be tidy, restrict the 53 ingress rule to your players' IPs
  instead of `0.0.0.0/0`.
- **Port 53 bind fails?** Ubuntu's `systemd-resolved` can hold it. The last
  section of `setup-vm.sh` has two commented lines that free it — uncomment and
  re-run.
- **The World Manager** (`admin.py`, port 8080) stays bound to localhost and is
  NOT exposed. To reach it, SSH-tunnel:
  `ssh -i key -L 8080:127.0.0.1:8080 ubuntu@YOUR_PUBLIC_IP` then open
  `http://127.0.0.1:8080` locally.
- **`.exe` doesn't run on Linux** — this deploys the Python source, which is
  the same program. No PyInstaller needed.
