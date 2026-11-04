# Retrieval replay results

Corpus: `synthetic-research-v1`. Unit: `reference_tokens:o200k_base`.

These are local retrieval and payload measurements. Evidence coverage is not answer accuracy. No LLM responses, provider billing, network latency or D1 availability were measured.

A is a top-3-document full-payload replay proxy. B extracts sections. C stores the same sections in SQLite and applies explicit state filters. A may exceed the stated budget; B/C flag insufficient budgets.

| Split | Method | Budget | Complete evidence | Required quote recall | Median units | Total units | Scope leak hits |
|---|---|---:|---:|---:|---:|---:|---:|
| dev | A | 1000 | 9/9 | 100.0% | 1662 | 15967 | 0 |
| dev | A | 2000 | 9/9 | 100.0% | 1654 | 15887 | 0 |
| dev | A | 4000 | 9/9 | 100.0% | 1654 | 15887 | 0 |
| dev | B | 1000 | 9/9 | 100.0% | 934 | 9416 | 0 |
| dev | B | 2000 | 9/9 | 100.0% | 1733 | 16587 | 0 |
| dev | B | 4000 | 9/9 | 100.0% | 1733 | 16587 | 0 |
| dev | C | 1000 | 9/9 | 100.0% | 950 | 9549 | 0 |
| dev | C | 2000 | 9/9 | 100.0% | 1521 | 15831 | 0 |
| dev | C | 4000 | 9/9 | 100.0% | 1521 | 15831 | 0 |
| eval | A | 1000 | 16/17 | 97.2% | 1654 | 33248 | 0 |
| eval | A | 2000 | 16/17 | 97.2% | 1646 | 33088 | 0 |
| eval | A | 4000 | 16/17 | 97.2% | 1646 | 33088 | 0 |
| eval | B | 1000 | 15/17 | 94.4% | 932 | 18678 | 0 |
| eval | B | 2000 | 16/17 | 97.2% | 1740 | 35165 | 0 |
| eval | B | 4000 | 16/17 | 97.2% | 1740 | 35165 | 0 |
| eval | C | 1000 | 15/17 | 94.4% | 948 | 18986 | 0 |
| eval | C | 2000 | 16/17 | 97.2% | 1749 | 34914 | 0 |
| eval | C | 4000 | 16/17 | 97.2% | 1749 | 35040 | 0 |

Raw results include failures. No common-quality efficiency multiplier is inferred from an unqualified ratio of payload totals.

Corpus SHA-256: `6d83e79df872645929ac1a19f0bec1f80f590047c487be23ed9823d3644a52e4`
Queries SHA-256: `66a612cfb42c8896e62bb80d65a54b2d6197e96671e4f95d67b0771584152d17`
Code SHA-256: `0b197cb57dc09711a84229d7ae14145d3f0cce48d4dccdb2c9e31464036d97df`
