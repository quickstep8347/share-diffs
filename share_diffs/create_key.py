from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend


def generate_rsa_key_pair(key_size=2048):
    # Generate private key
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=key_size, backend=default_backend()
    )

    # Serialize private key
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )

    # Get public key from private key
    public_key = private_key.public_key()

    # Serialize public key
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    return private_pem, public_pem


if __name__ == "__main__":
    private_pem, public_pem = generate_rsa_key_pair()

    # Write private key
    with open("private_key.pem", "wb") as f:
        f.write(private_pem)

    # Write public key
    with open("public_key.pem", "wb") as f:
        f.write(public_pem)

    print("RSA key pair generated and saved to disk.")
