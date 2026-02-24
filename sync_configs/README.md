# Sync Configurations

This directory contains individual configuration folders for each OPNsense server you want to sync with phpIPAM.

## Structure

Each subdirectory represents a separate OPNsense instance:

```
sync_configs/
├── opnsense1/          # Example: Main office firewall
│   ├── .env_sample     # Template configuration
│   └── .env            # Actual credentials (not in git)
├── opnsense2/          # Example: Branch office firewall
│   └── .env
└── datacenter-fw/      # Example: Datacenter firewall
    └── .env
```

## Setup

1. **Create a new configuration folder**:
   ```bash
   mkdir -p sync_configs/my-firewall
   ```

2. **Copy the sample configuration**:
   ```bash
   cp sync_configs/opnsense1/.env_sample sync_configs/my-firewall/.env
   ```

3. **Edit the configuration**:
   ```bash
   nano sync_configs/my-firewall/.env
   ```
   Update with your OPNsense and phpIPAM credentials.

4. **Run the sync**:
   ```bash
   ./scripts/sync_wrapper.sh sync_configs/my-firewall
   ```

## Running Multiple Syncs

To sync all configured firewalls, you can create a simple loop:

```bash
#!/bin/bash
for config_dir in sync_configs/*/; do
    if [ -f "$config_dir/.env" ]; then
        echo "Syncing $(basename $config_dir)..."
        ./scripts/sync_wrapper.sh "$config_dir"
    fi
done
```

Or use the provided batch script:

```bash
./scripts/sync_all.sh
```

## Cron Configuration

Add entries to your crontab for each firewall:

```cron
# Sync main office firewall every 5 minutes
*/5 * * * * /path/to/phpipam_config/scripts/sync_wrapper.sh /path/to/phpipam_config/sync_configs/opnsense1

# Sync branch office firewall every 15 minutes
*/15 * * * * /path/to/phpipam_config/scripts/sync_wrapper.sh /path/to/phpipam_config/sync_configs/opnsense2
```

## Log Files

By default, logs are stored in `/var/log/phpipam-sync/<config_name>.log`.

You can override this by setting `LOG_FILE` in your `.env` file:

```bash
LOG_FILE=/var/log/my-custom-location.log
```
