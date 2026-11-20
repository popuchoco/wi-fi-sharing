"""Seed script for populating Wi-Fi networks in Firestore."""

import datetime
from google.cloud import firestore

PROJECT_ID = "qwiklabs-gcp-04-e87625cd390f"
COLLECTION_NAME = "wifi_networks"

SAMPLE_NETWORKS = [
    {
        "ssid": "Office-Guest",
        "password": "WelcomeGuest2026!",
        "security_type": "WPA2",
        "hidden": False,
        "location": "總部大樓 1F & 3F 訪客大廳",
        "description": "訪客專用高速 Wi-Fi，支援快速掃碼秒連，每日 08:00 至 20:00 開放。",
        "is_active": True,
    },
    {
        "ssid": "MeetingRoom-5F",
        "password": "Meet@Conf5F!",
        "security_type": "WPA2",
        "hidden": False,
        "location": "5F 核心會議室",
        "description": "大型視訊會議與簡報專用高速頻道，具備低延遲特性。",
        "is_active": True,
    },
    {
        "ssid": "Cafe-Lounge",
        "password": "CoffeeFreeWifi",
        "security_type": "WPA2",
        "hidden": False,
        "location": "2F 咖啡休憩區與洽談區",
        "description": "休閒洽談區 Wi-Fi，歡迎員工與貴賓輕鬆連線使用。",
        "is_active": True,
    },
]


def seed():
    print(f"Connecting to Firestore for project: {PROJECT_ID}...")
    db = firestore.Client(project=PROJECT_ID)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    collection_ref = db.collection(COLLECTION_NAME)
    for network in SAMPLE_NETWORKS:
        doc_id = network["ssid"].lower().replace(" ", "-")
        doc_ref = collection_ref.document(doc_id)
        data = {**network, "updated_at": now_iso}
        doc_ref.set(data)
        print(f"✓ Seeded Wi-Fi: {network['ssid']} (Doc ID: {doc_id})")

    print("\nAll sample Wi-Fi networks seeded successfully!")


if __name__ == "__main__":
    seed()
