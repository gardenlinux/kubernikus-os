#!/usr/bin/env python3

import ipaddress
import os
import pathlib
import platform
import re
import textwrap
import uuid

import requests
from yaml import dump, load

try:
    from yaml import CDumper as Dumper
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Dumper, Loader


INPUT_PATH = "/etc/netplan/50-cloud-init.yaml"
OUTPUT_PATH = "/etc/netplan/50-cloud-init-derived.yaml"

DEFAULT_NAMESERVERS = {"addresses": ["147.204.9.200", "147.204.9.201"]}


def setup_ovs():
    try:
        with open(INPUT_PATH, "rt") as stream:
            data = load(stream, Loader=Loader)
    except FileNotFoundError:
        try:
            with open(INPUT_PATH + ".old", "rt") as stream:
                data = load(stream, Loader=Loader)
        except FileNotFoundError:
            return

    network = data["network"]
    ethernets = network.get("ethernets")
    interfaces = network.get("bonds") or ethernets

    if not interfaces:
        return

    primary_name, primary = next(iter(interfaces.items()))

    vlans = network.get("vlans", {})
    network["vlans"] = vlans

    network["openvswitch"] = {}
    bridges = network.setdefault("bridges", {})
    br_ex = {
        "interfaces": [primary_name],
        "openvswitch": {},
    }

    for key in ["macaddress", "addresses", "routes", "dhcp4"]:
        val = primary.pop(key, None)
        if val:
            br_ex[key] = val

    if not br_ex.get("dhcp4", None):
        br_ex["nameservers"] = DEFAULT_NAMESERVERS
    bridges["br-ex"] = br_ex

    name, ip, vlan_id, aggregates = _get_netbox_config()

    if ip and vlan_id:
        ipif = ipaddress.ip_interface(ip)
        gateway = str(next(ipif.network.hosts()))
        if "ap" not in name:
            vlan_link = primary_name
        else:
            vlan_link = "bond1"
            netpath = pathlib.Path("/sys/class/net")
            new_ethernets = []
            for en in netpath.glob("en*/address"):
                name = en.parent.name
                if name not in ethernets:
                    new_ethernets.append(name)
                    macaddress = en.read_text().strip()
                    ethernets[name] = {
                        "match": {
                            "macaddress": macaddress,
                        },
                        "set-name": name,
                    }
            network.setdefault("bonds", {})["bond1"] = {
                "interfaces": new_ethernets,
                "mtu": 8950,
                "macaddress": macaddress,
                "parameters": {"mii-monitor-interval": 100, "mode": "802.3ad"},
            }
        vlans[f"{vlan_link}.{vlan_id}"] = {
            "id": vlan_id,
            "link": vlan_link,
            "addresses": [ip],
            "routes": [{"to": aggregate, "via": gateway} for aggregate in aggregates],
        }

    with open(OUTPUT_PATH, "wt") as stream:
        dump(data, stream, Dumper=Dumper)
    os.chmod(OUTPUT_PATH, 0o600)

    try:
        os.replace(INPUT_PATH, INPUT_PATH + ".old")
    except FileNotFoundError:
        pass


def setup_memory():
    cfg = pathlib.Path("/etc/kernel/cmdline.d/50-hugepages.cfg")
    # Do not overwrite an existing config
    if cfg.exists():
        return

    cmdline = pathlib.Path("/proc/cmdline").read_text()
    m = re.search(r"hugepages=(\d+)", cmdline)
    hugepages = 0
    if m:
        hugepages = int(m[1])
    else:
        hugepages = int(pathlib.Path("/proc/sys/vm/nr_hugepages").read_text())

    if hugepages <= 0:
        return

    cfg.write_text(f'CMDLINE_LINUX="$CMDLINE_LINUX hugepages={hugepages}"\n')

    for entry in pathlib.Path("/efi/loader/entries").glob("*.conf"):
        old = entry.read_text()
        new = re.sub(r"^options.*", f"\\g<0> hugepages={hugepages}", old, flags=re.M)
        entry.write_text(new)


def _query_netbox(query):
    response = requests.post(
        "https://netbox.global.cloud.sap/graphql/",
        json={"query": textwrap.dedent(query)},
    )

    response.raise_for_status()
    return response.json()["data"]


def _get_netbox_config():
    node = platform.node().split(".", 1)[0]
    aggregates = ["10.245.0.0/16", "10.246.0.0/16", "10.247.0.0/16"]
    try:
        mac = uuid.getnode()

        data = _query_netbox(f"""
        {{
            interface_list(mac_address: "{mac:012x}") {{
                device {{
                    name
                    interfaces(name: "vmk0") {{
                        ip_addresses {{
                            address
                        }}
                    }}
                }}
            }}
        }}
        """)

        device = data["interface_list"][0]["device"]
        name = device["name"].split(".", 1)[0]
        ip = device["interfaces"][0]["ip_addresses"][0]["address"]

        data = _query_netbox(f"""
        {{
            prefix_list(contains: "{ip}") {{
                prefix
                vlan {{
                    vid
                }}
            }}
        }}
        """)

        item = data["prefix_list"][-1]["vlan"]
        return name, ip, item["vid"], aggregates
    except (IndexError, KeyError, requests.exceptions.ConnectionError) as e:
        return node, None, None, aggregates


setup_ovs()
setup_memory()
