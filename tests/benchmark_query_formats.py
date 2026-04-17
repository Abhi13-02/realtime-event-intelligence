import os
import re
import numpy as np
import feedparser
from sentence_transformers import SentenceTransformer
from typing import List, Dict

# Topic Definitions
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
        ],
        "dummy_relevant": [
            ("OpenAI releases new ChatGPT model", "The new generative AI model boasts improved reasoning."),
            ("Nvidia announces new AI chip", "The tech giant is investing heavily in new AI infrastructure."),
            ("EU passes comprehensive AI Act", "Lawmakers have agreed on strict regulations for artificial intelligence."),
            ("AI replacing jobs in tech sector", "A new report shows machine learning automating coding tasks."),
            ("Google DeepMind breakthroughs in protein folding", "The AI system AlphaFold has solved a grand challenge in biology."),
            ("Meta open sources new Llama 3 model", "The company hopes to accelerate artificial intelligence research by sharing weights openly."),
            ("AI agents capable of autonomous software engineering", "A new startup demonstrated a tool that can write, debug, and deploy code using neural networks."),
            ("Generative AI art wins major competition", "An image created by Midjourney has sparked controversy after winning first place at the state fair."),
            ("Venture capital floods into AI startups", "Investors poured billions into early-stage machine learning companies this quarter."),
            ("Microsoft integrates AI Copilot into Windows", "The tech giant is bringing large language models directly to the consumer desktop experience.")
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
            r'diplomacy', r'refugee', r'embargo', r'proxy war', r'peace talks'
        ],
        "dummy_relevant": [
            ("UN Security Council calls for immediate ceasefire", "Diplomats urge an end to the escalating violence in the region."),
            ("NATO allies pledge additional military support", "Defense ministers agreed to send advanced weaponry to the front lines."),
            ("US imposes sweeping new economic sanctions", "The Treasury Department targeted key military and financial institutions."),
            ("Refugee crisis worsens as border fighting continues", "Aid organizations warn of a looming humanitarian disaster."),
            ("Peace talks collapse after sudden missile strike", "Hopes for a diplomatic resolution were dashed following the overnight attack."),
            ("China and Russia conduct joint military exercises", "The naval drills in the Pacific signal deepening strategic ties."),
            ("EU leaders debate defense spending increases", "The geopolitical instability has prompted calls for a stronger European military alliance."),
            ("Drone attack targets strategic oil refinery", "The cross-border strike has raised concerns about global energy security."),
            ("Troops deployed to secure contested border region", "Tensions reached a boiling point after skirmishes left dozens dead."),
            ("Ambassador expelled in diplomatic tit-for-tat", "The espionage allegations have severely strained relations between the two nations.")
        ]
    }
}

FEEDS = [
    "http://feeds.bbci.co.uk/news/technology/rss.xml",
    "http://feeds.bbci.co.uk/news/business/rss.xml",
    "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    "http://feeds.bbci.co.uk/news/world/rss.xml"
]

def fetch_base_articles() -> List[Dict]:
    print("Fetching RSS feeds...")
    articles = []
    seen_titles = set()
    
    for url in FEEDS:
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
    return articles

def create_dataset_for_topic(base_articles: List[Dict], topic_name: str, topic_data: Dict) -> List[Dict]:
    topic_articles = []
    
    # Process base articles
    for a in base_articles:
        text_to_search = a["text"].lower()
        is_relevant = False
        for kw in topic_data["keywords"]:
            if re.search(kw, text_to_search):
                is_relevant = True
                break
        
        topic_articles.append({
            "headline": a["headline"],
            "description": a["description"],
            "text": a["text"],
            "is_relevant": is_relevant
        })
        
    # Inject dummy relevant to ensure strong statistics
    for t, d in topic_data["dummy_relevant"]:
        topic_articles.append({
            "headline": t,
            "description": d,
            "text": f"{t}. {d}",
            "is_relevant": True
        })
        
    return topic_articles

def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom > 1e-9 else 0.0

def evaluate_format(articles: List[Dict], query_embs: np.ndarray, article_embs: np.ndarray) -> Dict:
    relevant_scores = []
    irrelevant_scores = []
    
    for i, article in enumerate(articles):
        # Calculate max similarity against all queries in this format
        a_emb = article_embs[i]
        sims = [cosine_sim(a_emb, q_emb) for q_emb in query_embs]
        score = max(sims)
        
        if article["is_relevant"]:
            relevant_scores.append(score)
        else:
            irrelevant_scores.append(score)
            
    # Metrics
    metrics = {
        "mean_relevant": np.mean(relevant_scores) if relevant_scores else 0,
        "std_relevant": np.std(relevant_scores) if relevant_scores else 0,
        "mean_irrelevant": np.mean(irrelevant_scores) if irrelevant_scores else 0,
        "std_irrelevant": np.std(irrelevant_scores) if irrelevant_scores else 0,
    }
    metrics["separation_gap"] = metrics["mean_relevant"] - metrics["mean_irrelevant"]
    
    # Calculate overlap using threshold sweep (maximize F1)
    best_thresh = 0.0
    best_f1 = 0.0
    best_tp = 0
    best_fp = 0
    best_fn = 0
    
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

def generate_markdown_report(model_name: str, topic_results: Dict[str, Dict], topic_datasets: Dict[str, List[Dict]], query_prefix: str):
    lines = []
    lines.append(f"# Model Evaluation Report: `{model_name}`\n")
    lines.append("## 1. Model Used")
    lines.append(f"- **Name**: `{model_name}`")
    format_text = f'Prefix `"{query_prefix}"` applied to queries.' if query_prefix else 'Raw text applied to queries.'
    lines.append(f"- **Formatting applied**: {format_text}\n")
    
    for topic_name, results in topic_results.items():
        lines.append(f"## Evaluation: {topic_name}")
        articles = topic_datasets[topic_name]
        num_relevant = sum(1 for a in articles if a["is_relevant"])
        num_irrelevant = len(articles) - num_relevant
        lines.append(f"**Total Articles Evaluated**: {len(articles)} ({num_relevant} Relevant, {num_irrelevant} Irrelevant)\n")
        
        for name, metrics in results.items():
            lines.append(f"### {name}")
            lines.append(f"- **Relevant Scores**: Mean = {metrics['mean_relevant']:.4f}, Std = {metrics['std_relevant']:.4f}")
            lines.append(f"- **Irrelevant Scores**: Mean = {metrics['mean_irrelevant']:.4f}, Std = {metrics['std_irrelevant']:.4f}")
            lines.append(f"- **Separation Gap**: {metrics['separation_gap']:.4f}")
            lines.append(f"- **Optimal Threshold**: {metrics['optimal_threshold']:.2f}")
            lines.append(f"- **Max F1-Score**: {metrics['best_f1']:.4f}")
            lines.append(f"- **Identification**: True Positives = {metrics['true_positives']} (out of {metrics['true_positives'] + metrics['false_negatives']} relevant)")
            lines.append(f"- **Errors at Threshold**: False Positives = {metrics['false_positives']}, False Negatives = {metrics['false_negatives']}\n")
            
    report_content = "\n".join(lines)
    report_filename = f"tests/evaluation_report_{model_name.replace('/', '_')}.md"
    with open(report_filename, "w") as f:
        f.write(report_content)
    print(f"Report written to {report_filename}")

def main():
    models_to_test = [
        ("thenlper/gte-large", "", "")
    ]
    
    base_articles = fetch_base_articles()
    
    for model_name, query_prefix, doc_prefix in models_to_test:
        print(f"\n======================================")
        print(f"Loading model: {model_name}...")
        
        model = SentenceTransformer(model_name, trust_remote_code=True)
        
        topic_datasets = {}
        topic_results = {}
        
        for topic_name, topic_data in TOPICS.items():
            print(f"\n--- Processing Topic: {topic_name} ---")
            articles = create_dataset_for_topic(base_articles, topic_name, topic_data)
            topic_datasets[topic_name] = articles
            
            print("Encoding articles...")
            article_texts = [doc_prefix + a["text"] for a in articles]
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

if __name__ == "__main__":
    main()
