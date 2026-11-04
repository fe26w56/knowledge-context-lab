# Raw page migration fixture v2

This fixture tests migration of raw Notion-like pages, not a pre-split answer store. Each of the eight fictional topics has two pages: a main page that mixes a current summary with prior proposal/history, and a related reference or duplicate page. Bodies are deliberately multi-section Japanese prose (roughly 500–1400 characters) so that an importer must preserve page boundaries, metadata, links, and chronology before retrieval.

`pages.json` is the source corpus visible to an importer. `dev.json` and `final.json` contain eight questions each and evaluator-only `gold` spans. Requests do not contain page IDs, expected quotes, or task IDs. `operations` contain complete replacement page inputs for correction, explicit approval, repeat retrieval, and export/import checks; these are evaluator instructions, not retrieval input.

Schema: `pages` entries have `id`, `title`, example.invalid `url`, `parent_id`, `properties` (`decision_status`, `as_of`, `summary`, `category`), raw Markdown `body`, `scope`, `owner`, `edited_at`, and `incomplete`. A page may have `decision_status: null` when it is ordinary reference material. `incomplete` records a real unresolved field, not an artificial failure.

The author did not inspect migration implementation code before freezing this fixture. Dev and final use distinct fictional entities. This is an internal diagnostic, not an independent benchmark or production quality guarantee. Real documents, credentials, private identifiers, and actual Notion URLs are absent. Repairs require a new fixture version.
