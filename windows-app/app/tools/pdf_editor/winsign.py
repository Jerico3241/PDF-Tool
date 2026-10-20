"""Zertifikatspeicher von Windows für digitale Signaturen (seit 4.0 Beta 6) – über ctypes, ohne Zusatzpakete.

* ``certificates()``: eigene Zertifikate (»Eigene Zertifikate« des Benutzers) mit privatem Schlüssel, die signieren
  dürfen.
* ``StoreSigner``: signiert mit dem Schlüssel im Speicher – der Schlüssel verlässt Windows nie; bei Chipkarten fragt
  Windows selbst nach der PIN. Neue Schlüssel (CNG) und ältere (CryptoAPI, z. B. per Doppelklick importierte
  .pfx-Dateien) werden unterstützt.
* ``trust()``: baut die Zertifikatskette wie Windows selbst (vertrauenswürdige Stammzertifizierungsstellen,
  Sperrlisten nur aus dem Zwischenspeicher – ohne Netzwerk).
"""

from __future__ import annotations

import ctypes
import hashlib
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timezone

from .digsig import SignError, can_sign, cert_info

crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
ncrypt = ctypes.WinDLL("ncrypt", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

X509_ASN_ENCODING = 0x1
PKCS_7_ASN_ENCODING = 0x10000
ENCODING = X509_ASN_ENCODING | PKCS_7_ASN_ENCODING
CERT_KEY_PROV_INFO_PROP_ID = 2
CERT_STORE_ADD_ALWAYS = 4
CERT_STORE_PROV_MEMORY = 2
CRYPT_ACQUIRE_CACHE_FLAG = 0x1
CRYPT_ACQUIRE_COMPARE_KEY_FLAG = 0x4
CRYPT_ACQUIRE_PREFER_NCRYPT_KEY_FLAG = 0x20000
CERT_NCRYPT_KEY_SPEC = 0xFFFFFFFF
BCRYPT_PAD_PKCS1 = 0x2
NCRYPT_SILENT_FLAG = 0x40
CALG_SHA_256 = 0x0000800C
HP_HASHVAL = 0x2
PROV_RSA_AES = 24
MS_ENH_RSA_AES_PROV = "Microsoft Enhanced RSA and AES Cryptographic Provider"
CERT_CHAIN_REVOCATION_CHECK_CHAIN_EXCLUDE_ROOT = 0x40000000
CERT_CHAIN_REVOCATION_CHECK_CACHE_ONLY = 0x80000000
CERT_TRUST_IS_NOT_TIME_VALID = 0x1
CERT_TRUST_IS_REVOKED = 0x4
CERT_TRUST_IS_NOT_SIGNATURE_VALID = 0x8
CERT_TRUST_IS_UNTRUSTED_ROOT = 0x20
CERT_TRUST_REVOCATION_STATUS_UNKNOWN = 0x40
CERT_TRUST_IS_PARTIAL_CHAIN = 0x10000
CERT_TRUST_IS_OFFLINE_REVOCATION = 0x1000000


class CERT_CONTEXT(ctypes.Structure):
    _fields_ = [("dwCertEncodingType", wintypes.DWORD), ("pbCertEncoded", ctypes.POINTER(ctypes.c_ubyte)),
                ("cbCertEncoded", wintypes.DWORD), ("pCertInfo", ctypes.c_void_p), ("hCertStore", ctypes.c_void_p)]


PCCERT_CONTEXT = ctypes.POINTER(CERT_CONTEXT)


class BCRYPT_PKCS1_PADDING_INFO(ctypes.Structure):
    _fields_ = [("pszAlgId", wintypes.LPCWSTR)]


class CERT_TRUST_STATUS(ctypes.Structure):
    _fields_ = [("dwErrorStatus", wintypes.DWORD), ("dwInfoStatus", wintypes.DWORD)]


class CERT_CHAIN_CONTEXT(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("TrustStatus", CERT_TRUST_STATUS)]


class CERT_ENHKEY_USAGE(ctypes.Structure):
    _fields_ = [("cUsageIdentifier", wintypes.DWORD), ("rgpszUsageIdentifier", ctypes.c_void_p)]


class CERT_USAGE_MATCH(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD), ("Usage", CERT_ENHKEY_USAGE)]


class CERT_CHAIN_PARA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("RequestedUsage", CERT_USAGE_MATCH)]


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


crypt32.CertOpenStore.restype = ctypes.c_void_p
crypt32.CertOpenStore.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
crypt32.CertOpenSystemStoreW.restype = ctypes.c_void_p
crypt32.CertOpenSystemStoreW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
crypt32.CertEnumCertificatesInStore.restype = PCCERT_CONTEXT
crypt32.CertEnumCertificatesInStore.argtypes = [ctypes.c_void_p, PCCERT_CONTEXT]
crypt32.CertDuplicateCertificateContext.restype = PCCERT_CONTEXT
crypt32.CertDuplicateCertificateContext.argtypes = [PCCERT_CONTEXT]
crypt32.CertFreeCertificateContext.argtypes = [PCCERT_CONTEXT]
crypt32.CertCloseStore.argtypes = [ctypes.c_void_p, wintypes.DWORD]
crypt32.CertGetCertificateContextProperty.argtypes = [PCCERT_CONTEXT, wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
crypt32.CertGetCertificateContextProperty.restype = wintypes.BOOL
crypt32.CryptAcquireCertificatePrivateKey.argtypes = [PCCERT_CONTEXT, wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t),
                                                       ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.BOOL)]
crypt32.CryptAcquireCertificatePrivateKey.restype = wintypes.BOOL
crypt32.CertCreateCertificateContext.restype = PCCERT_CONTEXT
crypt32.CertCreateCertificateContext.argtypes = [wintypes.DWORD, ctypes.c_char_p, wintypes.DWORD]
crypt32.CertAddEncodedCertificateToStore.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_char_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
crypt32.CertAddEncodedCertificateToStore.restype = wintypes.BOOL
crypt32.CertGetCertificateChain.argtypes = [ctypes.c_void_p, PCCERT_CONTEXT, ctypes.POINTER(FILETIME), ctypes.c_void_p,
                                            ctypes.POINTER(CERT_CHAIN_PARA), wintypes.DWORD, ctypes.c_void_p,
                                            ctypes.POINTER(ctypes.POINTER(CERT_CHAIN_CONTEXT))]
crypt32.CertGetCertificateChain.restype = wintypes.BOOL
crypt32.CertFreeCertificateChain.argtypes = [ctypes.POINTER(CERT_CHAIN_CONTEXT)]
ncrypt.NCryptSignHash.argtypes = [ctypes.c_size_t, ctypes.c_void_p, ctypes.c_char_p, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                  ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
ncrypt.NCryptSignHash.restype = ctypes.c_long
ncrypt.NCryptGetProperty.argtypes = [ctypes.c_size_t, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
ncrypt.NCryptGetProperty.restype = ctypes.c_long
ncrypt.NCryptFreeObject.argtypes = [ctypes.c_size_t]
advapi32.CryptCreateHash.argtypes = [ctypes.c_size_t, wintypes.DWORD, ctypes.c_size_t, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)]
advapi32.CryptCreateHash.restype = wintypes.BOOL
advapi32.CryptSetHashParam.argtypes = [ctypes.c_size_t, wintypes.DWORD, ctypes.c_char_p, wintypes.DWORD]
advapi32.CryptSetHashParam.restype = wintypes.BOOL
advapi32.CryptSignHashW.argtypes = [ctypes.c_size_t, wintypes.DWORD, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
advapi32.CryptSignHashW.restype = wintypes.BOOL
advapi32.CryptDestroyHash.argtypes = [ctypes.c_size_t]
advapi32.CryptReleaseContext.argtypes = [ctypes.c_size_t, wintypes.DWORD]
advapi32.CryptGetProvParam.argtypes = [ctypes.c_size_t, wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
advapi32.CryptGetProvParam.restype = wintypes.BOOL
advapi32.CryptAcquireContextW.argtypes = [ctypes.POINTER(ctypes.c_size_t), wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
advapi32.CryptAcquireContextW.restype = wintypes.BOOL
PP_CONTAINER = 6


def _der(context: PCCERT_CONTEXT) -> bytes:
    return ctypes.string_at(context.contents.pbCertEncoded, context.contents.cbCertEncoded)


def _has_key(context: PCCERT_CONTEXT) -> bool:
    size = wintypes.DWORD(0)
    return bool(crypt32.CertGetCertificateContextProperty(context, CERT_KEY_PROV_INFO_PROP_ID, None, ctypes.byref(size)))


@dataclass(frozen=True)
class StoreCertificate:
    thumbprint: str
    der: bytes
    subject: str
    issuer: str
    email: str
    not_after: datetime
    self_signed: bool


def certificates() -> list[StoreCertificate]:
    """Gültige eigene Zertifikate mit privatem Schlüssel, die zum Signieren taugen – neueste zuerst."""
    store = crypt32.CertOpenSystemStoreW(None, "MY")
    if not store:
        return []
    found: list[StoreCertificate] = []
    now = datetime.now(timezone.utc)
    try:
        context = crypt32.CertEnumCertificatesInStore(store, None)
        while context:
            try:
                if _has_key(context):
                    der = _der(context)
                    if can_sign(der):
                        info = cert_info(der)
                        if info.valid_at(now):
                            found.append(StoreCertificate(info.thumbprint, der, info.subject, info.issuer, info.email, info.not_after, info.self_signed))
            except Exception:  # noqa: BLE001 - ein unlesbares Zertifikat überspringen
                pass
            context = crypt32.CertEnumCertificatesInStore(store, context)
    finally:
        crypt32.CertCloseStore(store, 0)
    found.sort(key=lambda item: item.not_after, reverse=True)
    return found


def _find(thumbprint: str) -> tuple[ctypes.c_void_p, PCCERT_CONTEXT] | None:
    store = crypt32.CertOpenSystemStoreW(None, "MY")
    if not store:
        return None
    context = crypt32.CertEnumCertificatesInStore(store, None)
    while context:
        if hashlib.sha1(_der(context)).hexdigest().upper() == thumbprint.upper():
            return store, crypt32.CertDuplicateCertificateContext(context)
        context = crypt32.CertEnumCertificatesInStore(store, context)
    crypt32.CertCloseStore(store, 0)
    return None


class StoreSigner:
    """Signiert mit einem Zertifikat aus »Eigene Zertifikate« (Kennung: SHA-1-Fingerabdruck)."""

    def __init__(self, thumbprint: str) -> None:
        found = _find(thumbprint)
        if found is None:
            raise SignError("Das Zertifikat wurde im Zertifikatspeicher von Windows nicht gefunden.")
        self._store, self._context = found
        self.certificate = _der(self._context)
        self.chain = _chain_certificates(self._context)

    def close(self) -> None:
        if self._context:
            crypt32.CertFreeCertificateContext(self._context)
            self._context = None
        if self._store:
            crypt32.CertCloseStore(self._store, 0)
            self._store = None

    def __del__(self) -> None:  # noqa: D105
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass

    def sign(self, data: bytes) -> bytes:
        from cryptography import x509
        from cryptography.hazmat.primitives.asymmetric import ec

        digest = hashlib.sha256(data).digest()
        key = ctypes.c_size_t(0)
        spec = wintypes.DWORD(0)
        free = wintypes.BOOL(False)
        flags = CRYPT_ACQUIRE_PREFER_NCRYPT_KEY_FLAG | CRYPT_ACQUIRE_COMPARE_KEY_FLAG
        if not crypt32.CryptAcquireCertificatePrivateKey(self._context, flags, None, ctypes.byref(key), ctypes.byref(spec), ctypes.byref(free)):
            raise SignError("Auf den privaten Schlüssel des Zertifikats besteht kein Zugriff.")
        is_ec = isinstance(x509.load_der_x509_certificate(self.certificate).public_key(), ec.EllipticCurvePublicKey)
        try:
            if spec.value == CERT_NCRYPT_KEY_SPEC:
                return _ncrypt_sign(key.value, digest, is_ec)
            if is_ec:
                raise SignError("Dieser Schlüssel wird nicht unterstützt.")
            return _capi_sign(key.value, spec.value, digest)
        finally:
            if free.value:
                if spec.value == CERT_NCRYPT_KEY_SPEC:
                    ncrypt.NCryptFreeObject(key.value)
                else:
                    advapi32.CryptReleaseContext(key.value, 0)


def _ncrypt_sign(key: int, digest: bytes, is_ec: bool) -> bytes:
    padding = BCRYPT_PKCS1_PADDING_INFO("SHA256")
    info = None if is_ec else ctypes.byref(padding)
    flags = 0 if is_ec else BCRYPT_PAD_PKCS1
    size = wintypes.DWORD(0)
    status = ncrypt.NCryptSignHash(key, info, digest, len(digest), None, 0, ctypes.byref(size), flags)
    if status != 0:
        raise SignError(f"Windows konnte nicht signieren (Fehler 0x{status & 0xFFFFFFFF:08X}).")
    buffer = ctypes.create_string_buffer(size.value)
    status = ncrypt.NCryptSignHash(key, info, digest, len(digest), buffer, size, ctypes.byref(size), flags)
    if status != 0:
        if status & 0xFFFFFFFF == 0x80100074 or status & 0xFFFFFFFF == 0x800704C7:  # abgebrochen
            raise SignError("Das Signieren wurde abgebrochen.")
        raise SignError(f"Windows konnte nicht signieren (Fehler 0x{status & 0xFFFFFFFF:08X}).")
    raw = buffer.raw[:size.value]
    if not is_ec:
        return raw
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

    half = len(raw) // 2
    return encode_dss_signature(int.from_bytes(raw[:half], "big"), int.from_bytes(raw[half:], "big"))


def _capi_sign(provider: int, spec: int, digest: bytes) -> bytes:
    """Ältere Schlüssel (CryptoAPI). SHA-256 kann nur der AES-Anbieter – derselbe Schlüsselcontainer wird dafür mit
    ihm geöffnet, falls der ursprüngliche Anbieter das nicht kann."""
    hash_handle = ctypes.c_size_t(0)
    owned = 0
    if not advapi32.CryptCreateHash(provider, CALG_SHA_256, 0, 0, ctypes.byref(hash_handle)):
        size = wintypes.DWORD(0)
        advapi32.CryptGetProvParam(provider, PP_CONTAINER, None, ctypes.byref(size), 0)
        name = ctypes.create_string_buffer(size.value)
        if not advapi32.CryptGetProvParam(provider, PP_CONTAINER, name, ctypes.byref(size), 0):
            raise SignError("Dieser Schlüssel kann nicht mit SHA-256 signieren.")
        handle = ctypes.c_size_t(0)
        container = name.value.decode("mbcs", "replace")
        if not advapi32.CryptAcquireContextW(ctypes.byref(handle), container, MS_ENH_RSA_AES_PROV, PROV_RSA_AES, 0):
            raise SignError("Dieser Schlüssel kann nicht mit SHA-256 signieren.")
        owned = provider = handle.value
        if not advapi32.CryptCreateHash(provider, CALG_SHA_256, 0, 0, ctypes.byref(hash_handle)):
            advapi32.CryptReleaseContext(owned, 0)
            raise SignError("Dieser Schlüssel kann nicht mit SHA-256 signieren.")
    try:
        if not advapi32.CryptSetHashParam(hash_handle.value, HP_HASHVAL, digest, 0):
            raise SignError("Windows konnte nicht signieren.")
        size = wintypes.DWORD(0)
        advapi32.CryptSignHashW(hash_handle.value, spec, None, 0, None, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.CryptSignHashW(hash_handle.value, spec, None, 0, buffer, ctypes.byref(size)):
            raise SignError("Windows konnte nicht signieren (Zugriff verweigert oder abgebrochen).")
        return buffer.raw[:size.value][::-1]  # CryptoAPI liefert Little-Endian
    finally:
        advapi32.CryptDestroyHash(hash_handle.value)
        if owned:
            advapi32.CryptReleaseContext(owned, 0)


def _build_chain(context: PCCERT_CONTEXT, extra: list[bytes], when: datetime | None):
    """CertGetCertificateChain mit zusätzlichen Zertifikaten aus der Signatur; liefert (Kette oder None, Speicher)."""
    memory = crypt32.CertOpenStore(ctypes.c_void_p(CERT_STORE_PROV_MEMORY), 0, None, 0, None)
    for der in extra:
        crypt32.CertAddEncodedCertificateToStore(memory, ENCODING, der, len(der), CERT_STORE_ADD_ALWAYS, None)
    para = CERT_CHAIN_PARA()
    para.cbSize = ctypes.sizeof(CERT_CHAIN_PARA)
    moment = None
    if when is not None:
        ticks = int((when.astimezone(timezone.utc) - datetime(1601, 1, 1, tzinfo=timezone.utc)).total_seconds() * 10_000_000)
        moment = FILETIME(ticks & 0xFFFFFFFF, ticks >> 32)
    chain = ctypes.POINTER(CERT_CHAIN_CONTEXT)()
    flags = CERT_CHAIN_REVOCATION_CHECK_CHAIN_EXCLUDE_ROOT | CERT_CHAIN_REVOCATION_CHECK_CACHE_ONLY
    ok = crypt32.CertGetCertificateChain(None, context, ctypes.byref(moment) if moment is not None else None, memory,
                                         ctypes.byref(para), flags, None, ctypes.byref(chain))
    return (chain if ok and chain else None), memory


def _chain_certificates(context: PCCERT_CONTEXT) -> list[bytes]:
    """Zwischenzertifikate der eigenen Kette (ohne Stamm) – für die Signatur."""
    try:
        chain, memory = _build_chain(context, [], None)
    except OSError:
        return []
    try:
        if chain is None:
            return []
        return _chain_ders(chain)[1:-1]
    finally:
        if chain is not None:
            crypt32.CertFreeCertificateChain(chain)
        crypt32.CertCloseStore(memory, 0)


class CERT_CHAIN_ELEMENT(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("pCertContext", PCCERT_CONTEXT), ("TrustStatus", CERT_TRUST_STATUS)]


class CERT_SIMPLE_CHAIN(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("TrustStatus", CERT_TRUST_STATUS), ("cElement", wintypes.DWORD),
                ("rgpElement", ctypes.POINTER(ctypes.POINTER(CERT_CHAIN_ELEMENT)))]


class CERT_CHAIN_CONTEXT_FULL(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("TrustStatus", CERT_TRUST_STATUS), ("cChain", wintypes.DWORD),
                ("rgpChain", ctypes.POINTER(ctypes.POINTER(CERT_SIMPLE_CHAIN)))]


def _chain_ders(chain) -> list[bytes]:
    full = ctypes.cast(chain, ctypes.POINTER(CERT_CHAIN_CONTEXT_FULL)).contents
    if full.cChain == 0:
        return []
    simple = full.rgpChain[0].contents
    return [_der(simple.rgpElement[index].contents.pCertContext) for index in range(simple.cElement)]


def trust(cert: bytes, extra: list[bytes], when: datetime | None) -> tuple[str, str]:
    """Vertraut Windows dem Zertifikat (zum Zeitpunkt der Signatur)? → (Stufe, Erklärung)."""
    context = crypt32.CertCreateCertificateContext(ENCODING, cert, len(cert))
    if not context:
        return "untrusted", "Das Zertifikat ist nicht lesbar."
    chain = None
    memory = None
    try:
        chain, memory = _build_chain(context, extra, when)
        if chain is None:
            return "untrusted", "Windows konnte die Zertifikatskette nicht aufbauen."
        status = chain.contents.TrustStatus.dwErrorStatus
    finally:
        if chain is not None:
            crypt32.CertFreeCertificateChain(chain)
        if memory:
            crypt32.CertCloseStore(memory, 0)
        crypt32.CertFreeCertificateContext(context)
    if status & CERT_TRUST_IS_REVOKED:
        return "revoked", "Das Zertifikat wurde gesperrt."
    if status & CERT_TRUST_IS_NOT_SIGNATURE_VALID:
        return "untrusted", "Die Zertifikatskette ist beschädigt."
    if status & (CERT_TRUST_IS_UNTRUSTED_ROOT | CERT_TRUST_IS_PARTIAL_CHAIN):
        return "untrusted", "Windows kennt die ausstellende Stelle nicht (z. B. selbst ausgestelltes Zertifikat)."
    if status & CERT_TRUST_IS_NOT_TIME_VALID:
        return "expired", "Das Zertifikat war zum Zeitpunkt der Signatur nicht gültig."
    remaining = status & ~(CERT_TRUST_REVOCATION_STATUS_UNKNOWN | CERT_TRUST_IS_OFFLINE_REVOCATION)
    if remaining:
        return "untrusted", f"Windows vertraut dem Zertifikat nicht (Status 0x{status:X})."
    return "trusted", "Windows vertraut dem Zertifikat."
