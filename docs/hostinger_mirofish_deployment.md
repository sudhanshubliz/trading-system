# Hostinger MiroFish Deployment

## Safety Boundary

This deployment is for paper and shadow research only. The compose file hard-overrides live trading disabled, unarmed, and paper execution regardless of the env file.

The trading API currently has no production identity layer. Do not publish ports `8000` or `5001` to the internet. The supplied compose file binds the trading API to VPS loopback and exposes MiroFish only to the private Docker network.

## Hostinger Prerequisites

- Hostinger VPS with the Ubuntu 24.04 Docker template.
- SSH public-key access. Restrict port `22` to the operator IP where practical.
- KVM 2 can be used for a small pilot. KVM 4 is the safer starting point for MiroFish and the trading backend together.
- Newly rotated Zep and LLM credentials. Never reuse credentials disclosed in chat, logs, or source control.

Ports `80` and `443` are not required for the initial SSH-tunnel deployment. Open them only when a TLS reverse proxy and backend authentication have been added. Never open `5001`, `8000`, or database ports publicly.

## Install

Connect to the VPS and verify Docker:

```bash
ssh root@YOUR_VPS_IP
docker --version
docker compose version
```

Create a non-root deployment user, install its SSH key, and grant only the access needed to operate Docker. Then clone the trading repository as that user:

```bash
git clone https://github.com/sudhanshubliz/trading-system.git
cd trading-system
```

Create the ignored runtime env files:

```bash
cp deploy/hostinger/mirofish.env.example deploy/hostinger/mirofish.env
cp deploy/hostinger/trading-system.env.example deploy/hostinger/trading-system.env
chmod 600 deploy/hostinger/mirofish.env deploy/hostinger/trading-system.env
```

Edit `deploy/hostinger/mirofish.env` directly on the VPS. Set a fresh `SECRET_KEY`, replacement `ZEP_API_KEY`, and the LLM provider fields. Do not send these values through chat or commit them.

## Validate And Start

Validate the resolved compose configuration using the populated env files:

```bash
docker compose -f deploy/docker-compose.hostinger.yml config --quiet
```

Pull MiroFish, build the trading backend, and start the stack:

```bash
docker compose -f deploy/docker-compose.hostinger.yml pull mirofish
docker compose -f deploy/docker-compose.hostinger.yml up -d --build
docker compose -f deploy/docker-compose.hostinger.yml ps
```

Inspect startup logs without printing environment variables:

```bash
docker compose -f deploy/docker-compose.hostinger.yml logs --tail=100 mirofish
docker compose -f deploy/docker-compose.hostinger.yml logs --tail=100 trading-system
```

Run the fail-closed verification. `--start-shadow` starts only the simulation path:

```bash
python3 scripts/verify_hostinger_deployment.py \
  --base-url http://127.0.0.1:8000 \
  --start-shadow
```

The command fails unless the backend is ready, execution mode is paper, live is disabled/unarmed, the real MiroFish upstream is reachable, provider health has no unhealthy entries, and shadow is running.

## Operator Access

Create a tunnel from the operator laptop:

```bash
ssh -N -L 8000:127.0.0.1:8000 YOUR_USER@YOUR_VPS_IP
```

The tunneled backend is then available locally at `http://127.0.0.1:8000`. Point the local operator dashboard at that address:

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_API_STREAM_URL=http://127.0.0.1:8000/api/v1/system/stream
```

This keeps dangerous backend actions off the public internet while preserving the dashboard and SSE stream.

## Operations

Check status:

```bash
docker compose -f deploy/docker-compose.hostinger.yml ps
docker stats --no-stream
python3 scripts/verify_hostinger_deployment.py --base-url http://127.0.0.1:8000
```

Update deliberately:

```bash
git pull --ff-only
docker compose -f deploy/docker-compose.hostinger.yml pull mirofish
docker compose -f deploy/docker-compose.hostinger.yml up -d --build
```

Stop without deleting persisted volumes:

```bash
docker compose -f deploy/docker-compose.hostinger.yml down
```

Do not use `down -v` unless permanent deletion of MiroFish uploads and trading databases is explicitly intended. Pin `MIROFISH_IMAGE` to a reviewed image digest before relying on reproducible simulations.

## Promotion Constraint

MiroFish remains advisory and non-tradable. A healthy MiroFish deployment does not qualify any strategy for live promotion. Replay, after-cost expectancy, shadow evidence, provider health, incident state, RiskService, approval, and guarded-live controls remain mandatory.
