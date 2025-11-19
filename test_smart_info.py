import json
import subprocess
import sys

import pytest

from smart_info import parse_smart_output, run_smartctl, find_smartctl


SAMPLE_ATA = """
=== START OF INFORMATION SECTION ===
Device Model: TestDisk 1TB
Serial Number: ABCDEFG
Firmware Version: 1.23
SMART overall-health self-assessment test result: PASSED

ID# ATTRIBUTE_NAME FLAG VALUE WORST THRESH TYPE UPDATED WHEN_FAILED RAW_VALUE
  1 Raw_Read_Error_Rate 0x000f 200 200 051 Pre-fail Always - 0
  5 Reallocated_Sector_Ct 0x0033 100 100 036 Pre-fail Always - 0
"""

SAMPLE_NVME = """
smartctl 7.5 2025-04-30 r5714 [x86_64-linux-6.17.7-300.fc43.x86_64] (local build)
\n=== START OF INFORMATION SECTION ===
Model Number:                       UMIS RPJYJ1T24RLS1QWY
Serial Number:                      SS1Q23148Z1CD56B11B0
Firmware Version:                   1.0L0541
\n=== START OF SMART DATA SECTION ===
SMART overall-health self-assessment test result: PASSED
\nSMART/Health Information (NVMe Log 0x02, NSID 0xffffffff)
Critical Warning:                   0x00
Temperature:                        29 Celsius
Available Spare:                    100%
Available Spare Threshold:          10%
Percentage Used:                    0%
Data Units Read:                    1,778,273 [910 GB]
Data Units Written:                 2,725,721 [1.39 TB]
Power Cycles:                       73
Power On Hours:                     41
Unsafe Shutdowns:                   10
Media and Data Integrity Errors:    0
Error Information Log Entries:      0
\nError Information (NVMe Log 0x01, 16 of 64 entries)
No Errors Logged
\n"""


def test_parse_ata():
    parsed = parse_smart_output(SAMPLE_ATA)
    assert parsed["model"] == "TestDisk 1TB"
    assert parsed["serial"] == "ABCDEFG"
    assert parsed["firmware"] == "1.23"
    assert parsed["health"] == "PASSED"
    assert "attributes" in parsed
    assert any(a.get("name") == "Raw_Read_Error_Rate" for a in parsed["attributes"]) 


def test_find_smartctl_not_found(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'linux')
    # simulate not found by temporarily changing PATH
    monkeypatch.setenv('PATH', '')
    assert find_smartctl() is None


def test_parse_nvme():
  parsed = parse_smart_output(SAMPLE_NVME)
  assert parsed["model"] == "UMIS RPJYJ1T24RLS1QWY"
  assert parsed["serial"] == "SS1Q23148Z1CD56B11B0"
  assert parsed["firmware"] == "1.0L0541"
  nv = parsed.get("nvme_health")
  assert nv is not None
  # structured fields: each is a dict with raw/value/unit
  assert "percentage_used" in nv and isinstance(nv["percentage_used"], dict)
  assert nv["percentage_used"]["raw"] == "0%"
  assert nv["percentage_used"]["value"] == 0
  assert nv["temperature"]["value"] == 29
  assert nv["power_on_hours"]["value"] == 41
  assert nv["data_units_read"]["value"] == 1778273
  assert nv["data_units_written"]["value"] == 2725721
