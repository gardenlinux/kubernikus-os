#!/bin/bash
# This file is part of dracut ensure-hugepages module.
# SPDX-License-Identifier: MIT

hugepages=$(getarg hugepages=) || hugepages=0

if [ $hugepages -gt 0 ]; then
  exit 0
fi

non_hugepages_mb=$(getarg rd.non_hugepages_mb=) || non_hugepages_mb=32768

mem_total_mb=$(($(sed -rn 's/MemTotal:\s+(.*) kB/\1/p' /proc/meminfo) / 1024 ))
hugepagesize_mb=$(($(sed -rn 's/Hugepagesize:\s+(.*) kB/\1/p' /proc/meminfo) / 1024 ))
nr_hugepages=$((($mem_total_mb - $non_hugepages_mb) / $hugepagesize_mb))

if [ $nr_hugepages -le 0 ]; then
  exit 0
fi

cmdline="$(</proc/cmdline) hugepages=$nr_hugepages"
release=$(uname -r)

NEWROOT=${NEWROOT:-/sysroot}

kexec \
  -l $NEWROOT/boot/vmlinuz-${release} \
  --initrd=$NEWROOT/boot/initrd.img-${release} \
  --command-line="$cmdline"

kexec -e --reset-vga
