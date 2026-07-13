"""Migrate a TV Time GDPR export into Yamtrack.

Two output paths are supported:

* ``convert`` – produce a Yamtrack-native import CSV you upload via the
  Yamtrack web UI (Settings -> Import). This path is the most robust for
  bulk loads.
* ``push`` – send each resolved item to the Yamtrack REST API using your
  API key.

See the README for full usage.
"""

__version__ = "1.0.0"
