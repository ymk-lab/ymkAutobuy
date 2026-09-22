# REAL needs two locks and only the next Once

Switching the Futu book from SIMULATE to REAL is easy to mis-click and hard to unwind. Production therefore keeps `QRESEARCH_FUTU_ALLOW_LIVE` as a server-side lock the web UI cannot set, requires an explicit web confirmation after that lock is on, and applies the new Trading Environment only to the next Once. Turning REAL off is immediate for future Ons; it does not invent a mid-session flatten.
