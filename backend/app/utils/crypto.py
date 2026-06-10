import base64
import hashlib
import secrets
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def generate_rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    return private_key, public_key


def export_public_key_spki(public_key):
    return public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def export_private_key_pkcs8(private_key):
    return private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def import_public_key_spki(spki_bytes):
    return serialization.load_der_public_key(spki_bytes)


def import_private_key_pkcs8(pkcs8_bytes):
    return serialization.load_der_private_key(pkcs8_bytes, password=None)


def encrypt_rsa_oaep(public_key, data):
    return public_key.encrypt(data, padding.OAEP(
        mgf=padding.MGF1(algorithm=hashlib.sha256()),
        algorithm=hashlib.sha256(),
        label=None,
    ))


def decrypt_rsa_oaep(private_key, data):
    return private_key.decrypt(data, padding.OAEP(
        mgf=padding.MGF1(algorithm=hashlib.sha256()),
        algorithm=hashlib.sha256(),
        label=None,
    ))


def generate_aes_gcm_key():
    return secrets.token_bytes(32)


def encrypt_aes_gcm(key, plaintext, associated_data=None):
    aesgcm = AESGCM(key)
    nonce = secrets.token_bytes(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data)
    return nonce + ciphertext


def decrypt_aes_gcm(key, nonce_ciphertext, associated_data=None):
    aesgcm = AESGCM(key)
    nonce = nonce_ciphertext[:12]
    ciphertext = nonce_ciphertext[12:]
    return aesgcm.decrypt(nonce, ciphertext, associated_data)


def derive_key_pbkdf2(password, salt, iterations=600000):
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    kdf = PBKDF2HMAC(
        algorithm=hashlib.sha256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    return kdf.derive(password.encode())


def compute_sas(user_pk_spki, contact_pk_spki):
    combined = user_pk_spki + contact_pk_spki
    hash_bytes = hashlib.sha256(combined).digest()
    sas_number = hash_bytes[0] + (hash_bytes[1] << 8) + (hash_bytes[2] << 16) + (hash_bytes[3] << 24)
    return f"{sas_number % 1000000:06d}"


def format_sas_for_display(sas):
    return f"{sas[:3]} {sas[3:]}"


def verify_sas(user_pk_spki, contact_pk_spki, expected_sas):
    computed = compute_sas(user_pk_spki, contact_pk_spki)
    return secrets.compare_digest(computed, expected_sas)