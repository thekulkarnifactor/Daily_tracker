import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
# One process keeps the in-memory sheet cache and write lock consistent;
# threads handle concurrency (the work is I/O-bound Google API calls).
workers = 1
threads = int(os.environ.get("GUNICORN_THREADS", "8"))
timeout = 60
graceful_timeout = 20
accesslog = "-"
errorlog = "-"
forwarded_allow_ips = "*"
