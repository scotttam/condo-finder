# Exactly one worker: the in-process scheduler must exist once.
bind = "0.0.0.0:8000"
workers = 1
worker_class = "gthread"
threads = 4
timeout = 120
accesslog = "-"
errorlog = "-"
