# Exactly one worker: the in-process scheduler must exist once.
# Localhost only: people reach the app through Tailscale Funnel (HTTPS), never port 8000 directly.
bind = "127.0.0.1:8000"
workers = 1
worker_class = "gthread"
threads = 4
timeout = 120
accesslog = "-"
errorlog = "-"
# The SQL console runs queries by GET ?q= so each has a permalink; the 4094-byte default rejects long ones.
limit_request_line = 0
