Stores: all enabled; 30 queries; top 10 rows per query; similarity threshold 0.82.

| Mode | P@10 | MRR | Zero results | Median latency | P@10 english | P@10 intent | P@10 literal | P@10 typo |
|---|---|---|---|---|---|---|---|---|
| text | 0.78 | 0.78 | 3 | 198 ms | 0.00 | 0.71 | 1.00 | 0.95 |
| semantic | 0.82 | 0.87 | 0 | 205 ms | 0.50 | 0.80 | 0.89 | 1.00 |
| hybrid | 0.87 | 0.88 | 0 | 214 ms | 0.45 | 0.82 | 1.00 | 0.95 |

| Query | Kind | text P@10 / RR | semantic P@10 / RR | hybrid P@10 / RR |
|---|---|---|---|---|
| zabpehely | literal | 1.0 / 1.00 | 0.7 / 1.00 | 1.0 / 1.00 |
| tejföl | literal | 1.0 / 1.00 | 1.0 / 1.00 | 1.0 / 1.00 |
| paradicsom | literal | 1.0 / 1.00 | 1.0 / 1.00 | 1.0 / 1.00 |
| pálinka | literal | 1.0 / 1.00 | 0.4 / 0.50 | 1.0 / 1.00 |
| mosogatószer | literal | 1.0 / 1.00 | 1.0 / 1.00 | 1.0 / 1.00 |
| kávékapszula | literal | 1.0 / 1.00 | 1.0 / 1.00 | 1.0 / 1.00 |
| zöld tea | literal | 1.0 / 1.00 | 1.0 / 1.00 | 1.0 / 1.00 |
| koffeinmentes kávé | literal | 1.0 / 1.00 | 0.8 / 1.00 | 1.0 / 1.00 |
| laktózmentes tej | literal | 1.0 / 1.00 | 1.0 / 1.00 | 1.0 / 1.00 |
| kutyaeledel | literal | 1.0 / 1.00 | 1.0 / 1.00 | 1.0 / 1.00 |
| csokolade | typo | 0.9 / 0.50 | 1.0 / 1.00 | 0.9 / 0.50 |
| mosopor | typo | 1.0 / 1.00 | 1.0 / 1.00 | 1.0 / 1.00 |
| orange juice | english | 0.0 / 0.00 | 0.0 / 0.00 | 0.0 / 0.00 |
| toilet paper | english | 0.0 / 0.00 | 1.0 / 1.00 | 0.9 / 0.50 |
| üdítő | intent | 0.4 / 1.00 | 0.6 / 0.50 | 0.7 / 1.00 |
| reggelire gabonapehely | intent | 1.0 / 1.00 | 1.0 / 1.00 | 1.0 / 1.00 |
| gluténmentes kenyér | intent | 1.0 / 1.00 | 1.0 / 1.00 | 1.0 / 1.00 |
| babapelenka | intent | 0.0 / 0.00 | 1.0 / 1.00 | 1.0 / 1.00 |
| macskaalom | intent | 1.0 / 1.00 | 0.8 / 1.00 | 1.0 / 1.00 |
| fogkrém gyerekeknek | intent | 0.6 / 1.00 | 1.0 / 1.00 | 0.8 / 1.00 |
| mosószer színes ruhákhoz | intent | 1.0 / 1.00 | 1.0 / 1.00 | 1.0 / 1.00 |
| sörkorcsolya | intent | 0.0 / 0.00 | 0.0 / 0.00 | 0.0 / 0.00 |
| grillezni való hús | intent | 0.7 / 0.25 | 1.0 / 1.00 | 0.7 / 0.50 |
| energiaital | intent | 1.0 / 1.00 | 1.0 / 1.00 | 1.0 / 1.00 |
| cukormentes üdítő | intent | 1.0 / 1.00 | 1.0 / 1.00 | 1.0 / 1.00 |
| kenyérre kenhető | intent | 0.9 / 1.00 | 0.0 / 0.00 | 0.8 / 1.00 |
| fehérjeszelet sportolóknak | intent | 1.0 / 1.00 | 1.0 / 1.00 | 1.0 / 1.00 |
| olasz tészta | intent | 0.8 / 0.50 | 1.0 / 1.00 | 0.8 / 1.00 |
| halkonzerv | intent | 0.0 / 0.00 | 0.4 / 1.00 | 0.4 / 1.00 |
| fürdőszoba tisztító | intent | 1.0 / 1.00 | 1.0 / 1.00 | 1.0 / 1.00 |

| Semantic threshold | P@10 (semantic) | Results for 4 nonsense queries |
|---|---|---|
| 0.00 | 0.84 | 40 |
| 0.78 | 0.84 | 40 |
| 0.80 | 0.84 | 40 |
| 0.82 | 0.82 | 24 |
| 0.84 | 0.77 | 20 |
| 0.86 | 0.57 | 1 |
