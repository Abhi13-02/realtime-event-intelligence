import urllib.request
import xml.etree.ElementTree as ET
import os
import csv
from sentence_transformers import SentenceTransformer
import numpy as np

os.environ["HF_HUB_OFFLINE"] = "0"

FEEDS = {
    "War and geopolitics": "http://feeds.bbci.co.uk/news/world/rss.xml",
    "Technology": "http://feeds.bbci.co.uk/news/technology/rss.xml",
    "Economy": "http://feeds.bbci.co.uk/news/business/rss.xml",
    "Science": "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml"
}

# ONLY context_heavy descriptions
TOPICS = {
    "War and geopolitics": "The geopolitical landscape is shifting rapidly as conflicts erupt in various regions. Diplomatic efforts, such as ceasefires and treaties, are crucial for international stability, while military deployments and refugee crises continue to challenge global security.",
    "Technology": "The rapid pace of technological innovation is transforming industries. Breakthroughs in artificial intelligence, cloud computing, and semiconductor manufacturing are enabling new capabilities while raising concerns about data privacy and cybersecurity.",
    "Economy": "Global financial markets are reacting to changing economic policies. Central banks are adjusting interest rates to combat inflation while avoiding recession, as businesses navigate shifting trade dynamics and strive for steady revenue growth.",
    "Science": "Scientific research continues to expand our understanding of the universe. From exploring distant planets and studying cosmic phenomena to unraveling the complexities of biology and addressing the pressing challenges of climate change and environmental degradation."
}

MODELS = [
    "all-mpnet-base-v2",
    "BAAI/bge-base-en-v1.5"
]

def fetch_articles():
    articles = []
    for category, url in FEEDS.items():
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                xml_data = response.read()
            root = ET.fromstring(xml_data)
            for item in root.findall('.//item'):
                title = item.find('title').text if item.find('title') is not None else ''
                desc = item.find('description').text if item.find('description') is not None else ''
                if title or desc:
                    articles.append({
                        "category": category,
                        "headline": title,
                        "content": desc,
                        "text": f"{title}. {desc}"
                    })
        except Exception as e:
            print(f"Error fetching {url}: {e}")
    return articles

def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom > 1e-9 else 0.0

def main():
    print("Fetching articles...")
    articles = fetch_articles()
    print(f"Fetched {len(articles)} articles.")

    csv_rows = []
    headers = [
        "Model", "Article Headline", "True Category", "Predicted Category", "Correct?",
        "Score: War & Geopolitics", "Score: Technology", "Score: Economy", "Score: Science"
    ]
    csv_rows.append(headers)

    for model_name in MODELS:
        print(f"\nLoading model: {model_name}")
        model = SentenceTransformer(model_name)
        
        topic_prefix = "Represent this sentence for searching relevant passages: " if "bge" in model_name.lower() else ""

        print(f"Encoding topics (context_heavy only)...")
        topic_embs = {}
        topic_names = list(TOPICS.keys())
        for topic_name, desc_text in TOPICS.items():
            topic_embs[topic_name] = model.encode(f"{topic_prefix}{desc_text}", show_progress_bar=False)
                
        print(f"Encoding articles...")
        article_texts = [a["text"] for a in articles]
        article_embs = model.encode(article_texts, batch_size=32, show_progress_bar=False)
        
        correct_predictions = 0
        
        print("Scoring...")
        for i, article in enumerate(articles):
            true_cat = article["category"]
            a_emb = article_embs[i]
            
            scores = {}
            for t_name in topic_names:
                scores[t_name] = cosine_sim(a_emb, topic_embs[t_name])
            
            best_cat = max(scores, key=scores.get)
            is_correct = (best_cat == true_cat)
            
            if is_correct:
                correct_predictions += 1
            
            row = [
                model_name,
                article["headline"],
                true_cat,
                best_cat,
                "YES" if is_correct else "NO",
                f"{scores['War and geopolitics']:.4f}",
                f"{scores['Technology']:.4f}",
                f"{scores['Economy']:.4f}",
                f"{scores['Science']:.4f}"
            ]
            csv_rows.append(row)
            
        accuracy = correct_predictions / len(articles) if articles else 0
        print(f"Model {model_name} Accuracy (context_heavy): {accuracy*100:.2f}% ({correct_predictions}/{len(articles)})")

    with open("detailed_benchmark_results.csv", "w", newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerows(csv_rows)
        
    print("\nDetailed results written to detailed_benchmark_results.csv")

if __name__ == "__main__":
    main()
