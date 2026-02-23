"""Unit tests for opnsense_phpipam_sync."""

import pytest
import responses as resp_mock
import requests

import opnsense_phpipam_sync as sync_module


# ---------------------------------------------------------------------------
# load_config / get_env
# ---------------------------------------------------------------------------

class TestGetEnv:
    def test_returns_value_when_set(self, monkeypatch):
        monkeypatch.setenv("SOME_VAR", "hello")
        assert sync_module.get_env("SOME_VAR") == "hello"

    def test_raises_when_missing(self, monkeypatch):
        monkeypatch.delenv("SOME_VAR", raising=False)
        with pytest.raises(EnvironmentError, match="SOME_VAR"):
            sync_module.get_env("SOME_VAR")

    def test_raises_when_empty(self, monkeypatch):
        monkeypatch.setenv("SOME_VAR", "   ")
        with pytest.raises(EnvironmentError, match="SOME_VAR"):
            sync_module.get_env("SOME_VAR")


class TestLoadConfig:
    REQUIRED_VARS = {
        "OPNSENSE_HOST": "fw.example.com",
        "OPNSENSE_KEY": "key123",
        "OPNSENSE_SECRET": "secret123",
        "PHPIPAM_HOST": "ipam.example.com",
        "PHPIPAM_APP_ID": "sync_agent",
        "PHPIPAM_APP_CODE": "app_code_abc",
        "PHPIPAM_SUBNET_ID": "3",
    }

    def test_loads_all_keys(self, monkeypatch):
        for k, v in self.REQUIRED_VARS.items():
            monkeypatch.setenv(k, v)
        cfg = sync_module.load_config()
        assert cfg["opnsense_host"] == "fw.example.com"
        assert cfg["phpipam_subnet_id"] == "3"

    def test_raises_if_key_missing(self, monkeypatch):
        for k, v in self.REQUIRED_VARS.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("OPNSENSE_KEY")
        with pytest.raises(EnvironmentError):
            sync_module.load_config()


# ---------------------------------------------------------------------------
# merge_sources
# ---------------------------------------------------------------------------

class TestMergeSources:
    def test_dhcp_takes_precedence_over_arp(self):
        leases = [{"address": "10.0.0.1", "mac": "aa:bb:cc:dd:ee:ff", "hostname": "myhost"}]
        arp = [{"ip": "10.0.0.1", "mac": "11:22:33:44:55:66"}]
        result = sync_module.merge_sources(leases, arp)
        assert result["10.0.0.1"]["hostname"] == "myhost"
        assert result["10.0.0.1"]["mac"] == "aa:bb:cc:dd:ee:ff"

    def test_arp_only_entry_added(self):
        leases = []
        arp = [{"ip": "10.0.0.2", "mac": "de:ad:be:ef:00:01"}]
        result = sync_module.merge_sources(leases, arp)
        assert "10.0.0.2" in result
        assert result["10.0.0.2"]["hostname"] == ""

    def test_empty_inputs(self):
        assert sync_module.merge_sources([], []) == {}

    def test_skips_entries_without_ip(self):
        leases = [{"address": "", "mac": "aa:bb:cc:dd:ee:ff", "hostname": "noip"}]
        arp = [{"ip": None, "mac": "11:22:33:44:55:66"}]
        result = sync_module.merge_sources(leases, arp)
        assert result == {}

    def test_multiple_hosts(self):
        leases = [
            {"address": "192.168.1.10", "mac": "aa:aa:aa:aa:aa:aa", "hostname": "alpha"},
            {"address": "192.168.1.11", "mac": "bb:bb:bb:bb:bb:bb", "hostname": "beta"},
        ]
        arp = [{"ip": "192.168.1.12", "mac": "cc:cc:cc:cc:cc:cc"}]
        result = sync_module.merge_sources(leases, arp)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# OPNsense API helpers
# ---------------------------------------------------------------------------

class TestFetchDhcpLeases:
    @resp_mock.activate
    def test_returns_rows(self):
        resp_mock.add(
            resp_mock.GET,
            "https://fw.example.com/api/dhcpv4/leases/searchLease",
            json={"rows": [{"address": "10.0.0.5", "mac": "aa:bb:cc:dd:ee:01", "hostname": "h1"}]},
            status=200,
        )
        session = requests.Session()
        result = sync_module.fetch_dhcp_leases("fw.example.com", "key", "secret", session)
        assert len(result) == 1
        assert result[0]["address"] == "10.0.0.5"

    @resp_mock.activate
    def test_raises_on_http_error(self):
        resp_mock.add(
            resp_mock.GET,
            "https://fw.example.com/api/dhcpv4/leases/searchLease",
            status=401,
        )
        session = requests.Session()
        with pytest.raises(requests.HTTPError):
            sync_module.fetch_dhcp_leases("fw.example.com", "bad_key", "bad_secret", session)


class TestFetchArpTable:
    @resp_mock.activate
    def test_returns_list(self):
        resp_mock.add(
            resp_mock.GET,
            "https://fw.example.com/api/diagnostics/interface/getArp",
            json=[{"ip": "10.0.0.1", "mac": "aa:bb:cc:dd:ee:ff"}],
            status=200,
        )
        session = requests.Session()
        result = sync_module.fetch_arp_table("fw.example.com", "key", "secret", session)
        assert result[0]["ip"] == "10.0.0.1"

    @resp_mock.activate
    def test_non_list_response_returns_empty(self):
        resp_mock.add(
            resp_mock.GET,
            "https://fw.example.com/api/diagnostics/interface/getArp",
            json={"error": "not a list"},
            status=200,
        )
        session = requests.Session()
        result = sync_module.fetch_arp_table("fw.example.com", "key", "secret", session)
        assert result == []


# ---------------------------------------------------------------------------
# phpIPAM API helpers
# ---------------------------------------------------------------------------

class TestPhpipamAuthenticate:
    @resp_mock.activate
    def test_returns_token(self):
        resp_mock.add(
            resp_mock.POST,
            "https://ipam.example.com/api/sync_agent/user/",
            json={"data": {"token": "tok_abc123"}},
            status=200,
        )
        session = requests.Session()
        token = sync_module.phpipam_authenticate("ipam.example.com", "sync_agent", "code", session)
        assert token == "tok_abc123"

    @resp_mock.activate
    def test_raises_when_no_token(self):
        resp_mock.add(
            resp_mock.POST,
            "https://ipam.example.com/api/sync_agent/user/",
            json={"data": {}},
            status=200,
        )
        session = requests.Session()
        with pytest.raises(RuntimeError, match="authentication failed"):
            sync_module.phpipam_authenticate("ipam.example.com", "sync_agent", "code", session)


class TestGetSubnetAddresses:
    @resp_mock.activate
    def test_returns_dict_keyed_by_ip(self):
        resp_mock.add(
            resp_mock.GET,
            "https://ipam.example.com/api/sync_agent/subnets/3/addresses/",
            json={"data": [{"id": "1", "ip": "10.0.0.1", "mac": "aa:bb:cc:dd:ee:ff", "hostname": "h1"}]},
            status=200,
        )
        session = requests.Session()
        result = sync_module.get_subnet_addresses("ipam.example.com", "sync_agent", "3", "tok", session)
        assert "10.0.0.1" in result
        assert result["10.0.0.1"]["id"] == "1"

    @resp_mock.activate
    def test_returns_empty_on_404(self):
        resp_mock.add(
            resp_mock.GET,
            "https://ipam.example.com/api/sync_agent/subnets/99/addresses/",
            status=404,
        )
        session = requests.Session()
        result = sync_module.get_subnet_addresses("ipam.example.com", "sync_agent", "99", "tok", session)
        assert result == {}


# ---------------------------------------------------------------------------
# Full sync
# ---------------------------------------------------------------------------

class TestSync:
    CONFIG = {
        "opnsense_host": "fw.example.com",
        "opnsense_key": "key",
        "opnsense_secret": "secret",
        "phpipam_host": "ipam.example.com",
        "phpipam_app_id": "sync_agent",
        "phpipam_app_code": "code",
        "phpipam_subnet_id": "3",
    }

    @resp_mock.activate
    def test_creates_new_address(self):
        # OPNsense endpoints
        resp_mock.add(resp_mock.GET,
                      "https://fw.example.com/api/dhcpv4/leases/searchLease",
                      json={"rows": [{"address": "10.0.0.50", "mac": "aa:aa:aa:aa:aa:aa", "hostname": "newhost"}]})
        resp_mock.add(resp_mock.GET,
                      "https://fw.example.com/api/diagnostics/interface/getArp",
                      json=[])
        # phpIPAM auth
        resp_mock.add(resp_mock.POST,
                      "https://ipam.example.com/api/sync_agent/user/",
                      json={"data": {"token": "tok"}})
        # existing addresses (empty subnet)
        resp_mock.add(resp_mock.GET,
                      "https://ipam.example.com/api/sync_agent/subnets/3/addresses/",
                      json={"data": []})
        # create call
        resp_mock.add(resp_mock.POST,
                      "https://ipam.example.com/api/sync_agent/addresses/",
                      json={"id": "10"}, status=201)

        summary = sync_module.sync(self.CONFIG, session=requests.Session())
        assert summary["created"] == 1
        assert summary["updated"] == 0
        assert summary["skipped"] == 0

    @resp_mock.activate
    def test_updates_changed_address(self):
        resp_mock.add(resp_mock.GET,
                      "https://fw.example.com/api/dhcpv4/leases/searchLease",
                      json={"rows": [{"address": "10.0.0.50", "mac": "bb:bb:bb:bb:bb:bb", "hostname": "renamed"}]})
        resp_mock.add(resp_mock.GET,
                      "https://fw.example.com/api/diagnostics/interface/getArp",
                      json=[])
        resp_mock.add(resp_mock.POST,
                      "https://ipam.example.com/api/sync_agent/user/",
                      json={"data": {"token": "tok"}})
        resp_mock.add(resp_mock.GET,
                      "https://ipam.example.com/api/sync_agent/subnets/3/addresses/",
                      json={"data": [
                          {"id": "5", "ip": "10.0.0.50", "mac": "aa:aa:aa:aa:aa:aa", "hostname": "oldname"}
                      ]})
        resp_mock.add(resp_mock.PUT,
                      "https://ipam.example.com/api/sync_agent/addresses/5/",
                      json={"success": True})

        summary = sync_module.sync(self.CONFIG, session=requests.Session())
        assert summary["updated"] == 1
        assert summary["created"] == 0

    @resp_mock.activate
    def test_skips_unchanged_address(self):
        resp_mock.add(resp_mock.GET,
                      "https://fw.example.com/api/dhcpv4/leases/searchLease",
                      json={"rows": [{"address": "10.0.0.50", "mac": "aa:aa:aa:aa:aa:aa", "hostname": "same"}]})
        resp_mock.add(resp_mock.GET,
                      "https://fw.example.com/api/diagnostics/interface/getArp",
                      json=[])
        resp_mock.add(resp_mock.POST,
                      "https://ipam.example.com/api/sync_agent/user/",
                      json={"data": {"token": "tok"}})
        resp_mock.add(resp_mock.GET,
                      "https://ipam.example.com/api/sync_agent/subnets/3/addresses/",
                      json={"data": [{"id": "5", "ip": "10.0.0.50", "mac": "aa:aa:aa:aa:aa:aa", "hostname": "same"}]})

        summary = sync_module.sync(self.CONFIG, session=requests.Session())
        assert summary["skipped"] == 1
        assert summary["created"] == 0
        assert summary["updated"] == 0
