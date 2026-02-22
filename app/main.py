import requests
from fastapi import FastAPI

app = FastAPI(title="RealTime Event Intelligence")

BASE_URL = "https://hacker-news.firebaseio.com/v0"

@app.get("/")
def health():
    return {"status": "System Running"}

@app.get("/fetch")
def fetch(limit: int = 5):
    # Step 1: Get top story IDs
    ids_response = requests.get(f"{BASE_URL}/topstories.json")
    ids = ids_response.json()[:limit]

    stories = []

    # Step 2: Fetch story details
    for story_id in ids:
        story_response = requests.get(f"{BASE_URL}/item/{story_id}.json")
        data = story_response.json()

        stories.append({
            "title": data.get("title"),
            "url": data.get("url"),
            "score": data.get("score"),
            "time": data.get("time")
        })

    return {"stories": stories}