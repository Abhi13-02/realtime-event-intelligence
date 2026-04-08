import feedparser
import json
import uuid

# The list of RSS feeds your team suggested
RSS_FEEDS = {
    "BBC": "https://feeds.bbci.co.uk/news/rss.xml",
    "NYT": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
    "CNN": "http://rss.cnn.com/rss/cnn_topstories.rss",
    "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml"
}

def test_fetch_rss():
    for source_name, feed_url in RSS_FEEDS.items():
        print(f"\n🚀 Fetching from: {source_name}")
        
        # feedparser automatically downloads and parses the XML
        feed = feedparser.parse(feed_url)
        
        # Check if the feed is broken or empty
        if not feed.entries:
            print("❌ Failed to fetch or no articles found.")
            continue
            
        print(f"✅ Successfully fetched {len(feed.entries)} articles.")
        print("Here is what the newest article looks like in your format:\n")
        
        # Grab the very first (newest) article
        latest_article = feed.entries[0]
        
        # Map the RSS tags to your exact dictionary schema
        formatted_article = {
            "url": latest_article.get("link", ""),
            "headline": latest_article.get("title", ""),
            # RSS sometimes uses 'summary' and sometimes 'description'
            "content": latest_article.get("summary", latest_article.get("description", "")), 
            "source_id": str(uuid.uuid4()), # Creating a dummy source_id for the test
            "published_at": latest_article.get("published", "")
        }
        
        # Print the resulting JSON
        print(json.dumps(formatted_article, indent=4))
        print("-" * 60)

if __name__ == "__main__":
    test_fetch_rss()