"""Sync OPNsense DHCP leases and ARP table into phpIPAM."""

import logging
import os
import sys

import requests
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def get_env(name: str) -> str:
    """Return the value of a required environment variable."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise EnvironmentError(f"Required environment variable '{name}' is not set.")
    return value


def load_config() -> dict:
    """Load configuration from environment variables."""
    verify_ssl_raw = os.environ.get("OPNSENSE_VERIFY_SSL", "true").strip().lower()
    verify_ssl: bool | str = verify_ssl_raw not in ("false", "0", "no")
    # Allow a path to a CA bundle instead of a boolean
    if verify_ssl and os.path.isfile(verify_ssl_raw):
        verify_ssl = verify_ssl_raw

    phpipam_scheme = os.environ.get("PHPIPAM_SCHEME", "https").strip().lower()
    if phpipam_scheme not in ("http", "https"):
        raise ValueError("PHPIPAM_SCHEME must be 'http' or 'https'.")

    return {
        "opnsense_host": get_env("OPNSENSE_HOST"),
        "opnsense_key": get_env("OPNSENSE_KEY"),
        "opnsense_secret": get_env("OPNSENSE_SECRET"),
        "opnsense_verify_ssl": verify_ssl,
        "phpipam_host": get_env("PHPIPAM_HOST"),
        "phpipam_scheme": phpipam_scheme,
        "phpipam_app_id": get_env("PHPIPAM_APP_ID"),
        "phpipam_app_code": get_env("PHPIPAM_APP_CODE"),
        "phpipam_subnet_id": get_env("PHPIPAM_SUBNET_ID"),
    }


# ---------------------------------------------------------------------------
# OPNsense helpers
# ---------------------------------------------------------------------------

def fetch_dhcp_leases(
    host: str, key: str, secret: str, session: requests.Session, verify: bool | str = True
) -> list:
    """Return active DHCPv4 leases from OPNsense."""
    url = f"https://{host}/api/dhcpv4/leases/searchLease"
    response = session.get(url, auth=HTTPBasicAuth(key, secret), verify=verify, timeout=10)
    response.raise_for_status()
    data = response.json()
    return data.get("rows", [])


def fetch_arp_table(
    host: str, key: str, secret: str, session: requests.Session, verify: bool | str = True
) -> list:
    """Return the ARP table from OPNsense."""
    url = f"https://{host}/api/diagnostics/interface/getArp"
    response = session.get(url, auth=HTTPBasicAuth(key, secret), verify=verify, timeout=10)
    response.raise_for_status()
    return response.json() if isinstance(response.json(), list) else []


def merge_sources(leases: list, arp_entries: list) -> dict:
    """
    Merge DHCP leases and ARP table into a single dict keyed by IP address.

    DHCP lease data takes precedence over ARP-only entries.
    """
    hosts: dict = {}

    for entry in arp_entries:
        ip = (entry.get("ip") or "").strip()
        mac = (entry.get("mac") or "").strip()
        if ip:
            hosts[ip] = {"ip": ip, "mac": mac, "hostname": ""}

    for lease in leases:
        ip = (lease.get("address") or "").strip()
        mac = (lease.get("mac") or "").strip()
        hostname = (lease.get("hostname") or "").strip()
        if ip:
            hosts[ip] = {"ip": ip, "mac": mac, "hostname": hostname}

    return hosts


# ---------------------------------------------------------------------------
# phpIPAM helpers
# ---------------------------------------------------------------------------

def phpipam_authenticate(
    host: str, app_id: str, app_code: str, session: requests.Session, scheme: str = "https"
) -> str:
    """Obtain a phpIPAM bearer token and return it."""
    url = f"{scheme}://{host}/api/{app_id}/user/"
    response = session.post(url, auth=HTTPBasicAuth(app_id, app_code), timeout=10)
    response.raise_for_status()
    data = response.json()
    token = data.get("data", {}).get("token")
    if not token:
        raise RuntimeError("phpIPAM authentication failed: no token in response.")
    return token


def get_subnet_addresses(
    host: str, app_id: str, subnet_id: str, token: str, session: requests.Session, scheme: str = "https"
) -> dict:
    """Return existing phpIPAM addresses in *subnet_id* keyed by IP."""
    url = f"{scheme}://{host}/api/{app_id}/subnets/{subnet_id}/addresses/"
    headers = {"phpipam-token": token}
    response = session.get(url, headers=headers, timeout=10)
    if response.status_code == 404:
        return {}
    response.raise_for_status()
    data = response.json()
    addresses = data.get("data") or []
    return {addr["ip"]: addr for addr in addresses if addr.get("ip")}


def create_address(
    host: str,
    app_id: str,
    subnet_id: str,
    host_info: dict,
    token: str,
    session: requests.Session,
    scheme: str = "https",
) -> None:
    """Create a new address record in phpIPAM."""
    url = f"{scheme}://{host}/api/{app_id}/addresses/"
    headers = {"phpipam-token": token}
    payload = {
        "subnetId": subnet_id,
        "ip": host_info["ip"],
        "mac": host_info["mac"],
        "hostname": host_info["hostname"],
    }
    response = session.post(url, json=payload, headers=headers, timeout=10)
    response.raise_for_status()
    logger.info("Created address %s (%s)", host_info["ip"], host_info["hostname"])


def update_address(
    host: str,
    app_id: str,
    address_id: str,
    host_info: dict,
    token: str,
    session: requests.Session,
    scheme: str = "https",
) -> None:
    """Update an existing address record in phpIPAM."""
    url = f"{scheme}://{host}/api/{app_id}/addresses/{address_id}/"
    headers = {"phpipam-token": token}
    payload = {
        "mac": host_info["mac"],
        "hostname": host_info["hostname"],
    }
    response = session.put(url, json=payload, headers=headers, timeout=10)
    response.raise_for_status()
    logger.info("Updated address %s (%s)", host_info["ip"], host_info["hostname"])


# ---------------------------------------------------------------------------
# Sync logic
# ---------------------------------------------------------------------------

def sync(config: dict, session: requests.Session | None = None) -> dict:
    """
    Run a full OPNsense → phpIPAM sync.

    Returns a summary dict with keys 'created', 'updated', 'skipped'.
    """
    if session is None:
        session = requests.Session()

    summary = {"created": 0, "updated": 0, "skipped": 0}

    # Fetch data from OPNsense
    verify_ssl = config.get("opnsense_verify_ssl", True)
    leases = fetch_dhcp_leases(
        config["opnsense_host"], config["opnsense_key"], config["opnsense_secret"], session, verify=verify_ssl
    )
    arp = fetch_arp_table(
        config["opnsense_host"], config["opnsense_key"], config["opnsense_secret"], session, verify=verify_ssl
    )
    hosts = merge_sources(leases, arp)
    logger.info("Discovered %d host(s) from OPNsense.", len(hosts))

    scheme = config.get("phpipam_scheme", "https")

    # Authenticate to phpIPAM
    token = phpipam_authenticate(
        config["phpipam_host"], config["phpipam_app_id"], config["phpipam_app_code"], session, scheme=scheme
    )

    # Fetch existing phpIPAM addresses
    existing = get_subnet_addresses(
        config["phpipam_host"], config["phpipam_app_id"], config["phpipam_subnet_id"], token, session,
        scheme=scheme,
    )

    # Synchronise
    for ip, host_info in hosts.items():
        if ip not in existing:
            create_address(
                config["phpipam_host"],
                config["phpipam_app_id"],
                config["phpipam_subnet_id"],
                host_info,
                token,
                session,
                scheme=scheme,
            )
            summary["created"] += 1
        else:
            current = existing[ip]
            if current.get("mac") != host_info["mac"] or current.get("hostname") != host_info["hostname"]:
                update_address(
                    config["phpipam_host"],
                    config["phpipam_app_id"],
                    current["id"],
                    host_info,
                    token,
                    session,
                    scheme=scheme,
                )
                summary["updated"] += 1
            else:
                summary["skipped"] += 1

    logger.info(
        "Sync complete: %d created, %d updated, %d skipped.",
        summary["created"],
        summary["updated"],
        summary["skipped"],
    )
    return summary


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        config = load_config()
    except EnvironmentError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    sync(config)


if __name__ == "__main__":
    main()
