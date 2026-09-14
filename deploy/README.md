# Deploying on Oracle Cloud (Always Free)

The bot is a single long-running Python process. It opens **no ports** — it only
makes outbound HTTPS calls to YouTube and Discord — so nothing needs to be
exposed and Oracle's restrictive default firewall can stay exactly as it is.

---

## 1. Pick the shape

Oracle's Always Free tier gives you two options, and the choice matters:

| Shape | Free allowance | Verdict |
|---|---|---|
| **VM.Standard.A1.Flex** (Ampere, ARM64) | 4 OCPU / 24 GB split across instances | **Recommended.** Give it 1 OCPU / 6 GB and never think about it again. |
| VM.Standard.E2.1.Micro (x86) | 1 OCPU / 1 GB, ×2 | Workable, but 1 GB is tight — add swap (step 3) and consider lowering `MAX_RESULTS`. |

Image: **Ubuntu 22.04 or 24.04**. Both ship a new enough Python (3.10 / 3.12);
the bot needs **3.10+**.

On ARM64 every dependency (Pillow, aiohttp, discord.py) installs from a
prebuilt wheel — no compiler, no build-essential.

---

## 2. Install

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip git fonts-roboto-unhinted fonts-dejavu-core
```

A font is not optional. The grid renderer measures text to wrap titles, and
with no TrueType font on the box it falls back to a bitmap font that measures
wrong — titles come out clipped or overflowing.

`fonts-roboto-unhinted` is what you actually want: YouTube itself sets titles
in Roboto Medium and the channel line in Roboto Regular, so with it installed
the grid matches the real thing. DejaVu is the last-resort fallback, and its
Bold face is noticeably heavy and wide at title size. `selftest.py` prints
which face each weight resolved to, so you can see what you got.

```bash
sudo mkdir -p /opt/takanosu-bot
sudo chown "$USER":"$USER" /opt/takanosu-bot
git clone https://github.com/TheTakanosu/Takanosu-YT-Indexer.git /opt/takanosu-bot
cd /opt/takanosu-bot

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

Then create the `.env`:

```bash
cp .env.example .env
nano .env          # paste your DISCORD_TOKEN
chmod 600 .env     # keep the token off other users' eyes
```

Verify before wiring up systemd — this hits YouTube and renders a grid without
touching Discord:

```bash
.venv/bin/python selftest.py
```

Expect `RESULT: passed`.

---

## 3. Swap (only on the 1 GB x86 micro)

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

If you still see the process getting killed, lower `MAX_RESULTS` in
[config.py](../config.py) from `RESULTS_PER_PAGE * 6` to `RESULTS_PER_PAGE * 3`
— that halves how many thumbnails are held in memory at once.

---

## 4. Coming from the old single-file bot? Migrate first

If this server previously ran the original `main.py`, its state lives in JSON
files next to it — `sessions.json` (queues), `saved_custom_playlists.json`,
`shared_playlists.json`, `user_settings.json`, `guild_settings.json`. Starting
the new bot without migrating them loses every user's queue and saved list.

```bash
# keep the old folder safe first
mkdir -p ~/backups
tar czf ~/backups/old-bot-$(date +%F).tar.gz -C ~ --exclude='*/.venv' <old-folder>

# then import the JSON into the SQLite vault
.venv/bin/python deploy/migrate_from_json.py <folder with the .json files>
```

It prints exactly what it moved, only ever reads the JSON, and is safe to
re-run. Share tokens keep their original `GHOST-XXXXXX` codes so links already
posted in chat keep working.

---

## 5. Run it as a service

```bash
sudo cp deploy/takanosu-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now takanosu-bot
```

Check it:

```bash
systemctl status takanosu-bot
journalctl -u takanosu-bot -f
```

A healthy start logs `cog loaded:` seven times and then
`connected: <BotName> (N guilds)` — check that name is the bot you meant.

### Running from a home directory instead

If the checkout is not `/opt/takanosu-bot` — say `/home/ubuntu/Takanosu-YT-Indexer` —
edit `User=`, `Group=`, `WorkingDirectory=`, `ExecStart=` and `ReadWritePaths=`
to match, and rename the unit to whatever you want to type:

```bash
D=/home/ubuntu/Takanosu-YT-Indexer
sed -e "s|/opt/takanosu-bot|$D|g" deploy/takanosu-bot.service \
  | sudo tee /etc/systemd/system/takanosu-bot.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now takanosu-bot
```

`ProtectHome=read-only` in the unit still allows this: `ReadWritePaths` punches
through it for the `data/` directory, which is the only place the bot writes.

Verify the unit parses cleanly — a key in the wrong section is silently ignored:

```bash
sudo systemd-analyze verify /etc/systemd/system/takanosu-bot.service
```

---

## 6. Updating

```bash
cd /opt/takanosu-bot
git pull
.venv/bin/pip install -r requirements.txt
sudo systemctl restart takanosu-bot
```

The database migrates itself on start (new tables are created if missing), so
a pull-and-restart is safe. Nothing is dropped.

---

## 7. Back up one file

Everything user-facing lives in **`data/vault.db`** — queues, saved playlists,
share tokens, playback history, per-user themes and regions, per-guild prefixes
and channel locks. It is the only file worth backing up.

```bash
# safe to run while the bot is live: sqlite3 handles the locking
sudo apt install -y sqlite3
sqlite3 /opt/takanosu-bot/data/vault.db ".backup '/home/ubuntu/vault-$(date +%F).db'"
```

A nightly copy via cron is enough:

```bash
(crontab -l 2>/dev/null; echo '0 4 * * * sqlite3 /opt/takanosu-bot/data/vault.db ".backup /home/ubuntu/vault-backup.db"') | crontab -
```

---

## Notes

**Do not open any ingress ports.** Oracle's Ubuntu images ship iptables rules
that drop most inbound traffic, and that is correct here — the bot never
listens. If you touch the security list at all, you are solving a problem this
bot does not have.

**One IP, one rate limit.** YouTube throttles per source address. If you run
several bot instances on the same VM they share that budget and will start
seeing `⚠️ YouTube refused the request` sooner. `config.py`'s `Throttle`
(8 concurrent, ≥200 ms apart) is tuned for one instance per IP.

**Do not commit `.env`.** It is gitignored, but on a shared box also
`chmod 600` it as shown above.

**Clock matters.** Share tokens expire on wall-clock time (48 h). Oracle images
run `systemd-timesyncd` by default; leave it on.
