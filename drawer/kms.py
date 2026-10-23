"""Optional: keep Drawer's master key wrapped by AWS KMS (envelope encryption).

With DRAWER_KMS_KEY_ID set, the master key is a KMS data key. Only the wrapped
copy sits on disk (master.kms). On each start the server asks KMS to unwrap it,
so a stolen disk or a leaked repo copy does not contain a usable key.
No household data is ever sent to AWS here, only the wrapped key.
"""
import os
from pathlib import Path

CONTEXT = {"app": "drawer"}


def _client(client=None):
    if client is not None:
        return client
    import boto3
    return boto3.client("kms", region_name=os.environ.get("AWS_REGION"))


def master_key(home: Path, key_id: str, client=None) -> bytes:
    kms = _client(client)
    wrapped = home / "master.kms"
    if wrapped.exists():
        r = kms.decrypt(CiphertextBlob=wrapped.read_bytes(), KeyId=key_id, EncryptionContext=CONTEXT)
        return r["Plaintext"]
    home.mkdir(parents=True, exist_ok=True)
    r = kms.generate_data_key(KeyId=key_id, KeySpec="AES_256", EncryptionContext=CONTEXT)
    wrapped.write_bytes(r["CiphertextBlob"])
    return r["Plaintext"]


if __name__ == "__main__":
    # python -m drawer.kms : proves KMS access without printing any key material
    from .store import _home
    key_id = os.environ.get("DRAWER_KMS_KEY_ID")
    if not key_id:
        raise SystemExit("Set DRAWER_KMS_KEY_ID first.")
    key = master_key(_home(), key_id)
    print(f"OK: master key unwrapped by AWS KMS ({len(key)} bytes). Wrapped copy: {_home() / 'master.kms'}")
