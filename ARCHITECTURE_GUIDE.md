# Vercel XHTTP Relay Architecture Guide

## Purpose

This document captures the practical architecture decisions and production lessons from building and operating a Vercel-based XHTTP relay for Xray/VLESS traffic. It is intended as the single source of truth for future developers.

## System Overview

The relay flow is:

1. Client connects to Vercel production domain over TLS on port 443.
2. Vercel Edge function receives XHTTP traffic and forwards the request stream to the configured backend origin from TARGET_DOMAIN.
3. Backend Xray inbound (3x-ui) handles VLESS over XHTTP and returns stream responses back through Vercel.

This works as an HTTP transport bridge, not as a raw TCP/UDP tunnel.

## Critical Operational Lessons

### 1) Vercel Edge IP Restriction

Vercel Edge blocks direct requests to bare IP origins. If TARGET_DOMAIN points to an IP address, deployment traffic fails with the error:

Direct IP access is not allowed

Required practice:

- TARGET_DOMAIN must be a domain-based URL.
- Example accepted form: http://sh.sooshiant.click:50666
- Example rejected form: http://1.2.3.4:50666

Why this matters:

- The relay cannot connect upstream unless DNS hostname routing is used.
- Any automation that sets TARGET_DOMAIN must validate that it is a hostname URL, not an IP URL.

### 2) Cloudflare Grey Cloud Requirement

Because Xray inbound is exposed on custom port 50666, Cloudflare proxy mode must be disabled for that DNS record.

Required DNS mode:

- DNS Only (Grey Cloud): required and working
- Proxied (Orange Cloud): blocks or interferes with this traffic pattern on custom port path

Why this matters:

- Orange Cloud proxying is not transparent for this custom-port transport path.
- If set incorrectly, the relay may appear healthy while backend connectivity silently fails.

### 3) Vercel Authentication and 401 Errors

Vercel often issues temporary deployment URLs protected by Vercel Authentication. V2ray/Xray clients do not handle this gate and receive HTTP 401.

Observed behavior:

- Temporary deployment URL returns authentication barrier.
- Client transport fails due to unauthorized response.

Required solutions:

1. Use the stable production domain for client traffic, such as my-xhttp-relay-two.vercel.app.
2. Or disable Vercel Authentication in Deployment Protection if policy permits.

Why this matters:

- Even perfect backend config fails if client hits protected preview URLs.
- Mobile and desktop clients need direct unauthenticated transport path.

### 4) Xray Server Configuration Constraints

On 3x-ui inbound, the working profile is:

- Protocol: VLESS
- Port: 50666
- Transmission: XHTTP
- Security: none
- Padding: empty value

Crucial tuning:

- Security must be none on inbound for this architecture.
- Padding must be fully empty, not a range like 100-1000.

Why this matters:

- Non-empty padding introduced buffer and compatibility instability when relayed through Vercel Edge behavior.
- Keeping payload framing clean and minimal avoids transport breakage.

### 5) Final Known-Good Client VLESS Format

The known-good VLESS client format is:

vless://[UUID]@[VERCEL_PROD_DOMAIN]:443?encryption=none&security=tls&sni=[VERCEL_PROD_DOMAIN]&alpn=h2,http/1.1&fp=chrome&type=xhttp&host=[VERCEL_PROD_DOMAIN]&path=/&mode=auto#Vercel-Connection

Notes:

- UUID must match server user.
- VERCEL_PROD_DOMAIN must be a production domain, not an auth-protected preview URL.
- XHTTP mode remains auto.

## Deployment and Runtime Guardrails

1. TARGET_DOMAIN must always remain hostname-based.
2. Upstream DNS record for custom backend port must remain DNS Only in Cloudflare.
3. Production client distribution must always use stable production Vercel domain.
4. Inbound settings drift (security or padding changes) should be treated as incident-level risk.

## FastAPI Bridge Role in Phase 2

Phase 2 backend is responsible for generating user-specific VLESS links by injecting runtime UUID plus active production Vercel domain into the known-good template.

This isolates clients from manual configuration and reduces operator mistakes.

## Step-by-Step Debugging Journey (Chronological)

This section records the exact troubleshooting path that led to the final working architecture.

### Step 1: Direct IP Upstream Failed on Vercel Edge

- Initial TARGET_DOMAIN attempt used raw IP: 64.110.98.173
- Vercel Edge returned: Direct IP access is not allowed

Conclusion:

- Vercel Edge will not relay to bare IP upstreams.
- TARGET_DOMAIN must always be a domain URL.

### Step 2: Switched TARGET_DOMAIN to Cloudflare-backed Hostname

- Replaced raw IP with domain endpoint: sh.sooshiant.click:50666
- Relay progressed beyond Vercel IP restriction.

Conclusion:

- Domain indirection resolved the Vercel Edge upstream policy block.

### Step 3: Fixed Cloudflare Proxy Mode for Custom Port

- With Orange Cloud enabled, custom port 50666 traffic was blocked or disrupted.
- Changed DNS record to DNS Only (Grey Cloud).

Conclusion:

- Grey Cloud is mandatory for this setup on custom port 50666.
- Orange Cloud must remain disabled for the relay upstream record.

### Step 4: Resolved Vercel Authentication 401 on Preview URLs

- Preview deployment URL returned HTTP 401 for V2ray clients due to Vercel Authentication.
- Migrated client usage to Production domain: my-xhttp-relay-two.vercel.app

Conclusion:

- Clients must use production domain or a deployment without authentication gate.
- Auth-protected preview URLs are not suitable for this transport flow.

### Step 5: Interpreted HTTP 400 as Positive End-to-End Signal

- Browser request to production relay returned HTTP ERROR 400 (Bad Request).

Why this is success, not failure:

- Browser traffic is not valid VLESS/XHTTP payload.
- 400 confirms request reached Xray core through full chain:
	Vercel -> Cloudflare DNS-only host -> Xray inbound
- Xray rejected malformed protocol payload as expected.

### Step 6: Ubuntu Python Package Constraint Workaround

- Ubuntu raised externally-managed-environment during pip installs.
- Installed dependencies using:
	pip install fastapi uvicorn --break-system-packages

Conclusion:

- For this server baseline, --break-system-packages was required to proceed quickly.

### Step 7: FastAPI Service Stabilized under PM2

- FastAPI API successfully run via PM2.
- Service bound and reachable on 127.0.0.1:8000.

Conclusion:

- PM2 provides stable process supervision for the configuration API service.

## Deployment & Troubleshooting

### Ubuntu Python Environment Restriction

On modern Ubuntu releases, global pip installs can fail with:

externally-managed-environment

Resolution used in this project:

- Use the break-glass install flag for this server instance.
- Example command:
	pip install python-telegram-bot qrcode pillow requests --break-system-packages

Operational note:

- This was intentionally used to move forward quickly on the target host.
- Keep this behavior documented for reproducibility across rebuilds.

### Process Management with PM2

Both Phase 2 (FastAPI) and Phase 3 (Telegram bot) are intended to run as daemonized background services.

Implementation pattern:

- Start process with explicit Python interpreter:
	pm2 start <script_name>.py --name "<app_name>" --interpreter python3
- Persist process list across reboots:
	pm2 save

Why this matters:

- Prevents process exits from taking services offline.
- Keeps API and bot continuously available.

### Telegram Bot Crash Loop (InvalidToken)

Observed symptom:

- Telegram bot crashed immediately and PM2 logs showed InvalidToken.

Root cause discovered:

- Token export command had a typographic prefix character (Persian character 'ت') before TELEGRAM_BOT_TOKEN value.

Resolution:

- Re-exported the exact token value without any extra characters.

### Applying Environment Variable Changes in PM2

Critical behavior:

- For an already running PM2 process, a plain restart may keep stale environment values.

Required command when env values change:

- pm2 restart tg-vpn-bot --update-env

Why this matters:

- Ensures corrected variables are injected into the daemonized runtime.
- Essential when fixing authentication values such as TELEGRAM_BOT_TOKEN.
