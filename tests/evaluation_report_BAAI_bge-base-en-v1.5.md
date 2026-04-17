# Model Evaluation Report: `BAAI/bge-base-en-v1.5`

## 1. Model Used
- **Name**: `BAAI/bge-base-en-v1.5`
- **Formatting applied**: Prefix `"Represent this sentence for searching relevant news articles: "` applied to queries.

## 2. Query Formats Tested
### Format A (Comprehensive)
- Artificial intelligence, machine learning, and neural networks are transforming industries. This includes generative AI like ChatGPT, large language models, automation of jobs, and the economic impact of tech companies investing in AI infrastructure, as well as debates around regulation and ethics.

### Format B (Subdomains)
- The rapid development and deployment of Generative AI systems and Large Language Models by major tech companies, focusing on their increasing capabilities in natural language understanding, reasoning, and multi-modal generation.
- The broader impact of artificial intelligence on the global economy, specifically highlighting the ongoing automation of cognitive tasks, significant shifts in the labor market, and concerns about widespread job displacement across various industries.
- The massive surge in capital expenditure by technology giants investing heavily in specialized AI infrastructure, building next-generation data centers, and procuring advanced semiconductor chips to power artificial intelligence training and inference.
- The ongoing international debates among lawmakers and policymakers regarding the implementation of comprehensive regulatory frameworks, safety standards, and ethical guidelines designed to govern the development and mitigate the risks of advanced artificial intelligence.

### Format C (News-Like)
- Major technology company officially releases highly anticipated new generative AI model, boasting significant improvements in reasoning capabilities and multi-modal processing.
- Comprehensive new economic report warns of significant AI-driven job displacement across multiple white-collar industries over the next decade.
- Leading tech giant formally announces a multi-billion dollar strategic investment to build massive new AI data centers and acquire specialized computing infrastructure.
- International lawmakers intensely debate the implementation of a strict new AI regulation framework and comprehensive safety standards to curb the risks of autonomous systems.

### Format D (Short)
- Generative AI development
- AI economic impact
- AI infrastructure investment
- AI ethics and regulation

## 3. Sample Data
**Total Articles Evaluated**: 121 (20 Relevant, 101 Irrelevant)

### Relevant Examples
- **Man charged with attempted murder over attack on home of OpenAI's Sam Altman**: The Texas man, who also faces federal felony charges, allegedly had documents advocating for violence against AI executives.
- **OpenAI boss Sam Altman's home targeted with Molotov cocktail**: San Francisco police have arrested a 20-year-old suspect after a perimeter gate was set alight.
- **Finance ministers and top bankers raise serious concerns about Mythos AI model**: Experts say Mythos potentially has an unprecedented ability to identify and exploit cybersecurity weaknesses.

### Irrelevant Examples
- **Could a digital twin make you into a 'superworker'?**: Firms say digital twins make staff more productive, but are they a potential legal minefield?
- **Things can't go on like this with online safety, Starmer tells tech bosses**: It comes as the government continues to consult on whether to ban under-16s from social media in the UK.
- **Booking.com customers warned of 'reservation hijacking' after hack**: The travel platform said it had changed Pins to protect customers but would not say how many were affected.


## 4. Results (Per Format)
### Format A (Comprehensive)
- **Relevant Scores**: Mean = 0.5755, Std = 0.0688
- **Irrelevant Scores**: Mean = 0.3881, Std = 0.0605
- **Separation Gap**: 0.1874
- **Optimal Threshold**: 0.50
- **Max F1-Score**: 0.8500
- **Identification**: True Positives = 17 (out of 20 relevant)
- **Errors at Threshold**: False Positives = 3, False Negatives = 3

### Format B (Subdomains)
- **Relevant Scores**: Mean = 0.5875, Std = 0.0721
- **Irrelevant Scores**: Mean = 0.4032, Std = 0.0525
- **Separation Gap**: 0.1843
- **Optimal Threshold**: 0.52
- **Max F1-Score**: 0.8718
- **Identification**: True Positives = 17 (out of 20 relevant)
- **Errors at Threshold**: False Positives = 2, False Negatives = 3

### Format C (News-Like)
- **Relevant Scores**: Mean = 0.5638, Std = 0.0741
- **Irrelevant Scores**: Mean = 0.3832, Std = 0.0524
- **Separation Gap**: 0.1806
- **Optimal Threshold**: 0.50
- **Max F1-Score**: 0.8421
- **Identification**: True Positives = 16 (out of 20 relevant)
- **Errors at Threshold**: False Positives = 2, False Negatives = 4

### Format D (Short)
- **Relevant Scores**: Mean = 0.5809, Std = 0.0653
- **Irrelevant Scores**: Mean = 0.3895, Std = 0.0528
- **Separation Gap**: 0.1914
- **Optimal Threshold**: 0.50
- **Max F1-Score**: 0.9048
- **Identification**: True Positives = 19 (out of 20 relevant)
- **Errors at Threshold**: False Positives = 3, False Negatives = 1

## 5. Model-Level Summary
- **Best Performing Format**: **Format D (Short)** (Highest separation gap)
- **Final Recommended Threshold**: **0.50**

### Observations
- Format A uses direct similarity to a single vector, while B, C, D use the MAX similarity across multiple vectors.
- The best format typically maximizes the separation gap between the mean relevant score and mean irrelevant score while keeping False Positives and False Negatives low.