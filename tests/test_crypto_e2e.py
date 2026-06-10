import base64
import pytest
from hypothesis import given, strategies as st, settings

from app.utils.crypto import (
    generate_rsa_keypair,
    export_public_key_spki,
    export_private_key_pkcs8,
    import_public_key_spki,
    import_private_key_pkcs8,
    encrypt_rsa_oaep,
    decrypt_rsa_oaep,
    generate_aes_gcm_key,
    encrypt_aes_gcm,
    decrypt_aes_gcm,
    derive_key_pbkdf2,
    compute_sas,
    verify_sas,
)


@pytest.fixture
def password():
    return "TestPassword123"


class TestKeyGeneration:
    def test_generate_rsa_keypair(self):
        private_key, public_key = generate_rsa_keypair()
        assert private_key is not None
        assert public_key is not None

    def test_export_import_public_key(self):
        private_key, public_key = generate_rsa_keypair()
        spki = export_public_key_spki(public_key)
        imported = import_public_key_spki(spki)
        assert imported is not None

    def test_export_import_private_key(self):
        private_key, public_key = generate_rsa_keypair()
        pkcs8 = export_private_key_pkcs8(private_key)
        imported = import_private_key_pkcs8(pkcs8)
        assert imported is not None


class TestRSAEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        private_key, public_key = generate_rsa_keypair()
        data = b"Test broadcast key data"
        
        encrypted = encrypt_rsa_oaep(public_key, data)
        decrypted = decrypt_rsa_oaep(private_key, encrypted)
        
        assert decrypted == data

    def test_different_keys_cannot_decrypt(self):
        private_key1, public_key1 = generate_rsa_keypair()
        private_key2, public_key2 = generate_rsa_keypair()
        data = b"Test broadcast key data"
        
        encrypted = encrypt_rsa_oaep(public_key1, data)
        
        with pytest.raises(Exception):
            decrypt_rsa_oaep(private_key2, encrypted)


class TestAESGCM:
    def test_encrypt_decrypt_roundtrip(self):
        key = generate_aes_gcm_key()
        plaintext = b"Hello, World! This is a test message."
        
        encrypted = encrypt_aes_gcm(key, plaintext)
        decrypted = decrypt_aes_gcm(key, encrypted)
        
        assert decrypted == plaintext

    def test_encrypt_decrypt_with_associated_data(self):
        key = generate_aes_gcm_key()
        plaintext = b"Hello, World!"
        associated_data = b"associated"
        
        encrypted = encrypt_aes_gcm(key, plaintext, associated_data)
        decrypted = decrypt_aes_gcm(key, encrypted, associated_data)
        
        assert decrypted == plaintext

    def test_wrong_associated_data_fails(self):
        key = generate_aes_gcm_key()
        plaintext = b"Hello, World!"
        associated_data = b"associated"
        wrong_associated_data = b"wrong"
        
        encrypted = encrypt_aes_gcm(key, plaintext, associated_data)
        
        with pytest.raises(Exception):
            decrypt_aes_gcm(key, encrypted, wrong_associated_data)

    def test_different_key_cannot_decrypt(self):
        key1 = generate_aes_gcm_key()
        key2 = generate_aes_gcm_key()
        plaintext = b"Hello, World!"
        
        encrypted = encrypt_aes_gcm(key1, plaintext)
        
        with pytest.raises(Exception):
            decrypt_aes_gcm(key2, encrypted)


class TestPBKDF2:
    def test_derive_key_deterministic(self):
        password = "TestPassword123"
        salt = b"1234567890123456"
        
        key1 = derive_key_pbkdf2(password, salt)
        key2 = derive_key_pbkdf2(password, salt)
        
        assert key1 == key2
        assert len(key1) == 32

    def test_different_password_different_key(self):
        salt = b"1234567890123456"
        
        key1 = derive_key_pbkdf2("Password1", salt)
        key2 = derive_key_pbkdf2("Password2", salt)
        
        assert key1 != key2

    def test_different_salt_different_key(self):
        password = "TestPassword123"
        
        key1 = derive_key_pbkdf2(password, b"salt123456789012")
        key2 = derive_key_pbkdf2(password, b"different_salt!!")
        
        assert key1 != key2


class TestSASVerification:
    def test_compute_sas_same_for_both_users(self):
        private_key1, public_key1 = generate_rsa_keypair()
        private_key2, public_key2 = generate_rsa_keypair()
        
        spki1 = export_public_key_spki(public_key1)
        spki2 = export_public_key_spki(public_key2)
        
        sas1 = compute_sas(spki1, spki2)
        sas2 = compute_sas(spki2, spki1)
        
        assert sas1 == sas2
        assert len(sas1) == 6
        assert sas1.isdigit()

    def test_verify_sas_correct(self):
        private_key1, public_key1 = generate_rsa_keypair()
        private_key2, public_key2 = generate_rsa_keypair()
        
        spki1 = export_public_key_spki(public_key1)
        spki2 = export_public_key_spki(public_key2)
        
        sas = compute_sas(spki1, spki2)
        result = verify_sas(spki1, spki2, sas)
        
        assert result is True

    def test_verify_sas_incorrect(self):
        private_key1, public_key1 = generate_rsa_keypair()
        private_key2, public_key2 = generate_rsa_keypair()
        
        spki1 = export_public_key_spki(public_key1)
        spki2 = export_public_key_spki(public_key2)
        
        sas = compute_sas(spki1, spki2)
        wrong_sas = str((int(sas) + 1) % 1000000).zfill(6)
        result = verify_sas(spki1, spki2, wrong_sas)
        
        assert result is False

    def test_sas_different_for_different_keys(self):
        private_key1, public_key1 = generate_rsa_keypair()
        private_key2, public_key2 = generate_rsa_keypair()
        private_key3, public_key3 = generate_rsa_keypair()
        
        spki1 = export_public_key_spki(public_key1)
        spki2 = export_public_key_spki(public_key2)
        spki3 = export_public_key_spki(public_key3)
        
        sas1 = compute_sas(spki1, spki2)
        sas2 = compute_sas(spki1, spki3)
        
        assert sas1 != sas2


class TestPropertyBasedCrypto:
    @settings(max_examples=50)
    @given(st.text(min_size=1, max_size=1000))
    def test_encrypt_decrypt_always_works(self, plaintext):
        key = generate_aes_gcm_key()
        data = plaintext.encode()
        
        encrypted = encrypt_aes_gcm(key, data)
        decrypted = decrypt_aes_gcm(key, encrypted)
        
        assert decrypted == data


class TestPropertyBasedBinary:
    @settings(max_examples=20)
    @given(st.binary(min_size=1, max_size=5000))
    def test_encrypt_binary_decrypt_binary(self, data):
        key = generate_aes_gcm_key()
        
        encrypted = encrypt_aes_gcm(key, data)
        decrypted = decrypt_aes_gcm(key, encrypted)
        
        assert decrypted == data


class TestFullKeyExchangeFlow:
    def test_alice_bob_key_exchange(self):
        # Alice generates keys
        alice_private, alice_public = generate_rsa_keypair()
        alice_spki = export_public_key_spki(alice_public)
        alice_broadcast = generate_aes_gcm_key()
        
        # Bob generates keys
        bob_private, bob_public = generate_rsa_keypair()
        bob_spki = export_public_key_spki(bob_public)
        
        # Alice encrypts her broadcast key for Bob
        encrypted_for_bob = encrypt_rsa_oaep(bob_public, alice_broadcast)
        
        # Bob decrypts Alice's broadcast key
        decrypted_by_bob = decrypt_rsa_oaep(bob_private, encrypted_for_bob)
        
        assert decrypted_by_bob == alice_broadcast
        
        # They can now communicate using AES-GCM
        alice_msg = b"Hello Bob!"
        encrypted_msg = encrypt_aes_gcm(alice_broadcast, alice_msg)
        decrypted_msg = decrypt_aes_gcm(decrypted_by_bob, encrypted_msg)
        
        assert decrypted_msg == alice_msg
        
        # SAS verification
        sas = compute_sas(alice_spki, bob_spki)
        assert verify_sas(alice_spki, bob_spki, sas)
        assert verify_sas(bob_spki, alice_spki, sas)