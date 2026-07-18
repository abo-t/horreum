# Contributing to Horreum

Thanks for your interest. Horreum is a **hobby project maintained in spare time**, so issues and
pull requests are genuinely welcome — but responses may take weeks. That's expected, not neglect.

*(Krótka wersja po polsku na końcu.)*

## Reporting issues

Use the GitHub **Issues** tab. A good report says what you did, what you expected, and what happened.
For scanning or header‑parsing problems, mention the file format (**FITS** or **XISF**) and, if you
can, the relevant header keywords — but never paste private data you don't want to be public.

## Development setup

Requires Python 3.9+.

```bash
pip install -e ".[gui,dev]"
python -m horreum.gui     # desktop application
pytest                    # test suite
```

From source you also get the CLI: `horreum --help` (`init` / `scan` / `group` / `resolve` / `delta`).

## Architecture you should respect

A few invariants are enforced by meta‑tests — please keep them:

- **The core is Qt‑free.** Database, scan, resolvers and query logic have no PySide6 import; only the
  view layer (`horreum/gui/`) may import Qt.
- **One write door.** All domain writes go through the repository layer and emit an event
  (append‑only); a meta‑test rejects stray SQL writes elsewhere.
- **File mutations are isolated** to the dedicated write modules (header writeback, projection),
  never scattered through the code.

Running `pytest` will tell you if a change crosses one of these lines.

## Pull requests

- Keep each PR focused on one concern.
- Run `pytest` before submitting; add tests for new behavior.
- Commit style: conventional‑commit prefixes (`feat` / `fix` / `docs` / `refactor` …). The maintainer
  writes commit descriptions in Polish, but English in your PRs is perfectly fine.

---

## Po polsku (skrót)

Projekt hobbystyczny prowadzony po godzinach — zgłoszenia (**Issues**) i pull requesty mile widziane,
ale odpowiedź może przyjść po tygodniach. Budowa i testy: `pip install -e ".[gui,dev]"`, potem
`python -m horreum.gui` i `pytest`. Rdzeń jest Qt‑wolny, zapis domenowy idzie jedną warstwą
repozytorium (pilnują tego meta‑testy) — `pytest` powie, czy zmiana nie przekracza tych granic.
