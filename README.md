# Linux SMART viewer

## Brief Introduction

Small CLI to view SMART information using `smartctl` (from smartmontools).

## Requirements

- Linux
- smartctl (smartmontools)
- Python 3.8+

## Usage

List devices:

```{python}
  python smart_info.py --list
```

Show device SMART (readable format):

```{python}
  python smart_info.py --device /dev/sda
```

Show device SMART (json format):

```{python}
  python smart_info.py --device /dev/sda --json
```

Here /dev/sda is an example device. Change it to your actual device that listed in the device list.

## Release Notes

This is a small helper that shells out to `smartctl -a`. It provides basic parsing for common fields and the ATA attribute table. It is not comprehensive but useful for quick checks.
