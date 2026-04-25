# RunPod Serverless Deployment Guide — XTTS v2 Worker

Complete step-by-step instructions for deploying your voice cloning
worker. Should take 30-60 minutes total.

---

## What you're building

A GPU-powered voice cloning worker on RunPod Serverless that:
- Costs ~$0.0005/second of inference (so ~$0.002 per 10-second clip)
- Goes to sleep when idle = $0/hour idle cost
- Wakes up automatically when a request comes in (~20-30 sec cold start)
- Handles concurrent requests across multiple workers

**Monthly cost estimate for your usage**:
- 0 users: $0
- 5 Pro users generating daily: ~$3-8/mo
- 20 Pro users generating daily: ~$15-30/mo
- 100 Pro users generating daily: ~$80-150/mo (consider dedicated GPU at this point)

---

## Step 1: Create a RunPod account (5 min)

1. Go to **https://www.runpod.io/**
2. Click **"Sign Up"** top right
3. Sign up with Google, GitHub, or email
4. Verify your email
5. Go to **"Billing"** in the left sidebar
6. Add **$10 credit** to start (minimum). This covers thousands of generations.
    - Click "Add Credit" → select $10 → pay with card
    - DO NOT enable auto-recharge yet; you want to watch usage first

---

## Step 2: Create a RunPod API key (2 min)

1. In RunPod dashboard, click your avatar (top right) → **"Settings"**
2. Click **"API Keys"** in the left menu
3. Click **"Create API Key"**
4. Give it a name like `voice-app-render`
5. Click **"Create"**
6. **COPY THE KEY IMMEDIATELY** — you will never see it again
   (format looks like: `XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`)
7. Save it somewhere safe (password manager, note on your phone)

---

## Step 3: Build the Docker image (15-30 min)

RunPod Serverless needs your code packaged as a Docker image hosted
somewhere public (Docker Hub is easiest and free).

### Option A: Build on your own computer (if you have Docker installed)

1. Install Docker Desktop if you don't have it: https://www.docker.com/products/docker-desktop
2. Create a free Docker Hub account: https://hub.docker.com/signup
3. Open a terminal in the `xtts-worker/` folder
4. Login: `docker login` (enter your Docker Hub credentials)
5. Build:
   ```bash
   docker build -t YOUR_DOCKERHUB_USERNAME/xtts-worker:latest .
   ```
   ⚠️  This downloads the 1.9 GB XTTS model and builds ~8 GB image.
   First build takes 20-30 minutes. Subsequent builds are faster.
6. Push:
   ```bash
   docker push YOUR_DOCKERHUB_USERNAME/xtts-worker:latest
   ```
   This uploads the image to Docker Hub. Takes 10-20 min depending on upload speed.

### Option B: Build using GitHub Actions (if you don't have Docker locally)

1. Push the `xtts-worker/` folder to a **public** GitHub repo
2. Add this file as `.github/workflows/build.yml` in the repo:

```yaml
name: Build and push Docker image
on:
  push:
    branches: [main]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}
      - uses: docker/build-push-action@v5
        with:
          context: ./xtts-worker
          push: true
          tags: ${{ secrets.DOCKERHUB_USERNAME }}/xtts-worker:latest
```

3. In GitHub repo settings → Secrets and variables → Actions, add:
   - `DOCKERHUB_USERNAME` = your Docker Hub username
   - `DOCKERHUB_TOKEN` = generate at https://hub.docker.com/settings/security
4. Push to main — GitHub Actions will build and push automatically (~20 min)

### Option C: Use RunPod's build service (easiest — no Docker needed)

RunPod can build from a public GitHub repo. See Step 4 below.

---

## Step 4: Create a Serverless endpoint on RunPod (5 min)

1. In RunPod dashboard, click **"Serverless"** in the left sidebar
2. Click **"+ New Endpoint"**
3. Fill in:
   - **Endpoint Name**: `xtts-voice-clone`
   - **Select GPU**:
     - Choose **"24 GB"** tier (RTX 4090 / A5000 — plenty for XTTS v2)
     - Or **"16 GB"** tier (A4000) for slightly cheaper rates
     - Do NOT pick A100/H100 — massively overkill and expensive
   - **Worker Configuration**:
     - Min workers: **0** (key for cost control — zero idle cost)
     - Max workers: **3** (can raise later)
     - Idle timeout: **5 seconds** (kill workers fast to save money)
     - Flashboot: **Enabled** (reduces cold start from 30s → ~5s)
   - **Container Image**:
     - If you used Option A or B: `YOUR_DOCKERHUB_USERNAME/xtts-worker:latest`
     - If using Option C: point to your public GitHub repo
   - **Container Registry Credentials**: leave blank (image is public)
   - **Container Disk**: **20 GB** (model + dependencies need ~10 GB)
   - **Environment Variables** — click "+ Add" and add:
     | Name | Value |
     |------|-------|
     | `WORKER_SECRET` | A long random string — GENERATE ONE NOW and save it. Example: `x7k2mp9qL4nR8tV6wZ3aB5cF1dH0jN` |
     | `COQUI_TOS_AGREED` | `1` |

4. Click **"Deploy"**

5. Wait for the endpoint to initialize (shows green "Ready" when done, ~2-5 min)

6. **COPY THE ENDPOINT ID** from the endpoint page — it's a string like `abc123xyz456`. You'll need it.

---

## Step 5: Test the endpoint (3 min)

Before wiring up your Render app, verify the worker works.

From a terminal on your computer:

```bash
# Replace these with your actual values
ENDPOINT_ID="your_endpoint_id_here"
API_KEY="your_runpod_api_key_here"
SECRET="your_worker_secret_here"

# Make a tiny test audio file (10 sec silence — just to verify auth/routing)
python3 -c "
import wave, struct
with wave.open('test.wav', 'wb') as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
    for _ in range(240000): w.writeframes(struct.pack('<h', 0))
"

# Base64 encode it
SPEAKER_B64=$(base64 -w 0 test.wav)

# Call the endpoint
curl -X POST "https://api.runpod.ai/v2/${ENDPOINT_ID}/runsync" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{
    \"input\": {
      \"secret\": \"${SECRET}\",
      \"text\": \"Hello world, this is a test.\",
      \"language\": \"en\",
      \"speed\": 1.0,
      \"speaker_audio_b64\": \"${SPEAKER_B64}\"
    }
  }" | head -c 300
```

**Expected**: a response with `"status": "COMPLETED"` and an `"audio_b64"` field
(you'll just see the first 300 chars so it doesn't flood your terminal).

**If you get an error**:
- `"Unauthorized"` → secret mismatch. Check `WORKER_SECRET` env var matches what you put in the curl.
- `"invalid token"` from RunPod → API key is wrong. Regenerate at Settings → API Keys.
- Endpoint shows "IN_QUEUE" for 2+ minutes → cold start. Wait and retry.
- Container crashes / unhealthy → check endpoint logs in RunPod dashboard.

---

## Step 6: Wire into your Render app (2 min)

1. Go to your Render dashboard → your voice-app service → **"Environment"**
2. Add these three environment variables:
   | Name | Value |
   |------|-------|
   | `RUNPOD_ENDPOINT_ID` | Your endpoint ID from Step 4 |
   | `RUNPOD_API_KEY` | Your RunPod API key from Step 2 |
   | `XTTS_WORKER_SECRET` | The same `WORKER_SECRET` you set on RunPod |
3. Click **"Save Changes"** → Render will auto-redeploy (~2-3 min)
4. After redeploy, voice cloning is LIVE.

---

## Step 7: Verify it works end-to-end (2 min)

1. Open your app (logged in as a Pro user)
2. Go to the tool page
3. If you already saved a voice, select it from the dropdown
4. Type something short: "Hello, this is my cloned voice."
5. Click Generate Voice
6. First request after idle: wait ~20-30 seconds (cold start)
7. You should hear your cloned voice speaking the text

**Cold start behavior**:
- First request after 10+ minutes of idle: ~20-30 seconds
- Requests within 10 minutes of another: ~3-10 seconds
- Users see "Generating..." during this time — no timeout issue

---

## Cost monitoring (important!)

1. Go to RunPod dashboard → **"Billing"** → **"Usage"**
2. Check daily. You should see charges like:
   - `xtts-voice-clone`: $0.47 today (2,140 seconds runtime)
3. Set a **billing alert**:
   - Go to Billing → **"Spend Alert"**
   - Set threshold: `$20`
   - You'll get an email when you cross $20 in a billing cycle

**Warning signs to watch for**:
- Usage jumping suddenly (>$5/day with few users) → someone is abusing your app, check the audit log
- Workers not going to sleep → verify `idle_timeout=5s` in endpoint settings
- Images failing to start → check endpoint health; may need to rebuild Docker image

---

## Troubleshooting

**"Worker unhealthy" errors**:
- Check Docker image is public on Docker Hub
- Check endpoint logs in RunPod dashboard
- Try reducing Container Disk if close to capacity

**"Model download taking forever"**:
- The Dockerfile bakes XTTS into the image so this shouldn't happen on cold start.
- If it IS happening, your image build didn't include the `RUN python -c ...` step.

**Audio quality is poor**:
- Recording quality matters! Ask users to record in a quiet room, close to the mic.
- 30 seconds of clean audio is better than 2 minutes of noisy audio.

**Urdu sounds like Hindi**:
- That's expected — XTTS doesn't support Urdu, we remap to Hindi.
- Tell users: "For best Urdu results, speak clearly in your voice sample."

---

## When to migrate to a dedicated GPU

If you see any of these, upgrade to a dedicated always-on GPU:
- Monthly RunPod bill exceeds $100
- More than 30% of requests hit cold starts
- Users complain about the 20-30 sec wait
- You have 100+ active paying users

At that point, migrating is trivial: rent a dedicated GPU (RunPod or Hetzner),
deploy the same Docker image, update `XTTS_WORKER_URL` in Render (swap from
RUNPOD_ENDPOINT_ID to XTTS_WORKER_URL), done.