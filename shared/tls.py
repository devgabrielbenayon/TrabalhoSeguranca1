"""TLS do canal cliente ↔ servidor: certificados locais e o contexto que o cliente usa para confiar neles.

O E2E já protege o conteúdo das mensagens; o TLS protege o que o E2E não cobre no caminho:
a senha no login, o token de sessão e os metadados (quem fala com quem).

Sem domínio público não há como obter certificado de uma autoridade reconhecida, então geramos:
- uma autoridade certificadora (AC) local, cuja chave privada é descartada logo após assinar;
- o certificado do servidor (127.0.0.1 e localhost), assinado por essa AC.
O cliente confia só nessa AC (`ca.pem`): um servidor com outro certificado é recusado.
"""

from __future__ import annotations

import ipaddress
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

PASTA_PADRAO = Path("data/tls")
NOMES_PADRAO = ("localhost", "127.0.0.1")
VALIDADE = timedelta(days=365)


@dataclass(frozen=True)
class ArquivosTls:
    ca: Path
    certificado: Path
    chave: Path

    @classmethod
    def na_pasta(cls, pasta: Path | str) -> ArquivosTls:
        pasta = Path(pasta)
        return cls(pasta / "ca.pem", pasta / "servidor.pem", pasta / "servidor-chave.pem")

    def existem(self) -> bool:
        return self.ca.exists() and self.certificado.exists() and self.chave.exists()


def _nome(texto: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CriptoChat RSA"), x509.NameAttribute(NameOID.COMMON_NAME, texto)])


def _alternativos(nomes: tuple[str, ...]) -> x509.SubjectAlternativeName:
    entradas: list[x509.GeneralName] = []
    for nome in nomes:
        try:
            entradas.append(x509.IPAddress(ipaddress.ip_address(nome)))
        except ValueError:
            entradas.append(x509.DNSName(nome))
    return x509.SubjectAlternativeName(entradas)


def gerar_certificados(pasta: Path | str = PASTA_PADRAO, nomes: tuple[str, ...] = NOMES_PADRAO) -> ArquivosTls:
    """Cria a AC local e o certificado do servidor. Curva P-256: o TLS usa ECDHE, que dá sigilo futuro ao canal."""
    arquivos = ArquivosTls.na_pasta(pasta)
    arquivos.ca.parent.mkdir(parents=True, exist_ok=True)
    agora = datetime.now(timezone.utc)
    inicio, fim = agora - timedelta(minutes=5), agora + VALIDADE

    chave_ca = ec.generate_private_key(ec.SECP256R1())
    ski_ca = x509.SubjectKeyIdentifier.from_public_key(chave_ca.public_key())
    ca = (
        x509.CertificateBuilder()
        .subject_name(_nome("CriptoChat AC local"))
        .issuer_name(_nome("CriptoChat AC local"))
        .public_key(chave_ca.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(inicio)
        .not_valid_after(fim)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False, content_commitment=False, key_encipherment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(ski_ca, critical=False)
        .sign(chave_ca, hashes.SHA256())
    )

    chave = ec.generate_private_key(ec.SECP256R1())
    certificado = (
        x509.CertificateBuilder()
        .subject_name(_nome(nomes[0]))
        .issuer_name(ca.subject)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(inicio)
        .not_valid_after(fim)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False, key_encipherment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(_alternativos(nomes), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(chave.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(ski_ca), critical=False)
        .sign(chave_ca, hashes.SHA256())
    )
    # a chave da AC não é gravada: ninguém consegue emitir outro certificado que o cliente aceite

    arquivos.ca.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    arquivos.certificado.write_bytes(certificado.public_bytes(serialization.Encoding.PEM))
    arquivos.chave.write_bytes(
        chave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    return arquivos


def contexto_cliente(ca: Path | str) -> ssl.SSLContext:
    """Confia só na AC indicada, exige TLS 1.3 e confere o nome do servidor."""
    contexto = ssl.create_default_context(cafile=str(ca))
    contexto.minimum_version = ssl.TLSVersion.TLSv1_3
    return contexto
