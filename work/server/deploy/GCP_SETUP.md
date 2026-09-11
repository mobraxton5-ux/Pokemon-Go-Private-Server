# Hosting the PoGO server on Google Cloud (e2-micro, Always Free)

Same end state as the Oracle walkthrough, on a provider that actually has
capacity. `deploy/setup-vm.sh` is generic Ubuntu, so steps 3 onward are
identical to `ORACLE_FULL_SETUP.md` — only the console clicking differs.

Placeholders: `PUBLIC_IP` = the VM's external IP, `~/.ssh/pogo_key` = your key.

---

## Step 1 — Account and project

1. https://console.cloud.google.com — sign in with your Google account.
2. Activate the free trial ($300 / 90 days). A card is required for identity
   verification; you are not auto-charged when the trial ends — the account
   pauses until you manually enable billing.
3. Top bar → project dropdown → **New Project** → name it `pogo` → Create.
   Make sure it's the selected project before continuing.

### Always Free vs the trial
Two separate things, same as Oracle. Always Free runs forever alongside and
after the trial. Its limits:

| Resource | Always Free limit |
|---|---|
| Compute | 1 × **e2-micro**, in `us-west1`, `us-central1`, or `us-east1` only |
| Disk | 30 GB standard persistent disk |
| Egress | **1 GB/month** out of North America |

The region restriction is strict — an e2-micro anywhere else is billed.

> **Egress is the one to watch.** RPC/protobuf traffic is tiny, but asset
> bundles are not. If you serve `assets/` from this box to several players you
> will blow through 1 GB. See "Egress" at the bottom.

---

## Step 2 — Create the VM

**Compute Engine → VM instances** → Enable the API if prompted (takes a minute)
→ **Create instance**.

| Field | Value |
|---|---|
| Name | `pogo` |
| Region | `us-central1` (or `us-west1` / `us-east1` — **must** be one of these) |
| Zone | any |
| Machine family | General purpose → **E2** |
| Machine type | **e2-micro** (2 shared vCPU, 1 GB) |
| Boot disk | **Ubuntu 22.04 LTS**, Standard persistent disk, **30 GB** |
| Firewall | tick **Allow HTTPS traffic** |

Boot disk is not Ubuntu by default — click **Change** and switch the OS to
Ubuntu, or `setup-vm.sh` will fail on its first `apt-get`.

Keep the disk at 30 GB standard. Larger, or SSD, leaves the free tier.

Create, wait for the green check, and copy the **External IP** — that's
`PUBLIC_IP`.

---

## Step 3 — SSH key

Easiest path: **Compute Engine → Settings → Metadata → SSH Keys → Edit → Add
item**, paste your public key:

```bash
cat ~/.ssh/pogo_key.pub
```

The username GCP uses is the comment at the end of the key. To make it
predictable, paste the key with `ubuntu` as the trailing comment, then log in
as `ubuntu`. Otherwise check the key list for the name it assigned.

(The in-browser **SSH** button also works and needs no key at all — but you
need working SSH from your PC for `upload.sh`, so set the key up.)

---

## Step 4 — Firewall rules

GCP's default network blocks everything inbound except SSH. The "Allow HTTPS
traffic" tick from step 2 covers 443; the DNS port needs a rule.

**VPC network → Firewall → Create firewall rule**

| Field | Value |
|---|---|
| Name | `pogo-dns` |
| Direction | Ingress |
| Targets | All instances in the network |
| Source IPv4 ranges | `0.0.0.0/0` |
| Protocols and ports | Specified → **UDP 53** |

Create. If you skipped the HTTPS tick, make a second rule the same way for
**TCP 443**.

> Skip the UDP/53 rule entirely if you go the metadata-patch route (client
> hostnames rewritten to point here directly). That design needs only TCP 443.

---

## Step 5 onward — identical to the Oracle guide

From `work/server/` on your PC:

```bash
bash deploy/upload.sh ubuntu@PUBLIC_IP ~/.ssh/pogo_key
```

```bash
ssh -i ~/.ssh/pogo_key ubuntu@PUBLIC_IP
```

```bash
sudo bash /opt/pogo/deploy/setup-vm.sh
```

Then verify from your PC before touching a phone:

```bash
nslookup pgorelease.nianticlabs.com PUBLIC_IP
```

```bash
curl -vk https://PUBLIC_IP/ --resolve pgorelease.nianticlabs.com:443:PUBLIC_IP
```

Phone setup, service management, and the World Manager tunnel are all
unchanged — see `ORACLE_FULL_SETUP.md` steps 5–7.

---

## GCP-specific gotchas

**Ephemeral external IP.** By default the external IP is ephemeral and can
change if the VM is stopped and started. Since players point DNS at a literal
IP, a change breaks everyone. Reserve it: **VPC network → IP addresses** →
find the one attached to `pogo` → **Reserve**. Note that a reserved static IP
that is *not* attached to a running VM bills hourly, so don't reserve and then
delete the VM.

**External IPv4 is no longer unconditionally free.** Google charges for
in-use external IPv4 addresses on some configurations (~$3/month). The $300
credit absorbs it during the trial. Check **Billing → Cost table** after a few
days to see whether a line item appears, and decide then.

**Set a budget alert.** Billing → Budgets & alerts → Create budget → $1,
alert at 100%. Do this on day one — it's the cheapest insurance against a
surprise.

**1 GB RAM.** e2-micro is small. If the server gets OOM-killed under load, add
swap:

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
```

Make it persist across reboots:

```bash
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

**Egress.** 1 GB/month free out of North America. To stay under it, don't
serve `assets/` from this VM to a group — host the bundles on a free object
store or a GitHub release and keep the VM for RPC only. Watch usage in
**Billing → Reports**, filtered to Network egress.
