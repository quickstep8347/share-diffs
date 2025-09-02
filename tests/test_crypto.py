from turtle import end_fill
from share_diffs.crypto import encrypt, decrypt

def test_roundtrip():
    test_str = "Hello World!"
    assert decrypt(encrypt(test_str.encode())) == test_str