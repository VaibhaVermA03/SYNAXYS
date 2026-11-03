"""Maps job kinds to handlers. Handlers for later phases are loaded only if present, so an
unimplemented kind fails the job with a clear message instead of pretending to succeed."""
from importlib import import_module

_SPECS = [("review", "app.workers.review_worker", "handle_review"),
          ("publish", "app.workers.publish_worker", "handle_publish"),
          ("index", "app.workers.indexing_worker", "handle_index"),
          ("index_delete", "app.workers.indexing_worker", "handle_index_delete")]


def load_handlers() -> dict:
    handlers = {}
    for kind, module, fn in _SPECS:
        try:
            handlers[kind] = getattr(import_module(module), fn)
        except (ImportError, AttributeError):
            continue
    return handlers
