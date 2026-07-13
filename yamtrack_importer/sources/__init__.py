"""Pluggable migration sources.

Each source knows how to turn some third-party export/credentials into Yamtrack
rows. TV Time is implemented today; the others are registered as planned so the
UI can show the roadmap. Add a new source by subclassing ``Source`` and
registering it in ``registry.py``.
"""
