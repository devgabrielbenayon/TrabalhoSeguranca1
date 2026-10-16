import os

# antes de qualquer import do back-end: o `app` do módulo não deve criar data/criptochat.db
os.environ.setdefault("CRIPTOCHAT_DB", "sqlite://")
