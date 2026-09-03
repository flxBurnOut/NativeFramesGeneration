from __future__ import annotations

import base64
import ctypes
import hashlib
import os
from pathlib import Path
from typing import Any

from .jsonio import atomic_write_json, read_json


class CredentialStoreError(RuntimeError):
    """Raised when local protected credentials cannot be decoded or written."""


class CredentialStore:
    """Small OS-bound secret store.

    Windows uses the current user's DPAPI key, so copying credentials.json to
    another account or machine does not reveal the API token. Other platforms
    retain a permission-restricted fallback until a native keyring is added.
    """

    def __init__(self, config_dir: Path) -> None:
        self.config_dir = config_dir.resolve()
        self.path = self.config_dir / "credentials.json"

    @property
    def protection(self) -> str:
        return "windows-dpapi-current-user" if os.name == "nt" else "restricted-local-file"

    def get(self, name: str) -> str | None:
        payload = self._read()
        record = payload.get("secrets", {}).get(name)
        if not isinstance(record, dict):
            return None
        encoded = record.get("value")
        if not isinstance(encoded, str) or not encoded:
            return None
        try:
            protected = base64.b64decode(encoded, validate=True)
            entropy_version = record.get("entropy_version")
            used_legacy_entropy = False
            if os.name == "nt" and entropy_version != "stable-v1":
                try:
                    clear = self._unprotect(protected)
                except Exception:
                    clear = _windows_dpapi(
                        protected,
                        self._legacy_entropy(),
                        decrypt=True,
                    )
                    used_legacy_entropy = True
            else:
                clear = self._unprotect(protected)
            value = clear.decode("utf-8")
            if used_legacy_entropy:
                # Earlier builds tied DPAPI entropy to the absolute data path.
                # Re-encrypt once with a stable application entropy so Windows
                # package virtualization or a future data-directory move cannot
                # make the credential unreadable.
                self.set(name, value)
            return value
        except Exception as exc:
            raise CredentialStoreError("stored credential cannot be decrypted") from exc

    def set(self, name: str, value: str | None) -> None:
        if not name or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in name):
            raise ValueError("credential name is invalid")
        payload = self._read()
        secrets = payload.setdefault("secrets", {})
        if value is None:
            secrets.pop(name, None)
        else:
            clear = value.encode("utf-8")
            protected = self._protect(clear)
            secrets[name] = {
                "protection": self.protection,
                "entropy_version": "stable-v1",
                "value": base64.b64encode(protected).decode("ascii"),
            }
        payload["schema_version"] = 1
        payload["protection"] = self.protection
        self.config_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path, payload)
        if os.name != "nt":
            try:
                self.path.chmod(0o600)
            except OSError:
                pass

    def public_status(self) -> dict[str, Any]:
        try:
            configured = self.get("pixellab_api_key") is not None
            error = None
        except CredentialStoreError as exc:
            configured = False
            error = str(exc)
        return {
            "configured": configured,
            "protection": self.protection,
            "path": str(self.path),
            "healthy": error is None,
            "error": error,
        }

    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"schema_version": 1, "protection": self.protection, "secrets": {}}
        try:
            payload = read_json(self.path)
        except Exception as exc:
            raise CredentialStoreError("credential file is not valid JSON") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("secrets", {}), dict):
            raise CredentialStoreError("credential file has an invalid structure")
        return payload

    def _entropy(self) -> bytes:
        return hashlib.sha256(b"SpritePipeline|credentials|stable-v1").digest()

    def _legacy_entropy(self) -> bytes:
        identity = f"SpritePipeline|{self.config_dir}".encode("utf-8")
        return hashlib.sha256(identity).digest()

    def _protect(self, clear: bytes) -> bytes:
        if os.name != "nt":
            return clear
        return _windows_dpapi(clear, self._entropy(), decrypt=False)

    def _unprotect(self, protected: bytes) -> bytes:
        if os.name != "nt":
            return protected
        return _windows_dpapi(protected, self._entropy(), decrypt=True)


def _windows_dpapi(payload: bytes, entropy: bytes, *, decrypt: bool) -> bytes:
    class DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.c_uint32),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    def blob(value: bytes) -> tuple[DataBlob, Any]:
        buffer = ctypes.create_string_buffer(value, len(value))
        return (
            DataBlob(
                len(value),
                ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
            ),
            buffer,
        )

    crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
    kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    input_blob, input_buffer = blob(payload)
    entropy_blob, entropy_buffer = blob(entropy)
    output_blob = DataBlob()
    flags = 0x01  # CRYPTPROTECT_UI_FORBIDDEN
    operation = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    operation.argtypes = [
        ctypes.POINTER(DataBlob),
        ctypes.c_void_p,
        ctypes.POINTER(DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(DataBlob),
    ]
    operation.restype = ctypes.c_int
    # Keep both source buffers alive for the duration of the native call.
    _keep_alive = (input_buffer, entropy_buffer)
    if not operation(
        ctypes.byref(input_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        flags,
        ctypes.byref(output_blob),
    ):
        error = ctypes.get_last_error()
        raise CredentialStoreError(f"Windows DPAPI operation failed ({error})")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))
