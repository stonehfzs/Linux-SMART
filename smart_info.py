#!/usr/bin/env python3
"""smart_info.py - simple SMART information viewer using smartctl

Usage:
  python smart_info.py --list
  python smart_info.py --device /dev/sda --json

This script shells out to `smartctl` (from smartmontools). It parses
common parts of the output into JSON. It's designed to be simple and
work for typical SATA and NVMe outputs.
"""
import argparse
import json
import shutil
import subprocess
import sys
from typing import Dict, List, Optional


def find_smartctl() -> Optional[str]:
    return shutil.which("smartctl")


def list_devices(smartctl: str) -> List[str]:
    # Use smartctl --scan to list devices
    try:
        p = subprocess.run([smartctl, "--scan"], capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"smartctl --scan failed: {e.stderr or e}")
    devices = []
    for line in p.stdout.splitlines():
        # lines like: /dev/sda -d sat # /dev/sda, ATA device
        parts = line.split()
        if parts:
            devices.append(parts[0])
    return devices


def run_smartctl(smartctl: str, device: str) -> str:
    try:
        p = subprocess.run([smartctl, "-a", device], capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        # smartctl returns non-zero for some drives - capture stdout/stderr anyway
        out = (e.stdout or "") + "\n" + (e.stderr or "")
        return out
    return p.stdout


def parse_smart_output(output: str) -> Dict:
    # Very small parser for key fields and Attribute table
    data: Dict = {}
    lines = output.splitlines()
    attrs: List[Dict] = []
    in_attr_table = False
    attr_headers = None
    in_nvme_health = False
    nvme_section_lines: List[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("=== START OF INFORMATION SECTION ==="):
            continue
        if line.startswith("Device Model:") or line.startswith("Model Number:"):
            data["model"] = line.split(":", 1)[1].strip()
        elif line.startswith("Serial Number:"):
            data["serial"] = line.split(":", 1)[1].strip()
        elif line.startswith("Firmware Version:"):
            data["firmware"] = line.split(":", 1)[1].strip()
        elif line.startswith("SMART overall-health self-assessment test result:"):
            data["health"] = line.split(":", 1)[1].strip()
        elif line.startswith("SMART overall-health self-assessment test result"):
            data.setdefault("notes", []).append(line)
        elif line.startswith("Percentage Used:"):
            data["percentage_used"] = line.split(":", 1)[1].strip()
        # NVMe: "Model Number: Samsung SSD 970 EVO Plus 1TB" handled above
        # NVMe health critical warning
        elif line.startswith("critical_warning"):
            data.setdefault("nvme_health", {})["critical_warning"] = line.split(":", 1)[1].strip()

        # detect start of NVMe SMART/Health Information
        if line.startswith("SMART/Health Information"):
            in_nvme_health = True
            nvme_section_lines = []
            continue
        if in_nvme_health:
            # NVMe SMART/Health section ends when an empty line or another section starts
            if line.startswith("Error Information") or line.startswith("Self-test Log") or line.startswith("==="):
                in_nvme_health = False
            else:
                nvme_section_lines.append(line)

        # Attribute table detection (ATA)
        if line.startswith("ID#") and "ATTRIBUTE_NAME" in line or line.startswith("ID#") and "ATTRIBUTE_NAME" not in line and "FLAG" in line:
            in_attr_table = True
            attr_headers = line
            continue
        if in_attr_table:
            # table rows normally start with a number
            if line[0].isdigit():
                parts = line.split()
                # Typical ATA: ID, ATTRIBUTE_NAME, FLAG, VALUE, WORST, THRESH, TYPE, UPDATED, WHEN_FAILED, RAW_VALUE
                if len(parts) >= 10:
                    try:
                        id_ = int(parts[0])
                    except ValueError:
                        id_ = parts[0]
                    attr = {
                        "id": id_,
                        "name": parts[1],
                        "value": parts[3],
                        "worst": parts[4],
                        "thresh": parts[5],
                        "type": parts[6],
                        "updated": parts[7],
                        "when_failed": parts[8],
                        "raw": " ".join(parts[9:]),
                    }
                    attrs.append(attr)
                else:
                    # Fallback: store raw line
                    attrs.append({"raw": line})
            else:
                # end of table
                in_attr_table = False

    if attrs:
        data["attributes"] = attrs
    # parse nvme health lines into structured fields
    if nvme_section_lines:
        # Build structured nvme fields: { key: { raw: str, value: int|float|str, unit: str|null } }
        nv_struct: Dict[str, Dict] = {}
        import re
        for l in nvme_section_lines:
            if ":" not in l:
                continue
            k, v = l.split(":", 1)
            key = k.strip().lower().replace(" ", "_")
            raw = v.strip()
            field = {"raw": raw}
            # try to extract number and unit
            # match patterns like '1,778,299 [910 GB]' or '29 Celsius' or '100%'
            # first try to find a bracketed unit (e.g. [910 GB])
            br = re.search(r"\[(.*?)\]", raw)
            if br:
                # attempt to extract the primary numeric before bracket
                m = re.search(r"([-+]?\d+[\d,]*)", raw)
                if m:
                    num = m.group(1).replace(",", "")
                    try:
                        field["value"] = int(num)
                    except ValueError:
                        try:
                            field["value"] = float(num)
                        except Exception:
                            field["value"] = raw
                field["unit"] = br.group(1)
            else:
                # look for number + optional unit
                m2 = re.match(r"^\s*([-+]?\d+[\d,]*)(?:\s*(\w+%?|Celsius|KB|MB|GB|TB)?)", raw)
                if m2:
                    num = m2.group(1).replace(",", "")
                    unit = m2.group(2) or None
                    try:
                        field["value"] = int(num)
                    except ValueError:
                        try:
                            field["value"] = float(num)
                        except Exception:
                            field["value"] = raw
                    field["unit"] = unit
                else:
                    field["value"] = raw
                    field["unit"] = None
            nv_struct[key] = field
        data.setdefault("nvme_health", {}).update(nv_struct)
    # include raw summary
    data.setdefault("raw", output)
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description="View SMART info via smartctl")
    parser.add_argument("--list", action="store_true", help="List detected devices")
    parser.add_argument("--device", help="Device path, e.g. /dev/sda or /dev/nvme0n1")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--include-raw", action="store_true", help="Include raw smartctl output in JSON")
    args = parser.parse_args(argv)

    smartctl = find_smartctl()
    if not smartctl:
        print("smartctl not found. Please install smartmontools.", file=sys.stderr)
        return 2

    if args.list:
        try:
            devices = list_devices(smartctl)
        except RuntimeError as e:
            print("Failed to list devices:", e, file=sys.stderr)
            return 3
        if args.json:
            print(json.dumps({"devices": devices}, indent=2))
        else:
            for d in devices:
                print(d)
        return 0

    if not args.device:
        print("Please specify --device or --list", file=sys.stderr)
        return 2

    output = run_smartctl(smartctl, args.device)
    parsed = parse_smart_output(output)
    # by default, omit the raw dump from JSON to keep output clean; include with --include-raw
    if args.json:
        to_print = dict(parsed)
        if not args.include_raw and "raw" in to_print:
            del to_print["raw"]
        print(json.dumps(to_print, indent=2))
    else:
        print(f"Device: {args.device}")
        print("Model:", parsed.get("model", "n/a"))
        print("Serial:", parsed.get("serial", "n/a"))
        print("Firmware:", parsed.get("firmware", "n/a"))
        print("Health:", parsed.get("health", "n/a"))
        if "attributes" in parsed:
            print("\nSMART Attributes:\nID  Name  Value  Worst  Thresh  Raw")
            for a in parsed["attributes"]:
                if "id" in a:
                    print(f"{a['id']:>2}  {a.get('name',''):15} {a.get('value',''):>5} {a.get('worst',''):>5} {a.get('thresh',''):>6} {a.get('raw','')}")
                else:
                    print(a.get("raw"))


if __name__ == "__main__":
    raise SystemExit(main())
