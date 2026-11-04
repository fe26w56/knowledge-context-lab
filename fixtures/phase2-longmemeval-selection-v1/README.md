# LongMemEval cleaned S: stratified selection v1

This directory freezes only the selection metadata for a small, externally-authored LongMemEval cleaned S subset. It contains no questions, conversation history, answers, or evidence text. The original cleaned dataset was downloaded from the official repository/dataset links recorded in `selection.json`; its SHA-256 and byte count are fixed there.

Selection rule: group by `abstention` when `question_id` ends with `_abs`, otherwise by the dataset's `question_type`. Within each group sort by `sha256("20261103:" + question_id)`. Choose the first one for dev and the next two for final. The source contained 500 records and seven groups, producing 7 dev and 14 final cases.

The prepared model/retriever inputs are kept outside this public fixture at `work/longmemeval/prepared-v1/`. Each public case contains only a neutral `evaluator_case_key`, the request, question date, and neutral session IDs with date and role/content turns. Gold answers, original question/session IDs, answer-session links, and answer-marked turn indices are separate evaluator-only files.

This is a local adaptation of an externally authored benchmark subset. It is not the full official leaderboard setup, an independent benchmark, a proof of Notion value, or evidence of production quality. Fourteen final cases are too small for general non-inferiority claims. No oracle dataset was downloaded and no paid API calls were made.

License/source links are recorded for review; verify the upstream terms before redistribution.
