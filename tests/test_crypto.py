from turtle import end_fill
from share_diffs.crypto import encrypt, decrypt

def test_roundtrip():
    test_str = b"Hello World!"
    assert decrypt(encrypt(test_str)) == test_str
    long_teststr = test_str*1000
    assert decrypt(encrypt(long_teststr)) == long_teststr