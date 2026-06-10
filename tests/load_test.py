import base64
import json
import random
import secrets
import string
from locust import HttpUser, task, between, events
from locust.contrib.socketio import SocketIOUser
import socketio


class SecureMessengerUser(SocketIOUser):
    wait_time = between(1, 3)
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user_id = None
        self.access_token = None
        self.username = None
        self.connected = False
        
    def on_start(self):
        self.register_and_login()
        self.connect_websocket()
        
    def get_current_time(self):
        import time
        return time.time()
        
    def register_and_login(self):
        self.username = f"user_{random.randint(10000, 99999)}"
        password = "TestPassword123"
        
        # Generate keys for registration
        import asyncio
        from app.utils.crypto import (
            generate_rsa_keypair,
            export_public_key_spki,
            export_private_key_pkcs8,
            generate_aes_gcm_key,
        )
        
        private_key, public_key = generate_rsa_keypair()
        public_key_spki = export_public_key_spki(public_key)
        private_key_pkcs8 = export_private_key_pkcs8(private_key)
        broadcast_key = generate_aes_gcm_key()
        
        # Encrypt private key with password
        from app.utils.crypto import derive_key_pbkdf2, encrypt_aes_gcm
        salt = secrets.token_bytes(16)
        derived_key = derive_key_pbkdf2(password, salt)
        encrypted_private = encrypt_aes_gcm(derived_key, private_key_pkcs8)
        encrypted_private_blob = salt + encrypted_private
        
        response = self.client.post("/api/v1/auth/register", json={
            "username": self.username,
            "password": password,
            "public_key": base64.b64encode(public_key_spki).decode(),
            "encrypted_private_key": base64.b64encode(encrypted_private_blob).decode(),
            "broadcast_key": base64.b64encode(broadcast_key).decode(),
        })
        
        if response.status_code == 200:
            data = response.json()
            self.access_token = data["access_token"]
            self.user_id = data["user_id"]
        else:
            # Try login if user exists
            response = self.client.post("/api/v1/auth/login", json={
                "username": self.username,
                "password": password,
            })
            if response.status_code == 200:
                data = response.json()
                self.access_token = data["access_token"]
                self.user_id = data["user_id"]
    
    def connect_websocket(self):
        if not self.access_token:
            return
            
        try:
            self.connect(
                f"ws://localhost:8111/socket.io/?token={self.access_token}",
                transports=["websocket"],
            )
            self.connected = True
        except Exception as e:
            self.environment.events.request.fire(
                request_type="WS",
                name="connect",
                response_time=0,
                response_length=0,
                exception=e,
            )
    
    @task(10)
    def send_message(self):
        if not self.connected or not self.user_id:
            return
            
        # Find another user to message (simplified - in reality would need permission)
        target_id = random.randint(1, 100)
        if target_id == self.user_id:
            target_id = (target_id % 100) + 1
            
        message = {
            "receiver_id": target_id,
            "encrypted_content": base64.b64encode(f"Test message from {self.username}".encode()).decode(),
            "attachment_ids": [],
        }
        
        start_time = self.get_current_time()
        try:
            self.emit("send_message", message)
            self.environment.events.request.fire(
                request_type="WS",
                name="send_message",
                response_time=(self.get_current_time() - start_time) * 1000,
                response_length=len(json.dumps(message)),
                exception=None,
            )
        except Exception as e:
            self.environment.events.request.fire(
                request_type="WS",
                name="send_message",
                response_time=(self.get_current_time() - start_time) * 1000,
                response_length=0,
                exception=e,
            )
    
    @task(5)
    def typing_indicator(self):
        if not self.connected or not self.user_id:
            return
            
        target_id = random.randint(1, 100)
        if target_id == self.user_id:
            target_id = (target_id % 100) + 1
            
        self.emit("typing", {"receiver_id": target_id, "is_typing": True})
        self.emit("typing", {"receiver_id": target_id, "is_typing": False})
    
    @task(3)
    def join_room(self):
        if not self.connected or not self.user_id:
            return
            
        target_id = random.randint(1, 100)
        if target_id == self.user_id:
            target_id = (target_id % 100) + 1
            
        self.emit("join_room", {"target_id": target_id})
    
    @task(2)
    def get_user_status(self):
        if not self.connected or not self.user_id:
            return
            
        target_id = random.randint(1, 100)
        if target_id == self.user_id:
            target_id = (target_id % 100) + 1
            
        self.emit("get_user_status", {"user_id": target_id})
    
    @task(1)
    def request_permission(self):
        if not self.connected or not self.user_id:
            return
            
        target_id = random.randint(1, 100)
        if target_id == self.user_id:
            target_id = (target_id % 100) + 1
            
        self.emit("permission_requested", {"owner_id": target_id})
    
    def on_message(self, data):
        pass
    
    def on_new_message(self, data):
        pass
    
    def on_typing(self, data):
        pass
    
    def on_user_status(self, data):
        pass
    
    def on_permission_request(self, data):
        pass
    
    def on_permission_response(self, data):
        pass


class RestApiUser(HttpUser):
    wait_time = between(1, 5)
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.access_token = None
        self.user_id = None
        
    def on_start(self):
        self.register_and_login()
        
    def register_and_login(self):
        self.username = f"rest_user_{random.randint(10000, 99999)}"
        password = "TestPassword123"
        
        import asyncio
        from app.utils.crypto import (
            generate_rsa_keypair,
            export_public_key_spki,
            export_private_key_pkcs8,
            generate_aes_gcm_key,
            derive_key_pbkdf2,
            encrypt_aes_gcm,
        )
        
        private_key, public_key = generate_rsa_keypair()
        public_key_spki = export_public_key_spki(public_key)
        private_key_pkcs8 = export_private_key_pkcs8(private_key)
        broadcast_key = generate_aes_gcm_key()
        
        salt = secrets.token_bytes(16)
        derived_key = derive_key_pbkdf2(password, salt)
        encrypted_private = encrypt_aes_gcm(derived_key, private_key_pkcs8)
        encrypted_private_blob = salt + encrypted_private
        
        response = self.client.post("/api/v1/auth/register", json={
            "username": self.username,
            "password": password,
            "public_key": base64.b64encode(public_key_spki).decode(),
            "encrypted_private_key": base64.b64encode(encrypted_private_blob).decode(),
            "broadcast_key": base64.b64encode(broadcast_key).decode(),
        })
        
        if response.status_code == 200:
            data = response.json()
            self.access_token = data["access_token"]
            self.user_id = data["user_id"]
    
    @task(5)
    def get_user_list(self):
        if not self.access_token:
            return
            
        headers = {"Authorization": f"Bearer {self.access_token}"}
        self.client.get("/api/v1/users", headers=headers)
    
    @task(3)
    def search_users(self):
        if not self.access_token:
            return
            
        headers = {"Authorization": f"Bearer {self.access_token}"}
        self.client.get("/api/v1/users/search?q=test", headers=headers)
    
    @task(2)
    def get_message_history(self):
        if not self.access_token:
            return
            
        headers = {"Authorization": f"Bearer {self.access_token}"}
        target_id = random.randint(1, 100)
        self.client.get(f"/api/v1/messages/{target_id}", headers=headers)
    
    @task(1)
    def send_message_rest(self):
        if not self.access_token:
            return
            
        headers = {"Authorization": f"Bearer {self.access_token}"}
        target_id = random.randint(1, 100)
        self.client.post(f"/api/v1/messages/{target_id}/send", json={
            "encrypted_content": base64.b64encode(b"REST API message").decode(),
            "attachment_ids": [],
        }, headers=headers)
    
    @task(2)
    def get_permissions(self):
        if not self.access_token:
            return
            
        headers = {"Authorization": f"Bearer {self.access_token}"}
        self.client.get("/api/v1/permissions/approved", headers=headers)
        self.client.get("/api/v1/permissions/incoming", headers=headers)
    
    @task(1)
    def request_permission(self):
        if not self.access_token:
            return
            
        headers = {"Authorization": f"Bearer {self.access_token}"}
        target_id = random.randint(1, 100)
        self.client.post(f"/api/v1/permissions/request/{target_id}", headers=headers)