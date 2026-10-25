"""Append one blood pressure reading to the CSV log, skipping exact duplicates.

Usage: bp_log.py <timestamp> <systolic> <diastolic> <pulse> [person]

person "person1" (default) -> blood_pressure_log.csv; any other -> blood_pressure_log_<person>.csv
Copy to /config/scripts/bp_log.py and call it from shell_command.bp_log_append.
"""
import csv
import os
import sys

LOG = "/config/bp/blood_pressure_log.csv"
HEADER = ["Date", "Time", "Systolic (mmHg)", "Diastolic (mmHg)", "Pulse (bpm)"]


def main() -> None:
    ts, sys_, dia, pulse = sys.argv[1:5]
    person = (sys.argv[5] if len(sys.argv) > 5 else "person1").strip().lower() or "person1"
    log = LOG if person == "person1" else LOG.replace(".csv", f"_{person}.csv")
    # ts is ISO local time, e.g. 2026-10-12T09:10:14-07:00
    date, time = ts[:10], ts[11:16]
    row = [date, time, sys_, dia, pulse]

    os.makedirs(os.path.dirname(log), exist_ok=True)
    rows = []
    if os.path.exists(log):
        with open(log, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
    data = rows[1:] if rows else []
    if row in data:
        return
    data.append(row)
    # readings stored on the monitor can arrive late; keep the file in time order
    data.sort(key=lambda r: (r[0], r[1]))
    with open(log, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(HEADER)
        writer.writerows(data)


if __name__ == "__main__":
    main()
