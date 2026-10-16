import asyncio
import os
import socket
import threading
import time

import pytest

# antes de qualquer import do back-end: o `app` do módulo não deve criar data/criptochat.db
os.environ.setdefault("CRIPTOCHAT_DB", "sqlite://")


@pytest.fixture
def servidor(tmp_path):
    """Back-end real (uvicorn) numa thread, com banco SQLite em arquivo temporário."""
    import uvicorn

    from backend.main import criar_app

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
    banco = tmp_path / "servidor.db"
    config = uvicorn.Config(criar_app(f"sqlite:///{banco.as_posix()}"), host="127.0.0.1", port=porta, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    limite = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < limite, "servidor não subiu"
        time.sleep(0.02)
    yield {"http": f"http://127.0.0.1:{porta}", "ws": f"ws://127.0.0.1:{porta}/ws", "banco": banco}
    server.should_exit = True
    thread.join(timeout=10)


async def esperar(condicao, segundos=5.0):
    limite = time.monotonic() + segundos
    while not condicao():
        assert time.monotonic() < limite, "condição não ocorreu a tempo"
        await asyncio.sleep(0.02)
