"""This module provides some default cryptographic functions for safe transport of diff data."""

from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.types import (
    PrivateKeyTypes,
    PublicKeyTypes,
)


@lru_cache
def public_key_pem() -> PublicKeyTypes:
    with open(Path(__file__).parent.parent / "public_key.pem", "rb") as f:
        public_pem = f.read()
    return serialization.load_pem_public_key(public_pem)


@lru_cache
def private_key_pem() -> PrivateKeyTypes:
    with open(Path(__file__).parent.parent / "private_key.pem", "rb") as f:
        private_key = f.read()
    return serialization.load_pem_private_key(private_key, password=None)


def encrypt(text: bytes) -> bytes:
    """
    Encrypts the given text using the public key in batches of 256 bytes where input chunks are 190 bytes.
    """
    encrypted_data = b""
    for i in range(0, len(text), 190):
        chunk = text[i : i + 190]
        encrypted_data += public_key_pem().encrypt(
            chunk,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
    return encrypted_data


def decrypt(encrypted_data: bytes) -> bytes:
    """
    Decrypts the given encrypted data using the private key in batches of 256 bytes where input chunks are 190 bytes.
    """
    decrypted_data = b""
    for i in range(0, len(encrypted_data), 256):
        chunk = encrypted_data[i : i + 256]
        decrypted_data += private_key_pem().decrypt(
            chunk,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
    return decrypted_data
