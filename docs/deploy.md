# Deploying CogniTrack to an Oracle Cloud VM

This guide takes the app from your laptop to an always-on Oracle Cloud VM that only your own
devices can reach. Follow it top to bottom; each step says **why**, so you learn what you are
doing as well as how. Allow an evening.

```
phone / laptop ──Tailscale (WireGuard, encrypted)──▶ VM: tailscale serve ──▶ 127.0.0.1:8080
                                                       web (Caddy) ─┬─ the React app
                                                                    └─ /api ─▶ api (FastAPI) ─▶ db (Postgres)
```

**The idea in one paragraph.** The VM runs the same three pieces as your laptop (database, API,
web), each in a Docker container, so the VM needs nothing installed except Docker and Tailscale.
The VM accepts **no connections from the internet at all**: Oracle's cloud firewall and the VM's
own firewall both block everything. You reach it only through Tailscale, a private network
between your own devices. Every night the database is dumped and copied off the VM.

Commands marked **laptop** run in Git Bash on your laptop; **VM** commands run over SSH on the VM.
Replace anything in `<angle brackets>`.

---

## 1. Oracle account

1. Sign up at <https://www.oracle.com/cloud/free/>. A card is needed for identity checks.
2. **Home region:** pick Mumbai (`ap-mumbai-1`) or Hyderabad (`ap-hyderabad-1`).
   *Why:* Always Free resources only exist in your home region, and it **can never be changed**.
   A nearby region keeps the app fast on your phone.
3. **Recommended: upgrade to Pay As You Go** (Billing & Cost Management → Upgrade and Manage
   Payment). Always Free resources stay free after the upgrade.
   *Why:* Oracle may reclaim *idle* Always Free VMs (over 7 days, CPU, network and memory all under
   20%), and a one-person app looks idle. Many people report that Pay As You Go accounts are not
   reclaimed, though Oracle's documentation does not say so outright. If you stay on the free
   tier, the nightly backups (step 10) are what let you rebuild if it happens.
4. **Budget alert:** Billing → Budgets → Create Budget: ₹100 a month, alert at 1% of actual
   spend, to your email.
   *Why:* if anything ever starts costing money, you hear about it the same day.

## 2. Create the VM

**laptop:** make an SSH key for this VM (press Enter for no passphrase, or set one):

```sh
ssh-keygen -t ed25519 -f ~/.ssh/cognitrack -C cognitrack
cat ~/.ssh/cognitrack.pub        # you'll paste this into Oracle
```

*Why a key:* SSH keys can't be guessed like passwords; the VM will accept nothing else.

Oracle console → Compute → Instances → **Create instance**:

| Setting | Value | Why |
| --- | --- | --- |
| Name | `cognitrack` | |
| Image | Canonical Ubuntu 24.04 (the aarch64 build is picked automatically for Ampere) | Long-term support until 2029, security updates built in |
| Shape | Ampere → `VM.Standard.A1.Flex`, **1 OCPU, 6 GB** | Plenty for this app; half the free allowance stays spare. The free limit is 2 OCPU / 12 GB in total |
| Networking | Create a new VCN and public subnet; **assign a public IPv4 address** | The VM needs to reach the internet (updates, Tailscale). Nothing will be allowed *in* |
| SSH keys | Paste `~/.ssh/cognitrack.pub` | |
| Boot volume | Default (about 47 GB) | Free up to 200 GB in total |

If it fails with **"Out of host capacity"**, Arm machines are fully booked in that availability
domain: try another availability domain, or retry later (early morning IST often works).

Note the **public IP address** on the instance page.

## 3. Lock the cloud firewall to your IP for now

Instance page → the subnet → the **Default Security List** → Ingress Rules. There is a rule
allowing TCP port 22 from `0.0.0.0/0` (the whole internet). Edit its source to your own address:

**laptop:** `curl -s https://ifconfig.me` → use `<that IP>/32` as the source CIDR.

*Why:* until Tailscale is working you need SSH from the internet, but only from you. In step 7
this rule is deleted entirely. (Leave the ICMP rules; they let the network report errors.)

## 4. First login and basic hardening

**laptop:**

```sh
ssh -i ~/.ssh/cognitrack ubuntu@<public IP>
```

**VM:**

```sh
sudo apt update && sudo apt full-upgrade -y
sudo timedatectl set-timezone Asia/Kolkata     # cron and reboots below are in IST

# SSH: keys only, no root logins.
sudo tee /etc/ssh/sshd_config.d/10-cognitrack.conf > /dev/null <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
sudo sshd -t && sudo systemctl reload ssh
```

*Why:* Ubuntu already disables passwords on Oracle images; writing it down makes sure an update
can't quietly turn them back on. `sshd -t` checks the file before reloading, so a typo can't lock
you out.

**Automatic security updates.** Ubuntu installs security patches daily on its own
(`unattended-upgrades`). Add automatic reboots (some patches need one) and Docker's updates:

```sh
sudo tee /etc/apt/apt.conf.d/52cognitrack > /dev/null <<'EOF'
// Reboot when a patch needs it, at 03:30 IST: after the 02:30 backup, far from market hours.
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "03:30";
// Docker's own repository (step 5) is not covered by default.
Unattended-Upgrade::Origins-Pattern { "origin=Docker"; };
EOF
sudo unattended-upgrade --dry-run 2>&1 | tail -3     # should finish without errors
```

**The VM's own firewall.** Oracle's Ubuntu images already have one: `iptables` rules (saved in
`/etc/iptables/rules.v4`) that accept SSH and reject every other incoming connection. See them:

```sh
sudo iptables -S INPUT
```

*Why two firewalls:* the cloud firewall (security list) and the VM firewall each block the
internet on their own, so one mistake in either still leaves the VM closed. Don't install `ufw`
on top: it fights with these rules. Tailscale and Docker add their own rules automatically.

## 5. Install Docker

**VM** (Docker's official instructions for Ubuntu):

```sh
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker ubuntu
apt-cache policy docker-ce | grep -m1 'o=Docker' && echo "auto-updates will cover Docker"
exit        # log out and back in so the docker group applies
```

*Why Docker:* the app, its database and the web server each run in a container built from files
in this repo, so the VM's setup is a few lines and a rebuild is one command. Being in the
`docker` group is equivalent to root on this VM, which is fine: you are its only user.

## 6. Install Tailscale

1. Create a Tailscale account at <https://tailscale.com> (free for personal use) and install the
   app on your **phone** and **laptop**, signed in to the same account.
2. **VM:**

   ```sh
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up --hostname=cognitrack
   ```

   Open the link it prints and approve the VM.
3. In the Tailscale admin console → Machines → `cognitrack` → **Disable key expiry**.
   *Why:* otherwise the VM drops off your network every 180 days until you log in again.
4. Note the VM's names: **VM:** `tailscale status --self` shows the short name `cognitrack`;
   the full name is `cognitrack.<your tailnet>.ts.net` (admin console → DNS shows the tailnet
   name). `tailscale ip -4` shows its `100.x.y.z` address.

*Why Tailscale:* it builds an encrypted private network between your own devices, so the VM can
refuse the whole internet and still be reachable from your phone anywhere. Its connections are
made outward from the VM, which is why no inbound firewall rule is needed.

## 7. Close the VM to the internet

1. **laptop**, *in a new terminal, keeping the current session open* (your way back in if
   something goes wrong): `ssh -i ~/.ssh/cognitrack ubuntu@cognitrack`. Continue only when this
   works: it is SSH over Tailscale.
2. **Oracle console:** Default Security List → **delete the port 22 ingress rule**. There are
   now no rules letting anything in from the internet.
3. **VM:** remove SSH from the VM firewall as well, for now and after reboots:

   ```sh
   sudo iptables -D INPUT -p tcp -m state --state NEW -m tcp --dport 22 -j ACCEPT
   sudo sed -i '/--dport 22 -j ACCEPT/d' /etc/iptables/rules.v4
   ```

   SSH over Tailscale keeps working: Tailscale's rules accept its own traffic first.
4. **laptop:** `ssh -o ConnectTimeout=5 -i ~/.ssh/cognitrack ubuntu@<public IP>` must now
   **time out**.

Locked out anyway? Oracle console → the instance → **Console connection** gives you a terminal
without the network.

From now on, always `ssh -i ~/.ssh/cognitrack ubuntu@cognitrack`. To shorten it, add to
`~/.ssh/config` on the laptop:

```
Host cognitrack
  User ubuntu
  IdentityFile ~/.ssh/cognitrack
```

## 8. Get the code onto the VM

The VM pulls the code from GitHub with a **deploy key**: an SSH key that can read this one
repository and nothing else. You push from your laptop; the VM only ever pulls.

**VM:**

```sh
ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N "" -C cognitrack-vm
cat ~/.ssh/github_deploy.pub
```

GitHub → `Kaivalya078/cognitrack` → Settings → Deploy keys → Add deploy key: paste it, leave
**Allow write access unticked**.

```sh
cat >> ~/.ssh/config <<'EOF'
Host github.com
  IdentityFile ~/.ssh/github_deploy
EOF
git clone git@github.com:Kaivalya078/cognitrack.git ~/CogniTrack
```

The VM deploys whatever is on GitHub, so **push from the laptop first**.

## 9. Settings, your ledger, and first start

**VM:**

```sh
cd ~/CogniTrack
cp .env.example .env
chmod 600 .env                  # only you can read it
openssl rand -hex 24            # copy this: the database password
nano .env
```

In `.env` set:

| Setting | Value |
| --- | --- |
| `POSTGRES_PASSWORD` | the `openssl` output (letters and digits only: it goes into a URL) |
| `ALLOWED_HOSTS` | `["cognitrack","cognitrack.<tailnet>.ts.net","localhost","127.0.0.1"]` |
| `BACKUP_UPLOAD_URL` | leave empty until step 10 |

`DATABASE_URL` and `POSTGRES_PORT` are for the laptop only; the VM ignores them.

**Move your ledger.** Your committed lots live in the laptop's database. Copy them across:

**laptop** (repo root, with the local database running):

```sh
docker compose -f infra/docker-compose.yml --env-file .env exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > ~/ledger.dump
scp ~/ledger.dump cognitrack:~/
```

**VM:**

```sh
cd ~/CogniTrack
alias dc='docker compose -f infra/docker-compose.prod.yml --env-file .env'
echo "alias dc='docker compose -f ~/CogniTrack/infra/docker-compose.prod.yml --env-file ~/CogniTrack/.env'" >> ~/.bashrc

dc up -d db                                   # the database alone first
dc ps                                         # wait until db shows "healthy"
dc exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error' < ~/ledger.dump
dc up -d --build                              # builds and starts api and web (a few minutes)
dc ps                                         # all three "running", api "healthy"
dc exec api python -m app.ledger.summary --as-of 2026-10-12
```

The summary must show the M3 numbers: 15 momentum trades, ₹2,875.69; long-term 31 open lots in
23 stocks, ₹1,33,381.63 invested; Groww cash. Then delete both copies of the dump
(`rm ~/ledger.dump` on the VM and on the laptop): it is your whole ledger.

*Why the database first:* the restore goes into an empty database; the API then starts, sees the
schema is current, and its migrations do nothing.

**From now on the VM is the source of truth.** Upload sheets and exports on the VM's staging page,
not the laptop's; the laptop database is for development only.

**Publish it on your tailnet. VM:**

```sh
sudo tailscale serve --bg --http=80 http://127.0.0.1:8080
tailscale serve status
```

*Why `tailscale serve`:* the web container listens only on the VM's loopback address, which no
other machine can reach. `tailscale serve` forwards your tailnet's port 80 to it. Docker never
publishes anything on a public address, so its habit of bypassing the VM firewall can't expose
anything. Traffic is encrypted by Tailscale end to end, so plain HTTP is fine here.

**Phone:** with Tailscale on, open `http://cognitrack.<tailnet>.ts.net`. The Health card should
say ok; the Staging page shows your committed batches.

**Reboot test. VM:** `sudo reboot`. Two minutes later the page opens again with nothing done by
hand (containers restart themselves; `tailscale serve --bg` is remembered).

## 10. Nightly backups off the VM

Backups go to **Oracle Object Storage** (20 GB free), uploaded with a link that can only *write*
to one bucket: if the VM were ever compromised, that link can't read or delete old backups.

1. Oracle console → Storage → Buckets → **Create bucket** `cognitrack-backups` (Standard tier,
   private).
2. The bucket → Lifecycle Policy Rules → Create: delete objects older than 60 days.
3. The bucket → Pre-Authenticated Requests → **Create**: target *Bucket*, access **Permit object
   writes**, expiration one year from today. Copy the URL (it ends in `/o/`): it is shown once.
   Put a reminder in your calendar a week before it expires to make a new one.
4. **VM:** put the URL in `.env` as `BACKUP_UPLOAD_URL=...`, then:

   ```sh
   sudo install -d -o ubuntu -g ubuntu -m 700 /var/backups/cognitrack
   sudo install -o ubuntu -g ubuntu -m 600 /dev/null /var/log/cognitrack-backup.log
   ~/CogniTrack/infra/backup.sh          # prints "... ok cognitrack-<date>.dump <size> bytes"
   ```

   The file appears in the bucket's Objects list.
5. Run it every night at 02:30 IST. **VM:** `crontab -e`, add the line:

   ```
   30 2 * * * /home/ubuntu/CogniTrack/infra/backup.sh >> /var/log/cognitrack-backup.log 2>&1
   ```

   Check it now and then: `tail /var/log/cognitrack-backup.log`. Every line should say `ok`.

*What the script does:* `pg_dump` from the db container; checks the dump reads back; uploads it;
keeps 14 days on the VM. Any failure stops it with an error in the log. The dumps, their folder
and the log are readable only by `ubuntu` (modes 600/700): a dump is your whole ledger.

**Weekly copy to your laptop.** Both copies above live in one Oracle account; if that account
ever went, they would go with it. Once a week, **laptop** (outside the repo folder):

```sh
mkdir -p ~/cognitrack-backups
scp "cognitrack:$(ssh cognitrack 'ls -t /var/backups/cognitrack/*.dump | head -1')" ~/cognitrack-backups/
```

## 11. Restore test

A backup you've never restored is a hope, not a backup. **VM:**

```sh
cd ~/CogniTrack
infra/restore-test.sh "$(ls -t /var/backups/cognitrack/*.dump | head -1)" --as-of 2026-10-12
dc exec api python -m app.ledger.summary --as-of 2026-10-12
```

The script loads the dump into a throwaway Postgres, prints its migration version
(`0004 (head)` or later) and the ledger summary from the restored copy, and removes it again.
**The two summaries must match.** Repeat after big changes, and occasionally with a file
downloaded from the bucket (on the laptop: `docker build -t cognitrack-api backend` once, then
the same script).

## 12. Updating the app

**laptop:** commit and push. **VM:**

```sh
cd ~/CogniTrack
infra/backup.sh                 # a fresh backup before any change
git pull
dc up -d --build                # rebuilds what changed; migrations run on start
dc ps
docker image prune -f           # now and then: removes old image layers
```

## 13. Done when (M4)

1. **Phone:** with Tailscale on, `http://cognitrack.<tailnet>.ts.net` shows a healthy API and your
   staging batches; the summary on the VM shows the M3 numbers.
2. **Backup:** a dump is in the bucket, and the restore test's summary matches the live one.
3. **Closed to the internet.** Turn Tailscale **off** on the laptop (or use the phone on mobile
   data with Tailscale off):

   ```sh
   curl -m 5 http://<public IP>/                              # times out
   ssh -o ConnectTimeout=5 ubuntu@<public IP>                 # times out
   ```

   With Tailscale back on, the app's host check works through `tailscale serve`:

   ```sh
   curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: evil.example' http://cognitrack.<tailnet>.ts.net/api/health   # 400
   ```

## Troubleshooting

| Symptom | Look at |
| --- | --- |
| "Out of host capacity" when creating the VM | Another availability domain, or retry at a quiet hour |
| Page doesn't load at all | Tailscale on? `tailscale serve status` on the VM; `dc ps` |
| `web` not starting | `dc ps`: it waits for `api` to be healthy; `dc logs api` |
| Every request says "Invalid host header" | `ALLOWED_HOSTS` in `.env` must list the name in the address bar, then `dc up -d` |
| Health card says degraded | `dc logs db`; is the disk full? `df -h` |
| Backup log shows an error | Upload failure: the pre-authenticated request may have expired (step 10.3) |
| SSH over Tailscale fails | Oracle console → Console connection; `sudo tailscale status` |
| VM gone (reclaimed) | Steps 2–9 on a new VM, then restore the latest dump from the bucket instead of the laptop's |
