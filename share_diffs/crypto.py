from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.types import (
    PublicKeyTypes,
    PrivateKeyTypes,
)
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from functools import lru_cache


@lru_cache
def public_key_pem() -> PublicKeyTypes:
    with open("public_key.pem", "rb") as f:
        public_pem = f.read()
    return serialization.load_pem_public_key(public_pem)


@lru_cache
def private_key_pem() -> PrivateKeyTypes:
    with open("private_key.pem", "rb") as f:
        private_key = f.read()
    return serialization.load_pem_private_key(private_key, password=None)


def encrypt(text: bytes) -> bytes:
    encrypted_data = public_key_pem().encrypt(
        text,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return encrypted_data


def decrypt(encrypted_data: bytes) -> str:
    decrypted_data = private_key_pem().decrypt(
        encrypted_data,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return decrypted_data.decode()


# # Example usage for a list of repositories
# repos = [
#     {"foldername": "/path/to/repo1", "last_commit": "abc123"},
#     # Add more repositories as needed
# ]

# generate_combined_encrypted_patch(repos)
