# backend/scripts/test_firestore.py
import firebase_admin
from firebase_admin import credentials, firestore

cred = credentials.Certificate("serviceAccount.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

ref = db.collection("_ping").document("test")
ref.set({"ok": True})
print("읽기 결과:", ref.get().to_dict())