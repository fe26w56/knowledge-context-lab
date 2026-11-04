# Phase 2 completion fixture v3

Revision of v2 after semantic review. v1 and v2 are untouched. This fictional,
non-independent benchmark contains 80 documents and 40 questions (20 dev, 20
final). Document and question IDs are hash-derived opaque values and document
order is deliberately shuffled.

Multi-source items use distinct operational roles (for example, an arrival log
and an exception/office-hours decision). Their atomic claims are stored in
different source families and no one document satisfies all claims. Condition
items request a named row from a topic-specific 20-row, four-column matrix;
the exact threshold, unit, action, and exception are also bound to an atomic
claim. Private non-owner items have denial-safe shared-policy gold and never
require private note content.

`FREEZE.json` records content hashes, implementation-blindness, and the
explicit `independent_benchmark: false` boundary.
