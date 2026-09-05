# Book Knowledge Routing

Use this contract for knowledge distilled from books, essays, and reading sessions.

- `book` describes an intellectual work; edition, translation, ISBN, and format belong in its metadata or sources.
- `person` and `author` share the `people/` route. Use `author` only when the person's authorship is relevant.
- `argument` records an attributed thesis or claim, not an established fact.
- `concept`, `theme`, `character`, and `setting` capture reusable ideas or work-specific literary elements.
- `reading_note` records a dated encounter with a book; `journal` is a dated reading log.
- `practice` and `skill` describe actionable methods derived from reading.
- `reference` is the fallback for factual source material that does not fit another type.

Do not create one page per chapter or quote. Keep chapter and passage locators in `sources`, and promote reusable cross-book conclusions to `synthesis`.

Every page must resolve through `routing.json`, have one primary page type, preserve source attribution, and link related books, people, concepts, and arguments.
