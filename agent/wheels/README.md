# Agent wheelhouse (offline install)

These `.whl` files (plus `get-pip.py`) are bundled into `/agent-pack.tgz` and
installed with `pip --no-index --find-links=…` so lab PCs do **not** need
campus proxy / PyPI.

Refresh (on a machine that can reach PyPI, often hobbit with proxy.cgi):

```bash
./scripts/linux/prefetch-agent-wheels.sh
```

Covers CPython 3.8–3.14 on Linux x86_64, Linux aarch64 (Jetson), and Windows amd64.
