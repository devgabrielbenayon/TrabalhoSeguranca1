"""Back-end do CriptoChat RSA. Executar a partir da raiz: uvicorn backend.main:app --reload"""

from fastapi import FastAPI

app = FastAPI(title="CriptoChat RSA", description="Diretório de chaves públicas e relay de envelopes cifrados")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
