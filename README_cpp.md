# smart_info (C++ version)

Build (requires cmake and a C++17 compiler):

```bash
mkdir -p build && cd build
cmake ..
make -j
```

Usage:

List devices:

  ./smart_info --list --json

Query device (JSON):

  sudo ./smart_info --device /dev/nvme0 --json

Notes:

- This program shells out to `smartctl` and parses the output. It is a
  minimal port of the Python version and aims to provide similar JSON
  output for NVMe SMART/Health data. Use `--include-raw` to include the
  raw smartctl dump in the JSON.
