# Model Evaluation Report: `nomic-ai/nomic-embed-text-v1.5`

## 1. Model Used
- **Name**: `nomic-ai/nomic-embed-text-v1.5`
- **Formatting applied**: Prefix `"search_query: "` applied to queries.

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
- **Relevant Scores**: Mean = 0.7046, Std = 0.0637
- **Irrelevant Scores**: Mean = 0.5453, Std = 0.0420
- **Separation Gap**: 0.1593
- **Optimal Threshold**: 0.64
- **Max F1-Score**: 0.8649
- **Identification**: True Positives = 16 (out of 20 relevant)
- **Errors at Threshold**: False Positives = 1, False Negatives = 4

### Format B (Subdomains)
- **Relevant Scores**: Mean = 0.7026, Std = 0.0682
- **Irrelevant Scores**: Mean = 0.5531, Std = 0.0380
- **Separation Gap**: 0.1495
- **Optimal Threshold**: 0.65
- **Max F1-Score**: 0.8571
- **Identification**: True Positives = 15 (out of 20 relevant)
- **Errors at Threshold**: False Positives = 0, False Negatives = 5

### Format C (News-Like)
- **Relevant Scores**: Mean = 0.6852, Std = 0.0713
- **Irrelevant Scores**: Mean = 0.5384, Std = 0.0378
- **Separation Gap**: 0.1468
- **Optimal Threshold**: 0.61
- **Max F1-Score**: 0.8293
- **Identification**: True Positives = 17 (out of 20 relevant)
- **Errors at Threshold**: False Positives = 4, False Negatives = 3

### Format D (Short)
- **Relevant Scores**: Mean = 0.6331, Std = 0.0595
- **Irrelevant Scores**: Mean = 0.4660, Std = 0.0409
- **Separation Gap**: 0.1671
- **Optimal Threshold**: 0.58
- **Max F1-Score**: 0.9189
- **Identification**: True Positives = 17 (out of 20 relevant)
- **Errors at Threshold**: False Positives = 0, False Negatives = 3

## 5. Model-Level Summary
- **Best Performing Format**: **Format D (Short)** (Highest separation gap)
- **Final Recommended Threshold**: **0.58**

### Observations
- Format A uses direct similarity to a single vector, while B, C, D use the MAX similarity across multiple vectors.
- The best format typically maximizes the separation gap between the mean relevant score and mean irrelevant score while keeping False Positives and False Negatives low.