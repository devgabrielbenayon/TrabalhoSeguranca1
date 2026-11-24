"""Sobe o back-end com TLS (https:// e wss://). Executar a partir da raiz: python -m backend

Na primeira vez gera a AC local e o certificado do servidor em data/tls/ (ver shared/tls.py).
Variáveis: CRIPTOCHAT_API_HOST (padrão 127.0.0.1), CRIPTOCHAT_API_PORTA (8000), CRIPTOCHAT_TLS (pasta dos certificados).
"""

import os

import uvicorn

from shared.tls import PASTA_PADRAO, ArquivosTls, gerar_certificados


def main() -> None:
    host = os.environ.get("CRIPTOCHAT_API_HOST", "127.0.0.1")
    porta = int(os.environ.get("CRIPTOCHAT_API_PORTA", "8000"))
    pasta = os.environ.get("CRIPTOCHAT_TLS", str(PASTA_PADRAO))

    arquivos = ArquivosTls.na_pasta(pasta)
    if not arquivos.existem():
        nomes = ("localhost", "127.0.0.1") if host in ("127.0.0.1", "localhost", "0.0.0.0") else (host, "localhost", "127.0.0.1")
        arquivos = gerar_certificados(pasta, nomes)
        print(f"Certificados TLS gerados em {pasta} (o front-end confia em {arquivos.ca})")

    uvicorn.run(
        "backend.main:app",
        host=host,
        port=porta,
        ssl_certfile=str(arquivos.certificado),
        ssl_keyfile=str(arquivos.chave),
    )


if __name__ == "__main__":
    main()
