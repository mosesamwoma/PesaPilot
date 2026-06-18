# PesaPilot — Hosting Guide

Complete guide to hosting the WhatsApp bot (whatsapp_bot.js + whatsapp_api.py) on every major free platform.

The bot needs three things from a host:
- Always-on (never sleeps or spins down)
- Runs Node.js and Python together
- Supports headless Chromium (required by whatsapp-web.js)

---

## Quick Reference

| Platform | Free Forever | Always-On | Chrome | Verdict |
|----------|-------------|-----------|--------|---------|
| Oracle Cloud | Yes | Yes | Yes | Best overall |
| Google Cloud | Yes | Yes | Yes | Best backup |
| Fly.io | Yes | Yes | Yes | Easiest setup |
| Koyeb | Yes | Yes | Yes | Simplest UI |
| AWS Free Tier | 12 months | Yes | Yes | Good to start |
| Azure Free Tier | 12 months | Yes | Yes | Good to start |
| DigitalOcean | $200 credit | Yes | Yes | 60 days free |
| Linode/Akamai | $100 credit | Yes | Yes | 60 days free |
| Vultr | $100 credit | Yes | Yes | 60 days free |
| Hetzner | No free tier | Yes | Yes | Cheapest paid ($4/mo) |
| Railway | Credit only | Yes | Yes | Runs out in ~3 weeks |
| Render | No | Spins down | — | Does not work |
| Vercel | No | Serverless | — | Does not work |
| Netlify | No | Serverless | — | Does not work |
| Heroku | No free tier | — | — | Does not work |
| Replit | No | Sleeps | — | Does not work |
| Glitch | No | Sleeps | — | Does not work |

---

## Tier 1 — Free Forever

### Oracle Cloud Free Tier

The best free option. Two VMs with 1GB RAM each, free permanently with no expiry and no credit card charges after signup.

**Setup:**

1. Go to [cloud.oracle.com](https://cloud.oracle.com) → Create Account
2. Choose Always Free VM → Ubuntu 22.04 → 1 OCPU → 1GB RAM
3. SSH into the server:

```bash
# Install dependencies
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs python3 python3-pip chromium-browser
sudo npm install -g pm2

# Clone project
git clone https://github.com/mosesamwoma/PesaPilot.git
cd PesaPilot
pip3 install -r requirements.txt fastapi uvicorn
npm install whatsapp-web.js qrcode-terminal axios

# Add env variables
nano .env

# Start both processes
pm2 start "uvicorn whatsapp_api:app --port 8000" --name pesapilot-api
pm2 start whatsapp_bot.js --name pesapilot-whatsapp
pm2 save && pm2 startup
```

---

### Google Cloud Free Tier

One e2-micro VM free forever in us-west1, us-central1, or us-east1 regions. 30GB disk included.

**Setup:**

1. Go to [cloud.google.com](https://cloud.google.com) → Create Account
2. Compute Engine → Create Instance → e2-micro → Ubuntu 22.04
3. Region must be us-west1, us-central1, or us-east1 for it to be free
4. SSH into the instance from the browser:

```bash
# Install dependencies
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs python3 python3-pip chromium-browser
sudo npm install -g pm2

# Clone and set up
git clone https://github.com/mosesamwoma/PesaPilot.git
cd PesaPilot
pip3 install -r requirements.txt fastapi uvicorn
npm install whatsapp-web.js qrcode-terminal axios
nano .env

# Start
pm2 start "uvicorn whatsapp_api:app --port 8000" --name pesapilot-api
pm2 start whatsapp_bot.js --name pesapilot-whatsapp
pm2 save && pm2 startup
```

---

### Fly.io

Three always-on shared VMs free forever. Easiest deployment — no server management, just deploy with CLI.

**Setup:**

```bash
# Install Fly CLI
curl -L https://fly.io/install.sh | sh
fly auth signup
```

Create `Dockerfile` in project root:

```dockerfile
FROM node:18-slim

RUN apt-get update && apt-get install -y \
    python3 python3-pip chromium \
    --no-install-recommends && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY requirements.txt ./
RUN pip3 install -r requirements.txt fastapi uvicorn --break-system-packages

COPY . .

EXPOSE 8000

CMD uvicorn whatsapp_api:app --host 0.0.0.0 --port 8000 & node whatsapp_bot.js
```

Create `fly.toml` in project root:

```toml
app = "pesapilot-whatsapp"
primary_region = "jnb"

[build]

[http_service]
  internal_port = 8000
  force_https = false
  auto_stop_machines = false
  auto_start_machines = true

[[mounts]]
  source = "pesapilot_data"
  destination = "/app/.wwebjs_auth"
```

Deploy:

```bash
# Set environment variables
fly secrets set SUPABASE_URL=https://your-project.supabase.co
fly secrets set SUPABASE_KEY=your-key
fly secrets set GROQ_API_KEY=your-key
fly secrets set LLM_MODEL=llama3-70b-8192
fly secrets set LLM_TEMPERATURE=0.3
fly secrets set LLM_MAX_TOKENS=1000

# Create persistent volume for WhatsApp session
fly volumes create pesapilot_data --size 1

# Deploy
fly launch
fly deploy

# Watch logs for QR code — scan once
fly logs
```

---

### Koyeb

Always-on free tier with the simplest UI of all platforms. Supports Docker deployments.

**Setup:**

1. Go to [koyeb.com](https://koyeb.com) → Sign up
2. New App → Docker → connect your GitHub repo
3. Use the same `Dockerfile` from the Fly.io section above
4. Under **Environment Variables**, add all your `.env` keys
5. Deploy

Scan QR code from the deployment logs once — done.

---

## Tier 2 — Free for a Limited Time

Good options to start immediately while you set up a permanent host.

### AWS Free Tier (12 months)

t2.micro VM, 1GB RAM, free for 12 months from account creation.

```bash
# After creating EC2 instance (Ubuntu 22.04) and SSH-ing in:
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs python3 python3-pip chromium-browser
sudo npm install -g pm2

git clone https://github.com/mosesamwoma/PesaPilot.git
cd PesaPilot
pip3 install -r requirements.txt fastapi uvicorn
npm install whatsapp-web.js qrcode-terminal axios
nano .env

pm2 start "uvicorn whatsapp_api:app --port 8000" --name pesapilot-api
pm2 start whatsapp_bot.js --name pesapilot-whatsapp
pm2 save && pm2 startup
```

---

### Azure Free Tier (12 months)

B1s VM (1 vCPU, 1GB RAM) free for 12 months.

1. Go to [azure.microsoft.com](https://azure.microsoft.com) → Free Account
2. Create Virtual Machine → Ubuntu 22.04 → B1s size
3. SSH in and follow the same commands as AWS above

---

### DigitalOcean ($200 credit — ~60 days)

$200 free credit on signup, valid for 60 days. Cheapest Droplet is $6/month so credit covers ~33 months worth — but credit expires after 60 days regardless.

```bash
# Create Droplet: Ubuntu 22.04, Basic, $6/month plan
# SSH in, then:
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs python3 python3-pip chromium-browser
sudo npm install -g pm2

git clone https://github.com/mosesamwoma/PesaPilot.git
cd PesaPilot
pip3 install -r requirements.txt fastapi uvicorn
npm install whatsapp-web.js qrcode-terminal axios
nano .env

pm2 start "uvicorn whatsapp_api:app --port 8000" --name pesapilot-api
pm2 start whatsapp_bot.js --name pesapilot-whatsapp
pm2 save && pm2 startup
```

---

### Linode / Akamai Cloud ($100 credit — 60 days)

$100 credit on signup, valid for 60 days. Same setup as DigitalOcean once you SSH in.

Sign up at [linode.com](https://linode.com) → Create Linode → Ubuntu 22.04 → Nanode 1GB plan ($5/month).

---

### Vultr ($100 credit — 30 days)

$100 credit valid for 30 days. Cloud Compute → Ubuntu 22.04 → 1GB RAM plan. Same commands once inside.

---

## Tier 3 — Does Not Work

These platforms cannot host whatsapp-web.js regardless of plan.

### Render (Free Tier)
Spins down after 15 minutes of inactivity. WhatsApp session dies and reconnecting requires rescanning QR every time.

### Vercel
Serverless functions only. Cannot run persistent Node.js or Python processes.

### Netlify
Serverless only. Same issue as Vercel.

### Heroku
Removed free tier in November 2022. Cheapest plan is $5/month.

### Railway
Not free — provides $5 credit/month which runs out in roughly 3 weeks of always-on usage, then charges your card.

### Replit
Free tier sleeps after inactivity. Paid Hacker plan ($7/month) keeps it always-on but that defeats the purpose.

### Glitch
Sleeps after 5 minutes of inactivity on free tier.

---

## Keeping the WhatsApp Session Alive

The session is stored in `.wwebjs_auth` folder in your project root. As long as this folder exists on the server, no QR rescan is needed.

```bash
# Check session exists
ls .wwebjs_auth/

# If QR is needed again (Fly.io)
fly logs

# If QR is needed again (PM2 on VM)
pm2 logs pesapilot-whatsapp
```

Session typically lasts weeks to months. On mobile WhatsApp, linked devices expire after 14 days of the phone being offline — keep your Airtel phone on or connected periodically.

---

## Recommended Path

```
Today      → Fly.io (fastest to get running, free forever)
Long term  → Oracle Cloud (most resources, most reliable, free forever)
```

Start on Fly.io to get the bot live immediately, then migrate to Oracle Cloud for maximum stability.
