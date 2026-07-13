"""Write resolved rows to a Yamtrack-native import CSV."""

from __future__ import annotations

import csv

from .build_records import CSV_COLUMNS


def write_csv(rows: list[dict], out_path: str) -> int:
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=CSV_COLUMNS, quoting=csv.QUOTE_ALL, extrasaction="ignore"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in CSV_COLUMNS})
    return len(rows)
