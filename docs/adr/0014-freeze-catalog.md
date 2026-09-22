# Freeze on ops failure, fill mismatch, or 50bps slip

Unattended Once must stop rather than self-heal. Freeze triggers: OpenD down or login dead; any Once leg fails or times out; preview versus fill reconcile fails; a fill slips more than 50bps versus the plan price; Signal asof is not the last complete US session; REAL is selected while ALLOW_LIVE is off. Unfreeze is manual. Alerts go by email.
