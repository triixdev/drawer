import os
from drawer import kms
from drawer.store import Store


class FakeKMS:
    """Stands in for AWS KMS: 'wraps' a key by reversing its bytes."""
    def __init__(self): self.calls = []
    def generate_data_key(self, **kw):
        self.calls.append(("generate", kw))
        plain = os.urandom(32)
        return {"Plaintext": plain, "CiphertextBlob": plain[::-1]}
    def decrypt(self, **kw):
        self.calls.append(("decrypt", kw))
        return {"Plaintext": kw["CiphertextBlob"][::-1]}


def test_key_is_generated_once_then_unwrapped(tmp_path):
    fake = FakeKMS()
    first = kms.master_key(tmp_path, "alias/drawer", fake)
    assert len(first) == 32 and (tmp_path / "master.kms").exists()
    second = kms.master_key(tmp_path, "alias/drawer", fake)
    assert second == first
    assert [c[0] for c in fake.calls] == ["generate", "decrypt"]
    assert all(c[1]["EncryptionContext"] == {"app": "drawer"} for c in fake.calls)


def test_plaintext_key_never_written_to_disk(tmp_path):
    fake = FakeKMS()
    key = kms.master_key(tmp_path, "alias/drawer", fake)
    for f in tmp_path.iterdir():
        assert key not in f.read_bytes()
    assert not (tmp_path / "key").exists()


def test_store_works_with_a_kms_master(tmp_path):
    key = kms.master_key(tmp_path, "alias/drawer", FakeKMS())
    s = Store(str(tmp_path / "t.db"), key)
    hid = s.create_household("Home", "river copper maple slate")
    s.add_entry(hid, "place", {"name": "main water valve", "where": "behind the heater"})
    assert s.entries(hid)[0]["where"] == "behind the heater"
    assert b"heater" not in (tmp_path / "t.db").read_bytes()
