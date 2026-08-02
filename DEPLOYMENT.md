# Deploying to an Oracle Cloud VM

The project ships with `docker/Dockerfile` and `docker/docker-compose.yml`
(app container running on SQLite, data kept in a named volume), so deployment
is: install Docker, get the code, set secrets, `docker compose up`.

Commands are given for both common Oracle Cloud images — **Ubuntu** and
**Oracle Linux** — use whichever matches your VM.

## 1. Connect to the VM

```bash
ssh -i /path/to/your-key.pem <ubuntu-or-opc>@<VM_PUBLIC_IP>
```

(`ubuntu` user for an Ubuntu image, `opc` for Oracle Linux.)

## 2. Install Docker + Compose plugin

**Ubuntu:**

```bash
sudo apt update && sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker $USER   # log out and back in for this to take effect
```

**Oracle Linux:**

```bash
sudo dnf install -y dnf-utils
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker $USER   # log out and back in
```

## 3. Get the code onto the VM

```bash
git clone https://github.com/abhinav162/WatchMyTicket.git
cd WatchMyTicket
```

If the repo is private, clone with a Personal Access Token
(`https://<token>@github.com/...`) or an SSH deploy key.

## 4. Configure secrets

```bash
cp .env.example .env
nano .env       # set TELEGRAM_BOT_TOKEN at minimum
chmod 600 .env
```

Leave `DATABASE_URL` as the default SQLite path — the app stores its
database inside the container at `./storage/ticket_watcher.db`, which
`docker-compose.yml` mounts as a named volume (`app_storage`) so it
survives restarts and rebuilds.

## 5. Launch

```bash
docker compose -f docker/docker-compose.yml up -d --build
```

## 6. Verify it's actually running

```bash
docker compose -f docker/docker-compose.yml ps
docker compose -f docker/docker-compose.yml logs -f app
curl http://localhost:8000/health
```

You should see `Scheduler started (every 60s...)` in the logs and a
`/health` response with `"scheduler_running": true`.

## 7. Networking — likely nothing to do

The bot only makes **outbound** connections (long-polling Telegram, scraping
BookMyShow) — no inbound port needs to be open for notifications to work.
Skip this section unless you want the REST API / `/health` reachable from
outside the VM.

If you do want that: Oracle Cloud has **two** firewalls that both default to
blocking inbound traffic — the cloud-level Security List/NSG (VM instance
page → attached VCN → Security Lists) *and* the OS-level firewall on the
instance itself. Open port 8000 in both:

```bash
# Ubuntu (iptables — ufw usually isn't the active one on OCI images)
sudo iptables -I INPUT -p tcp --dport 8000 -j ACCEPT
sudo netfilter-persistent save   # or: sudo apt install iptables-persistent first

# Oracle Linux (firewalld)
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --reload
```

plus adding an ingress rule for port 8000 in the OCI console's Security List.

## 8. Surviving reboots

`systemctl enable docker` (done in step 2) starts Docker on boot, and
`restart: unless-stopped` in `docker-compose.yml` brings the container back
up automatically. Worth testing once with `sudo reboot` and re-checking
`docker compose ps` afterwards.

## Day-2 operations

```bash
# Deploy new code
git pull && docker compose -f docker/docker-compose.yml up -d --build

# Tail logs
docker compose -f docker/docker-compose.yml logs -f app

# Stop (keeps the app_storage volume — SQLite data survives)
docker compose -f docker/docker-compose.yml down

# Stop AND wipe the database
docker compose -f docker/docker-compose.yml down -v
```

## Notes

- SQLite means the app must stay a single process/container. Fine for one
  scheduler + one bot; if this ever needs to scale to multiple app instances
  behind a load balancer, switch to a shared database (e.g. add a `db`
  service back to `docker-compose.yml` and point `DATABASE_URL` at it) —
  SQLite doesn't handle concurrent writers from separate processes well.
- Keep `.env` out of version control (already gitignored) and `chmod 600` it
  on the server — it holds your Telegram bot token.
