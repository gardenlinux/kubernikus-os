#!/usr/bin/env python3

import os
import pathlib
import re
from yaml import load, dump
try:
    from yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    from yaml import Loader, Dumper


INPUT_PATH="/etc/netplan/50-cloud-init.yaml"
OUTPUT_PATH="/etc/netplan/50-cloud-init-derived.yaml"

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
  interfaces = network.get("bonds") or network.get("ethernets")

  if not interfaces:
    return

  primary_name, primary = next(iter(interfaces.items()))

  network["openvswitch"] = {}
  bridges = network.setdefault("bridges", {})
  br_ex = {
    "interfaces": [primary_name],
    "openvswitch": {},
  }

  for key in ["addresses", "routes", "dhcp4"]:
    val = primary.pop(key, None)
    if val:
      br_ex[key] = val

  if not br_ex.get("dhcp4", None):
    br_ex["nameservers"] = {
      "addresses": ["147.204.9.200", "147.204.9.201"]
    }

  bridges["br-ex"] = br_ex

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
  hugepages=0
  if m:
    hugepages=int(m[1])
  else:
    hugepages=int(pathlib.Path("/proc/sys/vm/nr_hugepages").read_text())

  if hugepages<=0:
    return

  cfg.write_text(f'CMDLINE_LINUX="$CMDLINE_LINUX hugepages={hugepages}"\n')

  for entry in pathlib.Path("/efi/loader/entries").glob("*.conf"):
    old = entry.read_text()
    new = re.sub(r"^options.*", f"\\g<0> hugepages={hugepages}", old, flags=re.M)
    entry.write_text(new)

setup_ovs()
setup_memory()
