# Phase 2 token-growth fixture v4

Fictional, project-authored diagnostic; not an independent benchmark. The 37 essential
records support the development and held-out final topics, and every generated size is
exactly the requested N. Added records use an ordinal-stable family cycle: 15% historical,
15% exact duplicates, 30% current records with a different region/use case condition, and
40% other current records. Duplicate records deep-copy a source body and preserve its
project, status, and scope; metadata reports duplicate record counts.

The random seed depends on seed and scenario, never N, so the first 100 records are a
prefix of the 1,000- and 10,000-record mixed corpora. `unrelated` uses unrelated project
names without injected families. `long` keeps all source IDs and appends distinct sections
to all 37 essential documents; multipliers 1, 4, and 16 are frozen with observed body
character totals. The retriever receives only request text and permitted filters, never
qid, gold quotes, source IDs, or family labels.
