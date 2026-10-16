"""RSA com a biblioteca `cryptography` (modo real): 2048 bits, OAEP-SHA-256 para cifrar e PSS para assinar."""

from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from shared.crypto.base import IdentidadeChave

BITS_PADRAO = 2048
EXPOENTE_PUBLICO = 65537
_HASH = hashes.SHA256()

_OAEP = padding.OAEP(mgf=padding.MGF1(algorithm=_HASH), algorithm=_HASH, label=None)
_PSS = padding.PSS(mgf=padding.MGF1(_HASH), salt_length=padding.PSS.MAX_LENGTH)


class PublicaReal(IdentidadeChave):
    modo = "real"
    blocos_fixos = False  # o OAEP preserva o tamanho de cada bloco

    def __init__(self, chave: rsa.RSAPublicKey) -> None:
        self._chave = chave

    @property
    def tamanho_bloco(self) -> int:
        """k − 2·hLen − 2: 190 bytes para 2048 bits com SHA-256."""
        return self._chave.key_size // 8 - 2 * _HASH.digest_size - 2

    @property
    def numeros(self) -> dict[str, int]:
        numeros = self._chave.public_numbers()
        return {"e": numeros.e, "n": numeros.n}

    def bytes_canonicos(self) -> bytes:
        return self._chave.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )

    def exportar(self) -> str:
        return self._chave.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()

    @classmethod
    def carregar(cls, pem: str) -> PublicaReal:
        chave = serialization.load_pem_public_key(pem.encode())
        if not isinstance(chave, rsa.RSAPublicKey):
            raise ValueError("a chave pública não é RSA")
        return cls(chave)

    def cifrar_bloco(self, bloco: bytes, passos: list[dict] | None = None) -> bytes:
        if len(bloco) > self.tamanho_bloco:
            raise ValueError(f"bloco de {len(bloco)} bytes excede o máximo de {self.tamanho_bloco}")
        return self._chave.encrypt(bloco, _OAEP)

    def verificar(self, dados: bytes, assinatura: bytes, passos: list[dict] | None = None) -> bool:
        try:
            self._chave.verify(assinatura, dados, _PSS, _HASH)
        except InvalidSignature:
            return False
        return True


class PrivadaReal:
    modo = "real"

    def __init__(self, chave: rsa.RSAPrivateKey) -> None:
        self._chave = chave
        self.publica = PublicaReal(chave.public_key())

    def decifrar_bloco(self, cifrado: bytes, passos: list[dict] | None = None) -> bytes:
        # chave errada ou bloco adulterado: o OAEP rejeita com ValueError
        return self._chave.decrypt(cifrado, _OAEP)

    def assinar(self, dados: bytes, passos: list[dict] | None = None) -> bytes:
        return self._chave.sign(dados, _PSS, _HASH)

    def exportar(self, senha: str) -> bytes:
        """PEM PKCS#8 cifrado com a senha do usuário, para o keystore local."""
        return self._chave.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(senha.encode()),
        )

    @classmethod
    def carregar(cls, pem: bytes, senha: str) -> PrivadaReal:
        chave = serialization.load_pem_private_key(pem, password=senha.encode())
        if not isinstance(chave, rsa.RSAPrivateKey):
            raise ValueError("a chave privada não é RSA")
        return cls(chave)


def gerar(bits: int = BITS_PADRAO) -> PrivadaReal:
    return PrivadaReal(rsa.generate_private_key(public_exponent=EXPOENTE_PUBLICO, key_size=bits))
