# phpipam_config

A collection of configuration resources for deploying [phpIPAM](https://phpipam.net/) using Docker and synchronising IP address data from OPNsense.

---

## Table of Contents

- [Overview](#overview)
- [Requirements](#requirements)
- [Docker Compose](#docker-compose)
- [phpIPAM Node Configuration](#phpipam-node-configuration)
- [OPNsense → phpIPAM Sync Script](#opnsense--phpipam-sync-script)
- [License](#license)

---

## Overview

[phpIPAM](https://phpipam.net/) is an open-source IP Address Management (IPAM) web application. This repository documents how to:

1. Deploy phpIPAM and its dependencies using **Docker Compose**.
2. Configure phpIPAM as a scanning/discovery **node**.
3. Keep phpIPAM in sync with the DHCP leases and ARP table exported from an **OPNsense** firewall.

---

## Requirements

| Component | Minimum version |
|-----------|----------------|
| Docker Engine | 20.10+ |
| Docker Compose | v2.x |
| phpIPAM | 1.6+ |
| OPNsense | 23.x+ |
| PHP CLI (for scan agent) | 8.1+ |

---

## Docker Compose

The following `docker-compose.yml` deploys phpIPAM together with a MariaDB database backend and the optional phpIPAM scan agent.

```yaml
version: "3.9"

services:

  phpipam-db:
    image: mariadb:10.11
    container_name: phpipam-db
    restart: unless-stopped
    environment:
      MYSQL_ROOT_PASSWORD: "${DB_ROOT_PASSWORD}"
      MYSQL_DATABASE: phpipam
      MYSQL_USER: phpipam
      MYSQL_PASSWORD: "${DB_PASSWORD}"
    volumes:
      - phpipam-db:/var/lib/mysql
    networks:
      - phpipam

  phpipam-web:
    image: phpipam/phpipam-www:latest
    container_name: phpipam-web
    restart: unless-stopped
    depends_on:
      - phpipam-db
    environment:
      TZ: "Europe/Amsterdam"
      IPAM_DATABASE_HOST: phpipam-db
      IPAM_DATABASE_USER: phpipam
      IPAM_DATABASE_PASS: "${DB_PASSWORD}"
      IPAM_DATABASE_NAME: phpipam
    ports:
      - "80:80"
    networks:
      - phpipam

  phpipam-cron:
    image: phpipam/phpipam-cron:latest
    container_name: phpipam-cron
    restart: unless-stopped
    depends_on:
      - phpipam-db
    environment:
      TZ: "Europe/Amsterdam"
      IPAM_DATABASE_HOST: phpipam-db
      IPAM_DATABASE_USER: phpipam
      IPAM_DATABASE_PASS: "${DB_PASSWORD}"
      IPAM_DATABASE_NAME: phpipam
      SCAN_INTERVAL: "1h"
    networks:
      - phpipam

volumes:
  phpipam-db:

networks:
  phpipam:
    driver: bridge
```

### Environment variables

Create a `.env` file next to `docker-compose.yml`:

```dotenv
DB_ROOT_PASSWORD=changeme_root
DB_PASSWORD=changeme_phpipam
```

> **Security note:** Never commit the `.env` file to version control. Add it to `.gitignore`.

### Start the stack

```bash
docker compose up -d
```

phpIPAM is then available at `http://<host-ip>/`.  
Follow the web installer to complete the initial database setup.

---

## phpIPAM Node Configuration

A phpIPAM **scan agent** (node) offloads network discovery scans to an agent running close to the scanned subnets. The agent communicates with the phpIPAM API to report alive hosts.

### 1. Enable the API in phpIPAM

1. Log in as admin → **Administration → phpIPAM Settings**.
2. Set **API** to *Enabled*.
3. Navigate to **Administration → API** and create a new API key:
   - **App ID**: `scan_agent`
   - **App permissions**: *Read/Write*
   - **App security**: *SSL with App code token* (recommended) or *User token*.
4. Note the generated **App code** — it is used by the agent.

### 2. Create a Scan Agent entry

1. Navigate to **Administration → Scan agents → New agent**.
2. Fill in:
   - **Name**: descriptive label (e.g. `opnsense-agent`)
   - **Description**: optional
   - **Type**: *API*
3. Save and note the **Agent code** shown in the list.

### 3. Assign subnets to the agent

1. Open a subnet → **Edit subnet**.
2. Under **Scan agent**, select the agent created above.
3. Enable **Discover new hosts** and **Resolve DNS names** as needed.
4. Save.

### 4. Run the scan agent

The phpIPAM scan agent is shipped with the phpIPAM source. On the host running the agent:

```bash
# Install dependencies
composer install --working-dir=/path/to/phpipam

# Run the agent (replace <agent-code> with the code from step 2)
php /path/to/phpipam/functions/scripts/discoveryAgent.php \
    -a <agent-code> \
    -d
```

The agent can also run inside the `phpipam-cron` container (already included in the Compose file above) by mounting the agent configuration or setting the `SCAN_INTERVAL` environment variable.

---

## OPNsense → phpIPAM Sync Script

This section documents a shell/Python script that reads the DHCP leases and ARP table from an OPNsense firewall via its REST API and pushes the data into phpIPAM, keeping host records up to date automatically.

### How it works

```
OPNsense REST API
  └─ GET /api/dhcpv4/leases/searchLease   → active DHCP leases (IP + MAC + hostname)
  └─ GET /api/diagnostics/interface/getArp → ARP table (IP + MAC)
            │
            ▼
       Sync script
            │
            ▼
phpIPAM REST API
  └─ GET  /api/<app_id>/addresses/search/<ip>/  → check if address exists
  └─ POST /api/<app_id>/addresses/              → create new address record
  └─ PUT  /api/<app_id>/addresses/<id>/         → update existing record
```

### Prerequisites

- OPNsense API key with at least **read** access to `diagnostics` and `dhcpv4`.
- phpIPAM API key with **read/write** access.
- `curl` or `python3` with `requests` available on the machine running the script.

### OPNsense API credentials

In OPNsense:

1. Navigate to **System → Access → Users** and select (or create) an API user.
2. Click **+ Add API key** and download the `<key>.txt` file which contains:
   ```
   key=<API_KEY>
   secret=<API_SECRET>
   ```
3. Assign the user a role that grants read access to `diagnostics` and `dhcpv4`.

### phpIPAM API credentials

Use the App ID and App code created in the [phpIPAM Node Configuration](#phpipam-node-configuration) section, or create a dedicated one.

### Configuration

The script expects the following environment variables (or a configuration file):

| Variable | Description |
|----------|-------------|
| `OPNSENSE_HOST` | Hostname / IP of the OPNsense firewall |
| `OPNSENSE_KEY` | OPNsense API key |
| `OPNSENSE_SECRET` | OPNsense API secret |
| `OPNSENSE_VERIFY_SSL` | Verify OPNsense TLS certificate (`true` / `false` / path to CA bundle). Default: `true` |
| `PHPIPAM_HOST` | Hostname / IP of the phpIPAM instance |
| `PHPIPAM_SCHEME` | Protocol for phpIPAM (`https` or `http`). Default: `https` |
| `PHPIPAM_APP_ID` | phpIPAM API App ID |
| `PHPIPAM_APP_CODE` | phpIPAM API App code (token) |
| `PHPIPAM_SUBNET_ID` | phpIPAM subnet ID to synchronise hosts into |

### Sync logic (pseudo-code)

```
1. Authenticate to phpIPAM → obtain bearer token
2. Fetch DHCP leases from OPNsense
3. Fetch ARP table from OPNsense
4. Merge both sources (prefer DHCP hostname over ARP-only entries)
5. For each host record (ip, mac, hostname):
   a. Query phpIPAM for existing address in the target subnet
   b. If NOT found → create a new address record
   c. If found AND data differs → update the existing record
   d. If found AND data is identical → skip (no-op)
6. Optionally: mark addresses not present in OPNsense data as offline/inactive
```

### Running the sync

```bash
# One-shot sync
OPNSENSE_HOST=192.168.1.1 \
OPNSENSE_KEY=<key> \
OPNSENSE_SECRET=<secret> \
PHPIPAM_HOST=192.168.1.10 \
PHPIPAM_APP_ID=sync_agent \
PHPIPAM_APP_CODE=<app_code> \
PHPIPAM_SUBNET_ID=3 \
python3 opnsense_phpipam_sync.py

# Schedule via cron (every 5 minutes)
*/5 * * * * /usr/bin/env bash -c 'source /etc/phpipam-sync.env && python3 /opt/phpipam/opnsense_phpipam_sync.py' >> /var/log/phpipam-sync.log 2>&1
```

### phpIPAM API endpoints used

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/api/{app_id}/user/` | Obtain auth token |
| `GET` | `/api/{app_id}/subnets/{subnet_id}/addresses/` | List existing addresses |
| `POST` | `/api/{app_id}/addresses/` | Create address |
| `PUT` | `/api/{app_id}/addresses/{id}/` | Update address |
| `DELETE` | `/api/{app_id}/addresses/{id}/` | Remove stale address (optional) |

### OPNsense API endpoints used

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/api/dhcpv4/leases/searchLease` | Fetch active DHCPv4 leases |
| `GET` | `/api/diagnostics/interface/getArp` | Fetch ARP table |

---

## License

This project is licensed under the [MIT License](LICENSE).
