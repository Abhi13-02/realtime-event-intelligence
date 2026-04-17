# Comprehensive Multi-Topic Evaluation: `all-mpnet-base-v2`

## Setup
- **Model**: `all-mpnet-base-v2`
- **Formatting**: Raw text applied
- **Class Balance**: Strictly 1:1 Relevant vs Irrelevant. Uses ONLY real news articles fetched from live RSS feeds.

## Evaluation: Artificial Intelligence
**Dataset Size**: 32 total articles (16 Relevant, 16 Irrelevant)

### Queries Used
**Format A (Comprehensive)**:
- Artificial intelligence, machine learning, and neural networks are transforming industries. This includes generative AI like ChatGPT, large language models, automation of jobs, and the economic impact of tech companies investing in AI infrastructure, as well as debates around regulation and ethics.
**Format B (Subdomains)**:
- The rapid development and deployment of Generative AI systems and Large Language Models by major tech companies, focusing on their increasing capabilities in natural language understanding, reasoning, and multi-modal generation.
- The broader impact of artificial intelligence on the global economy, specifically highlighting the ongoing automation of cognitive tasks, significant shifts in the labor market, and concerns about widespread job displacement across various industries.
- The massive surge in capital expenditure by technology giants investing heavily in specialized AI infrastructure, building next-generation data centers, and procuring advanced semiconductor chips to power artificial intelligence training and inference.
- The ongoing international debates among lawmakers and policymakers regarding the implementation of comprehensive regulatory frameworks, safety standards, and ethical guidelines designed to govern the development and mitigate the risks of advanced artificial intelligence.
**Format C (News-Like)**:
- Major technology company officially releases highly anticipated new generative AI model, boasting significant improvements in reasoning capabilities and multi-modal processing.
- Comprehensive new economic report warns of significant AI-driven job displacement across multiple white-collar industries over the next decade.
- Leading tech giant formally announces a multi-billion dollar strategic investment to build massive new AI data centers and acquire specialized computing infrastructure.
- International lawmakers intensely debate the implementation of a strict new AI regulation framework and comprehensive safety standards to curb the risks of autonomous systems.
**Format D (Short)**:
- Generative AI development
- AI economic impact
- AI infrastructure investment
- AI ethics and regulation

### Results
**Format A (Comprehensive)**
- Relevant Mean/Std: 0.3086 / 0.1768
- Irrelevant Mean/Std: 0.0809 / 0.0906
- Separation Gap: 0.2277
- F1-Score: 0.8108 (at threshold 0.09)
- Errors: TP=15, FP=6, FN=1

**Format B (Subdomains)**
- Relevant Mean/Std: 0.3299 / 0.1524
- Irrelevant Mean/Std: 0.1309 / 0.0821
- Separation Gap: 0.1990
- F1-Score: 0.8649 (at threshold 0.14)
- Errors: TP=16, FP=5, FN=0

**Format C (News-Like)**
- Relevant Mean/Std: 0.3255 / 0.1444
- Irrelevant Mean/Std: 0.1400 / 0.0759
- Separation Gap: 0.1856
- F1-Score: 0.8000 (at threshold 0.17)
- Errors: TP=14, FP=5, FN=2

**Format D (Short)**
- Relevant Mean/Std: 0.2966 / 0.1432
- Irrelevant Mean/Std: 0.1258 / 0.0968
- Separation Gap: 0.1708
- F1-Score: 0.8421 (at threshold 0.12)
- Errors: TP=16, FP=6, FN=0

## Evaluation: World War and Geopolitics
**Dataset Size**: 116 total articles (58 Relevant, 58 Irrelevant)

### Queries Used
**Format A (Comprehensive)**:
- The geopolitical landscape is shifting rapidly as global conflicts erupt and international relations become strained. This includes ongoing military deployments, proxy wars, diplomatic efforts such as ceasefires and treaties, economic sanctions, the role of international organizations like the UN and NATO, and the resulting humanitarian crises and refugee movements.
**Format B (Subdomains)**:
- Ongoing military deployments, armed conflicts, and the strategic positioning of global military forces in volatile regions.
- The implementation of economic sanctions, trade embargoes, and the use of financial instruments as geopolitical weapons.
- Diplomatic negotiations, international treaties, peace talks, and the efforts of organizations like the UN and NATO to maintain stability.
- The severe humanitarian consequences of war, including mass refugee migrations, civilian casualties, and international aid efforts.
**Format C (News-Like)**:
- Global leaders convene for emergency summit as regional conflict escalates and ceasefire negotiations stall.
- International coalition announces sweeping new economic sanctions targeting military infrastructure and defense contractors.
- Hundreds of thousands displaced as heavy fighting breaks out along contested border, triggering a severe humanitarian crisis.
- Defense alliance deploys additional troops and advanced missile defense systems in response to rising geopolitical tensions.
**Format D (Short)**:
- Military deployments and armed conflicts
- Economic sanctions and trade embargoes
- International diplomacy and peace talks
- Humanitarian crises and refugee movements

### Results
**Format A (Comprehensive)**
- Relevant Mean/Std: 0.3033 / 0.1149
- Irrelevant Mean/Std: 0.1190 / 0.1123
- Separation Gap: 0.1843
- F1-Score: 0.8175 (at threshold 0.13)
- Errors: TP=56, FP=23, FN=2

**Format B (Subdomains)**
- Relevant Mean/Std: 0.3196 / 0.0984
- Irrelevant Mean/Std: 0.1429 / 0.1025
- Separation Gap: 0.1767
- F1-Score: 0.8358 (at threshold 0.17)
- Errors: TP=56, FP=20, FN=2

**Format C (News-Like)**
- Relevant Mean/Std: 0.2882 / 0.0943
- Irrelevant Mean/Std: 0.1341 / 0.0889
- Separation Gap: 0.1541
- F1-Score: 0.8644 (at threshold 0.20)
- Errors: TP=51, FP=9, FN=7

**Format D (Short)**
- Relevant Mean/Std: 0.3394 / 0.1113
- Irrelevant Mean/Std: 0.1545 / 0.1022
- Separation Gap: 0.1849
- F1-Score: 0.8235 (at threshold 0.25)
- Errors: TP=49, FP=12, FN=9

## Evaluation: Science and Discovery
**Dataset Size**: 80 total articles (40 Relevant, 40 Irrelevant)

### Queries Used
**Format A (Comprehensive)**:
- Scientific research continues to push the boundaries of human knowledge, encompassing breakthroughs in biology, space exploration, physics, and medicine. This includes the discovery of new celestial bodies, advancements in genetic engineering, studying the effects of climate change, and the development of novel medical treatments.
**Format B (Subdomains)**:
- Astronomical discoveries, space exploration missions, and the observation of new planetary systems and cosmic phenomena.
- Breakthroughs in biological research, genetic engineering, molecular biology, and the study of complex ecosystems.
- The physical sciences, exploring quantum mechanics, particle physics, and fundamental forces of the universe.
- Medical advancements, the development of new treatments, vaccines, and ongoing research into human health and disease.
**Format C (News-Like)**:
- Astronomers successfully capture unprecedented images of distant exoplanet using next-generation orbital telescope.
- Researchers publish groundbreaking new study detailing a revolutionary method for targeted gene editing.
- Physicists announce major breakthrough in quantum computing stability after years of experimental trials.
- Clinical trial results show highly promising efficacy for experimental new Alzheimer's disease treatment.
**Format D (Short)**:
- Space exploration and astronomy
- Genetics and biological research
- Physics and quantum mechanics
- Medical research and treatments

### Results
**Format A (Comprehensive)**
- Relevant Mean/Std: 0.1719 / 0.0915
- Irrelevant Mean/Std: 0.0661 / 0.0581
- Separation Gap: 0.1059
- F1-Score: 0.8056 (at threshold 0.12)
- Errors: TP=29, FP=3, FN=11

**Format B (Subdomains)**
- Relevant Mean/Std: 0.2374 / 0.1046
- Irrelevant Mean/Std: 0.1031 / 0.0642
- Separation Gap: 0.1343
- F1-Score: 0.7750 (at threshold 0.15)
- Errors: TP=31, FP=9, FN=9

**Format C (News-Like)**
- Relevant Mean/Std: 0.1636 / 0.0785
- Irrelevant Mean/Std: 0.0804 / 0.0675
- Separation Gap: 0.0832
- F1-Score: 0.7500 (at threshold 0.08)
- Errors: TP=33, FP=15, FN=7

**Format D (Short)**
- Relevant Mean/Std: 0.1959 / 0.1110
- Irrelevant Mean/Std: 0.0764 / 0.0627
- Separation Gap: 0.1196
- F1-Score: 0.7711 (at threshold 0.09)
- Errors: TP=32, FP=11, FN=8

## Evaluation: Sports
**Dataset Size**: 44 total articles (22 Relevant, 22 Irrelevant)

### Queries Used
**Format A (Comprehensive)**:
- The world of competitive sports brings together athletes and fans globally, featuring intense matches, championship tournaments, and record-breaking performances. This encompasses professional leagues, international competitions like the Olympics, dramatic player transfers, coaching changes, and the ongoing pursuit of athletic excellence.
**Format B (Subdomains)**:
- High-stakes professional leagues, seasonal tournaments, and the intense competition for championship titles.
- International sporting events, national team rivalries, and global spectacles like the Olympic Games or World Cup.
- Athlete performance, record-breaking achievements, and the physical conditioning required for elite sports.
- The business of sports, including lucrative player transfers, major contract signings, and controversial coaching changes.
**Format C (News-Like)**:
- Underdog team secures dramatic last-minute victory to clinch the national championship title.
- Star athlete shatters long-standing world record during highly anticipated international competition.
- Major professional sports league announces controversial new rules aimed at increasing player safety.
- Record-breaking multi-million dollar contract signed as star player transfers to rival club.
**Format D (Short)**:
- Championship tournaments and matches
- International sporting events
- Athlete performance and records
- Player transfers and sports business

### Results
**Format A (Comprehensive)**
- Relevant Mean/Std: 0.1002 / 0.0879
- Irrelevant Mean/Std: 0.0564 / 0.0694
- Separation Gap: 0.0439
- F1-Score: 0.7273 (at threshold 0.07)
- Errors: TP=16, FP=6, FN=6

**Format B (Subdomains)**
- Relevant Mean/Std: 0.1737 / 0.0815
- Irrelevant Mean/Std: 0.1130 / 0.0655
- Separation Gap: 0.0607
- F1-Score: 0.7308 (at threshold 0.10)
- Errors: TP=19, FP=11, FN=3

**Format C (News-Like)**
- Relevant Mean/Std: 0.1070 / 0.0627
- Irrelevant Mean/Std: 0.1054 / 0.0568
- Separation Gap: 0.0016
- F1-Score: 0.6667 (at threshold 0.00)
- Errors: TP=22, FP=22, FN=0

**Format D (Short)**
- Relevant Mean/Std: 0.1317 / 0.0836
- Irrelevant Mean/Std: 0.1003 / 0.0497
- Separation Gap: 0.0314
- F1-Score: 0.6774 (at threshold 0.04)
- Errors: TP=21, FP=19, FN=1

## Evaluation: Economy and Finance
**Dataset Size**: 62 total articles (31 Relevant, 31 Irrelevant)

### Queries Used
**Format A (Comprehensive)**:
- Global financial markets are constantly reacting to changing economic indicators, corporate performance, and government monetary policies. This includes central bank decisions on interest rates, stock market fluctuations, inflation reports, corporate earnings, trade agreements, and the broader impacts of international commerce.
**Format B (Subdomains)**:
- Central bank monetary policies, adjustments to baseline interest rates, and national strategies for managing inflation.
- Stock market volatility, daily trading indices, and the performance of global financial exchanges.
- Corporate earnings reports, quarterly financial results, and the strategic business decisions of multinational companies.
- International trade dynamics, global supply chain disruptions, and the economic impact of tariffs and trade agreements.
**Format C (News-Like)**:
- Central bank officially announces unexpected interest rate hike in continued effort to combat persistent inflation.
- Global stock markets experience significant sell-off following release of worse-than-expected economic data.
- Major multinational corporation reports record quarterly profits driven by strong international sales.
- New international trade agreement signed, significantly lowering tariffs and aiming to boost global commerce.
**Format D (Short)**:
- Monetary policy and interest rates
- Stock market and financial exchanges
- Corporate earnings and business strategy
- International trade and supply chains

### Results
**Format A (Comprehensive)**
- Relevant Mean/Std: 0.2868 / 0.1154
- Irrelevant Mean/Std: 0.0980 / 0.0774
- Separation Gap: 0.1888
- F1-Score: 0.8525 (at threshold 0.17)
- Errors: TP=26, FP=4, FN=5

**Format B (Subdomains)**
- Relevant Mean/Std: 0.2786 / 0.0857
- Irrelevant Mean/Std: 0.1276 / 0.0867
- Separation Gap: 0.1510
- F1-Score: 0.8571 (at threshold 0.19)
- Errors: TP=27, FP=5, FN=4

**Format C (News-Like)**
- Relevant Mean/Std: 0.2772 / 0.0827
- Irrelevant Mean/Std: 0.1263 / 0.0669
- Separation Gap: 0.1510
- F1-Score: 0.8525 (at threshold 0.19)
- Errors: TP=26, FP=4, FN=5

**Format D (Short)**
- Relevant Mean/Std: 0.2447 / 0.0764
- Irrelevant Mean/Std: 0.1001 / 0.0853
- Separation Gap: 0.1446
- F1-Score: 0.8571 (at threshold 0.12)
- Errors: TP=30, FP=9, FN=1
