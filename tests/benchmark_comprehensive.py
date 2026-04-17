import os
import re
import csv
import random
import numpy as np
import feedparser
from sentence_transformers import SentenceTransformer
from typing import List, Dict

# Set fixed seed for reproducibility in sampling
random.seed(42)

TOPICS = {
    "Artificial Intelligence": {
        "formats": {
            "Format A (Comprehensive)": [
                "Artificial intelligence, machine learning, and neural networks are transforming industries. This includes generative AI like ChatGPT, large language models, automation of jobs, and the economic impact of tech companies investing in AI infrastructure, as well as debates around regulation and ethics."
            ],
            "Format B (Subdomains)": [
                "The rapid development and deployment of Generative AI systems and Large Language Models by major tech companies, focusing on their increasing capabilities in natural language understanding, reasoning, and multi-modal generation.",
                "The broader impact of artificial intelligence on the global economy, specifically highlighting the ongoing automation of cognitive tasks, significant shifts in the labor market, and concerns about widespread job displacement across various industries.",
                "The massive surge in capital expenditure by technology giants investing heavily in specialized AI infrastructure, building next-generation data centers, and procuring advanced semiconductor chips to power artificial intelligence training and inference.",
                "The ongoing international debates among lawmakers and policymakers regarding the implementation of comprehensive regulatory frameworks, safety standards, and ethical guidelines designed to govern the development and mitigate the risks of advanced artificial intelligence."
            ],
            "Format C (News-Like)": [
                "Major technology company officially releases highly anticipated new generative AI model, boasting significant improvements in reasoning capabilities and multi-modal processing.",
                "Comprehensive new economic report warns of significant AI-driven job displacement across multiple white-collar industries over the next decade.",
                "Leading tech giant formally announces a multi-billion dollar strategic investment to build massive new AI data centers and acquire specialized computing infrastructure.",
                "International lawmakers intensely debate the implementation of a strict new AI regulation framework and comprehensive safety standards to curb the risks of autonomous systems."
            ],
            "Format D (Short)": [
                "Generative AI development",
                "AI economic impact",
                "AI infrastructure investment",
                "AI ethics and regulation"
            ]
        },
        "keywords": [
            r'\bai\b', r'artificial intelligence', r'machine learning', r'chatgpt',
            r'openai', r'generative ai', r'\bllm\b', r'\bllms\b', r'neural network',
            r'deep learning', r'nvidia', r'anthropic', r'gemini'
        ]
    },
    "World War and Geopolitics": {
        "formats": {
            "Format A (Comprehensive)": [
                "The geopolitical landscape is shifting rapidly as global conflicts erupt and international relations become strained. This includes ongoing military deployments, proxy wars, diplomatic efforts such as ceasefires and treaties, economic sanctions, the role of international organizations like the UN and NATO, and the resulting humanitarian crises and refugee movements."
            ],
            "Format B (Subdomains)": [
                "Ongoing military deployments, armed conflicts, and the strategic positioning of global military forces in volatile regions.",
                "The implementation of economic sanctions, trade embargoes, and the use of financial instruments as geopolitical weapons.",
                "Diplomatic negotiations, international treaties, peace talks, and the efforts of organizations like the UN and NATO to maintain stability.",
                "The severe humanitarian consequences of war, including mass refugee migrations, civilian casualties, and international aid efforts."
            ],
            "Format C (News-Like)": [
                "Global leaders convene for emergency summit as regional conflict escalates and ceasefire negotiations stall.",
                "International coalition announces sweeping new economic sanctions targeting military infrastructure and defense contractors.",
                "Hundreds of thousands displaced as heavy fighting breaks out along contested border, triggering a severe humanitarian crisis.",
                "Defense alliance deploys additional troops and advanced missile defense systems in response to rising geopolitical tensions."
            ],
            "Format D (Short)": [
                "Military deployments and armed conflicts",
                "Economic sanctions and trade embargoes",
                "International diplomacy and peace talks",
                "Humanitarian crises and refugee movements"
            ]
        },
        "keywords": [
            r'\bwar\b', r'geopolitics', r'military', r'sanctions', r'ceasefire', 
            r'\bnato\b', r'un security council', r'troops', r'missile', r'diplomat', 
            r'diplomacy', r'refugee', r'embargo', r'proxy war', r'peace talks', r'invasion', r'defense'
        ]
    },
    "Science and Discovery": {
        "formats": {
            "Format A (Comprehensive)": [
                "Scientific research continues to push the boundaries of human knowledge, encompassing breakthroughs in biology, space exploration, physics, and medicine. This includes the discovery of new celestial bodies, advancements in genetic engineering, studying the effects of climate change, and the development of novel medical treatments."
            ],
            "Format B (Subdomains)": [
                "Astronomical discoveries, space exploration missions, and the observation of new planetary systems and cosmic phenomena.",
                "Breakthroughs in biological research, genetic engineering, molecular biology, and the study of complex ecosystems.",
                "The physical sciences, exploring quantum mechanics, particle physics, and fundamental forces of the universe.",
                "Medical advancements, the development of new treatments, vaccines, and ongoing research into human health and disease."
            ],
            "Format C (News-Like)": [
                "Astronomers successfully capture unprecedented images of distant exoplanet using next-generation orbital telescope.",
                "Researchers publish groundbreaking new study detailing a revolutionary method for targeted gene editing.",
                "Physicists announce major breakthrough in quantum computing stability after years of experimental trials.",
                "Clinical trial results show highly promising efficacy for experimental new Alzheimer's disease treatment."
            ],
            "Format D (Short)": [
                "Space exploration and astronomy",
                "Genetics and biological research",
                "Physics and quantum mechanics",
                "Medical research and treatments"
            ]
        },
        "keywords": [
            r'space', r'astronomy', r'physics', r'biology', r'medical', r'genetic', 
            r'climate change', r'planet', r'galaxy', r'scientist', r'researcher', 
            r'vaccine', r'dinosaur', r'fossil', r'archeology', r'nasa', r'telescope'
        ]
    },
    "Sports": {
        "formats": {
            "Format A (Comprehensive)": [
                "The world of competitive sports brings together athletes and fans globally, featuring intense matches, championship tournaments, and record-breaking performances. This encompasses professional leagues, international competitions like the Olympics, dramatic player transfers, coaching changes, and the ongoing pursuit of athletic excellence."
            ],
            "Format B (Subdomains)": [
                "High-stakes professional leagues, seasonal tournaments, and the intense competition for championship titles.",
                "International sporting events, national team rivalries, and global spectacles like the Olympic Games or World Cup.",
                "Athlete performance, record-breaking achievements, and the physical conditioning required for elite sports.",
                "The business of sports, including lucrative player transfers, major contract signings, and controversial coaching changes."
            ],
            "Format C (News-Like)": [
                "Underdog team secures dramatic last-minute victory to clinch the national championship title.",
                "Star athlete shatters long-standing world record during highly anticipated international competition.",
                "Major professional sports league announces controversial new rules aimed at increasing player safety.",
                "Record-breaking multi-million dollar contract signed as star player transfers to rival club."
            ],
            "Format D (Short)": [
                "Championship tournaments and matches",
                "International sporting events",
                "Athlete performance and records",
                "Player transfers and sports business"
            ]
        },
        "keywords": [
            r'football', r'soccer', r'basketball', r'tennis', r'golf', r'tournament', 
            r'champion', r'olympics', r'match', r'league', r'athlete', r'stadium', 
            r'premier league', r'nfl', r'nba', r'fifa', r'wimbledon', r'formula 1'
        ]
    },
    "Economy and Finance": {
        "formats": {
            "Format A (Comprehensive)": [
                "Global financial markets are constantly reacting to changing economic indicators, corporate performance, and government monetary policies. This includes central bank decisions on interest rates, stock market fluctuations, inflation reports, corporate earnings, trade agreements, and the broader impacts of international commerce."
            ],
            "Format B (Subdomains)": [
                "Central bank monetary policies, adjustments to baseline interest rates, and national strategies for managing inflation.",
                "Stock market volatility, daily trading indices, and the performance of global financial exchanges.",
                "Corporate earnings reports, quarterly financial results, and the strategic business decisions of multinational companies.",
                "International trade dynamics, global supply chain disruptions, and the economic impact of tariffs and trade agreements."
            ],
            "Format C (News-Like)": [
                "Central bank officially announces unexpected interest rate hike in continued effort to combat persistent inflation.",
                "Global stock markets experience significant sell-off following release of worse-than-expected economic data.",
                "Major multinational corporation reports record quarterly profits driven by strong international sales.",
                "New international trade agreement signed, significantly lowering tariffs and aiming to boost global commerce."
            ],
            "Format D (Short)": [
                "Monetary policy and interest rates",
                "Stock market and financial exchanges",
                "Corporate earnings and business strategy",
                "International trade and supply chains"
            ]
        },
        "keywords": [
            r'economy', r'inflation', r'interest rate', r'stock market', r'wall street', 
            r'central bank', r'gdp', r'recession', r'corporate earnings', r'investors', 
            r'financial', r'trade', r'tariff', r'export', r'banking', r'bank of england', r'federal reserve'
        ]
    }
}

FEEDS = [
    "http://feeds.bbci.co.uk/news/world/rss.xml",
    "http://feeds.bbci.co.uk/news/uk/rss.xml",
    "http://feeds.bbci.co.uk/news/business/rss.xml",
    "http://feeds.bbci.co.uk/news/politics/rss.xml",
    "http://feeds.bbci.co.uk/news/health/rss.xml",
    "http://feeds.bbci.co.uk/news/education/rss.xml",
    "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    "http://feeds.bbci.co.uk/news/technology/rss.xml",
    "http://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml",
    "https://feeds.skynews.com/feeds/rss/home.xml",
    "https://feeds.skynews.com/feeds/rss/technology.xml",
    "https://feeds.skynews.com/feeds/rss/business.xml",
    "https://feeds.skynews.com/feeds/rss/politics.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/Sports.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/Science.xml"
]

def fetch_base_articles() -> List[Dict]:
    print("Fetching massive RSS feed pool...")
    articles = []
    seen_titles = set()
    
    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                title = entry.get('title', '')
                desc = entry.get('description', '')
                
                if title in seen_titles:
                    continue
                seen_titles.add(title)
                
                articles.append({
                    "headline": title,
                    "description": desc,
                    "text": f"{title}. {desc}"
                })
        except Exception as e:
            print(f"Failed to fetch {url}: {e}")
            
    print(f"Total unique real articles fetched: {len(articles)}")
    return articles

def create_balanced_dataset_for_topic(base_articles: List[Dict], topic_name: str, topic_data: Dict) -> List[Dict]:
    relevant_articles = []
    irrelevant_articles = []
    
    for a in base_articles:
        text_to_search = a["text"].lower()
        is_relevant = False
        for kw in topic_data["keywords"]:
            if re.search(kw, text_to_search):
                is_relevant = True
                break
        
        # We need a copy because 'is_relevant' is topic-specific
        art_copy = {
            "headline": a["headline"],
            "description": a["description"],
            "text": a["text"],
            "is_relevant": is_relevant
        }
        
        if is_relevant:
            relevant_articles.append(art_copy)
        else:
            irrelevant_articles.append(art_copy)
            
    num_relevant = len(relevant_articles)
    
    # Balance 1:1
    if num_relevant > 0:
        if num_relevant <= len(irrelevant_articles):
            sampled_irrelevant = random.sample(irrelevant_articles, num_relevant)
        else:
            sampled_irrelevant = irrelevant_articles
    else:
        sampled_irrelevant = []
        print(f"WARNING: No relevant articles found for {topic_name}!")
        
    final_dataset = relevant_articles + sampled_irrelevant
    random.shuffle(final_dataset)
    return final_dataset

def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom > 1e-9 else 0.0

def evaluate_format(articles: List[Dict], query_embs: np.ndarray, article_embs: np.ndarray) -> Dict:
    relevant_scores = []
    irrelevant_scores = []
    article_scores = [] # Track scores sequentially for CSV
    
    for i, article in enumerate(articles):
        a_emb = article_embs[i]
        sims = [cosine_sim(a_emb, q_emb) for q_emb in query_embs]
        score = max(sims)
        
        article_scores.append(score)
        
        if article["is_relevant"]:
            relevant_scores.append(score)
        else:
            irrelevant_scores.append(score)
            
    metrics = {
        "mean_relevant": np.mean(relevant_scores) if relevant_scores else 0,
        "std_relevant": np.std(relevant_scores) if relevant_scores else 0,
        "mean_irrelevant": np.mean(irrelevant_scores) if irrelevant_scores else 0,
        "std_irrelevant": np.std(irrelevant_scores) if irrelevant_scores else 0,
        "article_scores": article_scores
    }
    metrics["separation_gap"] = metrics["mean_relevant"] - metrics["mean_irrelevant"]
    
    best_thresh = 0.0
    best_f1 = 0.0
    best_tp = 0
    best_fp = 0
    best_fn = 0
    
    if relevant_scores and irrelevant_scores:
        thresholds = np.arange(0.0, 1.0, 0.01)
        for t in thresholds:
            tp = sum(1 for s in relevant_scores if s >= t)
            fn = len(relevant_scores) - tp
            fp = sum(1 for s in irrelevant_scores if s >= t)
            tn = len(irrelevant_scores) - fp
            
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0
            f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
            
            if f1 > best_f1:
                best_f1 = f1
                best_thresh = t
                best_tp = tp
                best_fp = fp
                best_fn = fn
            
    metrics["optimal_threshold"] = best_thresh
    metrics["best_f1"] = best_f1
    metrics["true_positives"] = best_tp
    metrics["false_positives"] = best_fp
    metrics["false_negatives"] = best_fn
    
    return metrics

def export_detailed_csv(topic_datasets: Dict[str, List[Dict]], topic_results: Dict[str, Dict]):
    csv_filename = "tests/comprehensive_article_scores.csv"
    with open(csv_filename, "w", newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Topic", "Headline", "Description", "Ground Truth", "Format A Score", "Format B Score", "Format C Score", "Format D Score"])
        
        for topic_name, articles in topic_datasets.items():
            results = topic_results[topic_name]
            
            for i, article in enumerate(articles):
                row = [
                    topic_name,
                    article["headline"],
                    article["description"],
                    "Relevant" if article["is_relevant"] else "Irrelevant",
                    f"{results['Format A (Comprehensive)']['article_scores'][i]:.4f}",
                    f"{results['Format B (Subdomains)']['article_scores'][i]:.4f}",
                    f"{results['Format C (News-Like)']['article_scores'][i]:.4f}",
                    f"{results['Format D (Short)']['article_scores'][i]:.4f}"
                ]
                writer.writerow(row)
    print(f"Detailed scores exported to {csv_filename}")

def generate_markdown_report(model_name: str, topic_results: Dict[str, Dict], topic_datasets: Dict[str, List[Dict]], query_prefix: str):
    lines = []
    lines.append(f"# Comprehensive Multi-Topic Evaluation: `{model_name}`\n")
    lines.append("## Setup")
    lines.append(f"- **Model**: `{model_name}`")
    lines.append(f"- **Formatting**: {'Prefix `' + query_prefix + '` applied' if query_prefix else 'Raw text applied'}")
    lines.append("- **Class Balance**: Strictly 1:1 Relevant vs Irrelevant. Uses ONLY real news articles fetched from live RSS feeds.\n")
    
    for topic_name, results in topic_results.items():
        lines.append(f"## Evaluation: {topic_name}")
        articles = topic_datasets[topic_name]
        num_relevant = sum(1 for a in articles if a["is_relevant"])
        lines.append(f"**Dataset Size**: {len(articles)} total articles ({num_relevant} Relevant, {len(articles)-num_relevant} Irrelevant)\n")
        
        lines.append("### Queries Used")
        for format_name, queries in TOPICS[topic_name]["formats"].items():
            lines.append(f"**{format_name}**:")
            for q in queries:
                lines.append(f"- {q}")
        lines.append("\n### Results")
        
        for name, metrics in results.items():
            lines.append(f"**{name}**")
            lines.append(f"- Relevant Mean/Std: {metrics['mean_relevant']:.4f} / {metrics['std_relevant']:.4f}")
            lines.append(f"- Irrelevant Mean/Std: {metrics['mean_irrelevant']:.4f} / {metrics['std_irrelevant']:.4f}")
            lines.append(f"- Separation Gap: {metrics['separation_gap']:.4f}")
            lines.append(f"- F1-Score: {metrics['best_f1']:.4f} (at threshold {metrics['optimal_threshold']:.2f})")
            lines.append(f"- Errors: TP={metrics['true_positives']}, FP={metrics['false_positives']}, FN={metrics['false_negatives']}\n")
            
    report_content = "\n".join(lines)
    report_filename = f"tests/evaluation_comprehensive.md"
    with open(report_filename, "w") as f:
        f.write(report_content)
    print(f"Markdown report written to {report_filename}")

def main():
    model_name = "all-mpnet-base-v2"
    query_prefix = ""
    
    print(f"\n======================================")
    print(f"Loading model: {model_name}...")
    model = SentenceTransformer(model_name)
    
    base_articles = fetch_base_articles()
    
    topic_datasets = {}
    topic_results = {}
    
    for topic_name, topic_data in TOPICS.items():
        print(f"\n--- Processing Topic: {topic_name} ---")
        articles = create_balanced_dataset_for_topic(base_articles, topic_name, topic_data)
        topic_datasets[topic_name] = articles
        
        if len(articles) == 0:
            print(f"Skipping {topic_name} (no relevant articles).")
            continue
            
        print(f"Balanced Dataset: {len(articles)} articles (1:1 ratio)")
        print("Encoding articles...")
        article_texts = [a["text"] for a in articles]
        article_embs = model.encode(article_texts, batch_size=32, show_progress_bar=True)
        
        results = {}
        for format_name, queries in topic_data["formats"].items():
            print(f"Evaluating {format_name}...")
            prefixed_queries = [query_prefix + q for q in queries]
            query_embs = model.encode(prefixed_queries, show_progress_bar=False)
            
            metrics = evaluate_format(articles, query_embs, article_embs)
            results[format_name] = metrics
            
        topic_results[topic_name] = results
        
    generate_markdown_report(model_name, topic_results, topic_datasets, query_prefix)
    export_detailed_csv(topic_datasets, topic_results)

if __name__ == "__main__":
    main()
