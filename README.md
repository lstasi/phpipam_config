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

The following `docker-compose.yml` (or `dockercompose.yaml`) deploys phpIPAM together with a MariaDB database backend, the phpIPAM scan agent, and a log rotation service for database logs.

```yaml
services:
  phpipam-web:
    image: phpipam/phpipam-www:latest
    container_name: phpipam-web
    ports:
      - "80:80"
    cap_add:
      - NET_RAW
      - NET_ADMIN
    environment:
      - TZ=Europe/London
      - IPAM_DATABASE_HOST=phpipam-db
      - IPAM_DATABASE_PORT=3306
      - IPAM_DATABASE_NAME=phpipam
      - IPAM_DATABASE_USER=phpipam
      - IPAM_DATABASE_PASS=${DB_PASSWORD}
    volumes:
      - phpipam-logo:/phpipam/css/images/logo
      - phpipam-ca:/usr/local/share/ca-certificates
    depends_on:
      phpipam-db:
        condition: service_healthy
    restart: unless-stopped
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"
    networks:
      - phpipam-net

  phpipam-cron:
    image: phpipam/phpipam-cron:latest
    container_name: phpipam-cron
    cap_add:
      - NET_RAW
      - NET_ADMIN
    environment:
      - TZ=Europe/London
      - IPAM_DATABASE_HOST=phpipam-db
      - IPAM_DATABASE_PORT=3306
      - IPAM_DATABASE_NAME=phpipam
      - IPAM_DATABASE_USER=phpipam
      - IPAM_DATABASE_PASS=${DB_PASSWORD}
      - SCAN_INTERVAL=1h
    volumes:
      - phpipam-ca:/usr/local/share/ca-certificates
    depends_on:
      phpipam-db:
        condition: service_healthy
    restart: unless-stopped
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"
    networks:
      - phpipam-net

  phpipam-db:
    image: mariadb:latest
    container_name: phpipam-db
    environment:
      - MYSQL_ROOT_PASSWORD=${DB_ROOT_PASSWORD}
      - MYSQL_DATABASE=phpipam
      - MYSQL_USER=phpipam
      - MYSQL_PASSWORD=${DB_PASSWORD}
    volumes:
      - phpipam-db:/var/lib/mysql
      - phpipam-logs:/var/log/mysql
    healthcheck:
      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 30s
    restart: unless-stopped
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"
    networks:
      - phpipam-net

  logrotate:
    image: blacklabelops/logrotate:latest
    container_name: phpipam-logrotate
    environment:
      - TZ=Europe/London
      - LOGS_DIRECTORIES=/var/log/mysql
      - LOGROTATE_SIZE=10M
      - LOGROTATE_ROTATE=5
      - LOGROTATE_COMPRESSION=compress
      - LOGROTATE_INTERVAL=daily
      - LOGROTATE_DATEFORMAT=-%Y%m%d
    volumes:
      - phpipam-logs:/var/log/mysql
    restart: unless-stopped
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"
    networks:
      - phpipam-net

volumes:
  phpipam-db:
  phpipam-logo:
  phpipam-ca:
  phpipam-logs:

networks:
  phpipam-net:
    driver: bridge
```

### Environment variables

Create a `.env` file next to `dockercompose.yaml`:

```dotenv
DB_ROOT_PASSWORD=your_root_password_here
DB_PASSWORD=your_phpipam_password_here
```

Alternatively, copy the provided `.env_sample` file:

```bash
cp .env_sample .env
# Edit .env and set your passwords
```

> **Security note:** Never commit the `.env` file to version control. It is already included in `.gitignore`.

### Start the stack

```bash
docker compose up -d
```

phpIPAM is then available at `http://<host-ip>/`.
Follow the web installer to complete the initial database setup.

### Notable Features

- **Health Checks**: The database service includes a health check to ensure it's ready before dependent services start
- **Network Capabilities**: `NET_RAW` and `NET_ADMIN` capabilities are added to enable network scanning features
- **Log Management**: Integrated log rotation service to manage database logs automatically
- **Persistent Volumes**: Separate volumes for database data, logs, custom logos, and CA certificates
- **Resource Limits**: JSON logging configured with size and rotation limits to prevent disk space issues

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

- **OPNsense API user** with minimum required privileges:
  - `Diagnostics: Interface: ARP Table` (read-only)
  - `Services: DHCPv4: Leases` (read-only)
- **phpIPAM API application** with **Read/Write** permissions
- Python 3.8+ with the `requests` library installed on the machine running the script:
  ```bash
  pip3 install -r requirements.txt
  ```

### OPNsense API credentials

In OPNsense:

1. **Create a dedicated user** (recommended):
   - Navigate to **System → Access → Users**
   - Click **+ Add** to create a new user (e.g., `phpipam_sync`)
   - Set a strong password (required even though API key will be used)
   - Leave shell access disabled

2. **Create a custom group with minimum permissions**:
   - Navigate to **System → Access → Groups**
   - Click **+ Add** to create a new group (e.g., `PHPIPAM_API`)
   - Under **Assigned Privileges**, add only these **two** required privileges:
     - `Diagnostics: Interface: ARP Table` - for fetching the ARP table
     - `Services: DHCPv4: Leases` - for fetching DHCP lease information
   - Save the group

3. **Assign the user to the group**:
   - Go back to **System → Access → Users** and edit the user created in step 1
   - In the **Group Membership** section, add the user to the `PHPIPAM_API` group
   - Save

4. **Generate API credentials**:
   - While still editing the user, scroll to **API keys**
   - Click **+ Add API key**
   - Download the generated `<key>.txt` file which contains:
     ```
     key=<API_KEY>
     secret=<API_SECRET>
     ```
   - Store these securely - the secret cannot be retrieved later

> **Security note**: These are the **minimum required permissions**. The user has read-only access to only DHCP leases and the ARP table, following the principle of least privilege.

### phpIPAM API credentials

In phpIPAM:

1. **Enable the API**:
   - Log in as admin → **Administration → phpIPAM Settings**
   - Find the **API** section and set it to **Enabled**
   - Save changes

2. **Create a dedicated API application**:
   - Navigate to **Administration → API**
   - Click **Create API key**
   - Configure the API application:
     - **App ID**: `opnsense_sync` (or your preferred identifier)
     - **App permissions**: **Read/Write** (required to create and update address records)
     - **App security**:
       - **SSL with App code token** (recommended for production)
       - or **App code token** (for testing or internal networks)
     - **Description**: "OPNsense DHCP/ARP sync"
   - Click **Add**
   - Copy the generated **App code** - this is your `PHPIPAM_APP_CODE`

3. **Note the required API permissions**:
   - The sync script requires **Read/Write** access to perform these operations:
     - `GET /api/{app_id}/subnets/{subnet_id}/addresses/` - read existing addresses
     - `POST /api/{app_id}/addresses/` - create new address records
     - `PUT /api/{app_id}/addresses/{id}/` - update existing records

> **Note**: The App ID and App code can be reused from the [phpIPAM Node Configuration](#phpipam-node-configuration) section if you've already created one, or you can create a dedicated API application specifically for the sync script.

### Configuration

The script expects the following environment variables:

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `OPNSENSE_HOST` | Hostname / IP of the OPNsense firewall | Yes | - |
| `OPNSENSE_KEY` | OPNsense API key | Yes | - |
| `OPNSENSE_SECRET` | OPNsense API secret | Yes | - |
| `OPNSENSE_VERIFY_SSL` | Verify OPNsense TLS certificate (`true` / `false` / path to CA bundle) | No | `true` |
| `PHPIPAM_HOST` | Hostname / IP of the phpIPAM instance | Yes | - |
| `PHPIPAM_SCHEME` | Protocol for phpIPAM (`https` or `http`) | No | `https` |
| `PHPIPAM_APP_ID` | phpIPAM API App ID | Yes | - |
| `PHPIPAM_APP_CODE` | phpIPAM API App code (token) | Yes | - |
| `PHPIPAM_SUBNET_ID` | phpIPAM subnet ID to synchronise hosts into | Yes | - |

You can configure these variables in the `.env` file alongside the database credentials. The `.env_sample` file includes templates for all required variables.

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
# Using the .env file (recommended)
set -a
source .env
set +a
python3 opnsense_phpipam_sync.py

# Or with inline environment variables
OPNSENSE_HOST=192.168.1.1 \
OPNSENSE_KEY=<key> \
OPNSENSE_SECRET=<secret> \
PHPIPAM_HOST=192.168.1.10 \
PHPIPAM_APP_ID=sync_agent \
PHPIPAM_APP_CODE=<app_code> \
PHPIPAM_SUBNET_ID=3 \
python3 opnsense_phpipam_sync.py

# Schedule via cron (every 5 minutes)
*/5 * * * * /usr/bin/env bash -c 'cd /path/to/phpipam_config && set -a && source .env && set +a && python3 opnsense_phpipam_sync.py' >> /var/log/phpipam-sync.log 2>&1
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
