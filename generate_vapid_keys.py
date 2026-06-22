import base64

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


PRIVATE_KEY_FILE = "vapid_private_key.pem"


def base64url_no_padding(data):
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def main():
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_bytes = private_key.public_key().public_bytes(
        Encoding.X962,
        PublicFormat.UncompressedPoint,
    )
    private_pem = private_key.private_bytes(
        Encoding.PEM,
        PrivateFormat.PKCS8,
        NoEncryption(),
    )

    with open(PRIVATE_KEY_FILE, "wb") as file:
        file.write(private_pem)

    print(f"VAPID_PUBLIC_KEY={base64url_no_padding(public_bytes)}")
    print(f"VAPID_PRIVATE_KEY_FILE={PRIVATE_KEY_FILE}")


if __name__ == "__main__":
    main()
