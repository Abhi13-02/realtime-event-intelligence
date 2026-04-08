import os
import requests
import json
from dotenv import load_dotenv

# Load the API keys from the .env file
load_dotenv()

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
NEWSDATA_KEY = os.getenv("NEWSDATA_KEY")
GUARDIAN_KEY = os.getenv("GUARDIAN_KEY")

def test_newsapi():
    if not NEWSAPI_KEY:
        print("⏭️ Skipping NewsAPI (No key found)")
        return
        
    print("\n🚀 Fetching from: NewsAPI.org")
    url = f"https://newsapi.org/v2/everything?q=Artificial Intelligence&pageSize=1&apiKey={NEWSAPI_KEY}"
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        articles = data.get("articles", [])
        if articles:
            print(json.dumps(articles[0], indent=4))
    else:
        print(f"❌ Error: {response.status_code} - {response.text}")

def test_newsdata():
    if not NEWSDATA_KEY:
        print("⏭️ Skipping Newsdata.io (No key found)")
        return
        
    print("\n🚀 Fetching from: Newsdata.io")
    url = f"https://newsdata.io/api/1/news?apikey={NEWSDATA_KEY}&q=Artificial Intelligence&language=en"
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        results = data.get("results", [])
        if results:
            print(json.dumps(results[0], indent=4))
    else:
        print(f"❌ Error: {response.status_code} - {response.text}")

def test_guardian():
    if not GUARDIAN_KEY:
        print("⏭️ Skipping The Guardian (No key found)")
        return
        
    print("\n🚀 Fetching from: The Guardian Open Platform")
    # Note: We specifically ask for 'trailText' (the summary) in the show-fields parameter
    url = f"https://content.guardianapis.com/search?q=Artificial Intelligence&api-key={GUARDIAN_KEY}&show-fields=trailText,headline"
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        results = data.get("response", {}).get("results", [])
        if results:
            print(json.dumps(results[0], indent=4))
    else:
        print(f"❌ Error: {response.status_code} - {response.text}")

if __name__ == "__main__":
    print("Starting API Tests...")
    test_newsapi()
    print("-" * 60)
    test_newsdata()
    print("-" * 60)
    test_guardian()
    print("-" * 60)