"""Phase 5 (batch 17), stdlib-only: favicon set, legal documents (operator details in operator.json, required disclosures, nothing invented), licence notice, Markdown in sync."""
import json
import pathlib
import re
import struct

ROOT = pathlib.Path(__file__).resolve().parents[3]
PUB, LEGAL, DOCS = ROOT / "frontend" / "public", ROOT / "frontend" / "src" / "legal", ROOT / "docs" / "legal"
KEYS = ("privacy", "terms", "security", "license")


def _doc(k): return json.loads((LEGAL / f"{k}.json").read_text(encoding="utf-8"))


def _text(doc):
    out = [doc["title"], doc.get("banner", ""), doc.get("effective", "")]
    for s in doc["sections"]:
        out.append(s["title"])
        for b in s["blocks"]:
            if "p" in b: out.append(b["p"])
            elif "note" in b: out.append(b["note"])
            elif "ul" in b: out += b["ul"]
            elif "table" in b: out += b["table"]["head"] + [c for r in b["table"]["rows"] for c in r]
    return "\n".join(out)


def _png_size(path):
    d = path.read_bytes()
    assert d[:8] == b"\x89PNG\r\n\x1a\n", path.name
    return struct.unpack(">II", d[16:24])


def test_favicon_files_exist_with_the_right_dimensions():
    for name, size in {"favicon-16x16.png": 16, "favicon-32x32.png": 32, "apple-touch-icon.png": 180, "android-chrome-192x192.png": 192, "android-chrome-512x512.png": 512, "maskable-512x512.png": 512}.items():
        assert _png_size(PUB / name) == (size, size), name
    ico = (PUB / "favicon.ico").read_bytes()
    reserved, kind, count = struct.unpack("<HHH", ico[:6])
    sizes = sorted((ico[6 + 16 * i] or 256) for i in range(count))
    assert (reserved, kind) == (0, 1) and sizes == [16, 32, 48]
    svg = (PUB / "favicon.svg").read_text(encoding="utf-8")
    assert svg.startswith("<svg") and "prefers-color-scheme:dark" in svg and len(svg) < 4000 and "<script" not in svg    # small, adaptive, inert


def test_manifest_and_html_reference_only_existing_icons():
    m = json.loads((PUB / "site.webmanifest").read_text(encoding="utf-8"))
    assert m["name"] == "SYNAXYS" and len(m["icons"]) >= 3
    for icon in m["icons"]:
        assert (PUB / icon["src"].lstrip("/")).exists() and _png_size(PUB / icon["src"].lstrip("/"))[0] == int(icon["sizes"].split("x")[0])
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r'<link rel="(?:icon|apple-touch-icon|manifest)"[^>]*href="([^"]+)"', html)
    assert {"/favicon.ico", "/favicon.svg", "/favicon-32x32.png", "/favicon-16x16.png", "/apple-touch-icon.png", "/site.webmanifest"} <= set(refs)
    assert all((PUB / r.lstrip("/")).exists() for r in refs)
    assert "<script>" not in html                                                          # the CSP forbids inline scripts


def test_existing_brand_assets_are_untouched():
    assert (PUB / "logo.svg").exists() and (PUB / "brand").is_dir()                       # the favicon is derived from the logo; the logo itself is not changed


def _operator(): return json.loads((LEGAL / "operator.json").read_text(encoding="utf-8"))


def test_legal_documents_are_structured_and_use_operator_details():
    """The owner's real details live only in operator.json; the documents reference them as {{key}}."""
    op = {k: v for k, v in _operator().items() if not k.startswith("_")}
    used = set()
    for k in KEYS:
        d = _doc(k)
        assert d["id"] == k and "lawyer" in d["banner"] and "double brackets" in d["banner"]   # the draft notice text exists; the page shows it only while [[...]] values remain
        assert len({s["id"] for s in d["sections"]}) == len(d["sections"]) and all(s["blocks"] for s in d["sections"])
        txt = _text(d)
        assert "[[" not in re.sub(r"\[\[double brackets\]\]", "", txt)                       # the documents themselves contain no unfilled markers
        used |= set(re.findall(r"\{\{(\w+)\}\}", txt))
    assert used <= set(op), sorted(used - set(op))                                              # every {{key}} has a value
    assert set(op) <= used, sorted(set(op) - used)                                              # and every value is used somewhere
    assert all(isinstance(v, str) and v.strip() for v in op.values())


def test_nothing_is_invented_no_emails_urls_phones_or_company_details():
    for k in KEYS:
        outside = re.sub(r"\[\[.*?\]\]", "", _text(_doc(k)))
        assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", outside), (k, "e-mail address")
        assert not re.search(r"https?://|www\.", outside, re.I), (k, "URL")
        assert not re.search(r"\+?\d[\d ()-]{8,}\d", outside.replace("1,500", "").replace("4,000", "")), (k, "phone-like number")
        assert not re.search(r"\b(Inc\.|Ltd\.?|GmbH|LLC|Pvt\b|S\.A\.)", outside), (k, "legal entity")


def test_privacy_policy_discloses_the_real_data_flows():
    t = _text(_doc("privacy"))
    for needle in ["OpenAI", "Pinecone", "GitHub", "Sentry", "Redis", "embeddings", "1,500 characters", "4,000 characters", "synaxys_session", "read:user", "Pull requests: read and write",
                   "gpt-4o", "text-embedding-3-small", "Export your data", "best effort", "diffs", "namespace per repository", "Embeddings are numeric representations"]:
        assert needle in t, needle
    assert "source code is transmitted" in t.lower() or "Relevant source code is transmitted to OpenAI" in t
    assert not re.search(r"never (shared|sent|leaves)|not stored|cannot contain|do(es)? not contain (any )?(code|sensitive)", t, re.I)   # no false reassurance
    assert "We do not claim that they cannot reveal information" in t


def test_retention_table_matches_the_default_settings():
    cfg = (ROOT / "backend" / "app" / "core" / "config.py").read_text(encoding="utf-8")
    default = lambda name: int(re.search(rf"{name}: int = (\d+)", cfg).group(1))   # noqa: E731
    t = _text(_doc("privacy"))
    for name, text in [("retention_sessions_days", "7 days after it expires"), ("retention_webhook_days", "30 days"), ("retention_jobs_done_days", "14 days"), ("retention_jobs_failed_days", "60 days"),
                       ("retention_indexing_jobs_days", "30 days (the latest"), ("retention_audit_days", "365 days"), ("retention_security_audit_days", "730 days"), ("retention_invitations_days", "30 days"),
                       ("retention_notifications_days", "Read: 90 days"), ("retention_notifications_max_days", "any: 365 days")]:
        assert text in t, (name, text)
    assert default("retention_sessions_days") == 7 and default("retention_webhook_days") == 30 and default("retention_jobs_done_days") == 14 and default("retention_jobs_failed_days") == 60
    assert default("retention_audit_days") == 365 and default("retention_security_audit_days") == 730 and default("retention_notifications_days") == 90 and default("export_ttl_hours") == 24
    assert default("session_ttl_hours") == 12 and "12 hours" in t


def test_terms_cover_the_required_topics():
    t = _text(_doc("terms")).lower()
    for needle in ["account", "acceptable use", "github", "ai-generated", "responsib", "third-party", "availability", "suspend", "intellectual property", "liability", "data handling", "contact", "governing law"]:
        assert needle in t, needle
    assert "ai model" in t and "not a substitute for human code review" in t


def test_security_policy_has_reporting_instructions_with_placeholder_contacts():
    d = _doc("security")
    t = _text(d)
    for needle in ["Reporting a vulnerability", "What to include", "Scope", "Rules for testing", "What happens next", "{{securityEmail}}", "PGP"]:
        assert needle in t, needle


def test_licence_is_proprietary_and_no_open_source_grant():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "PROPRIETARY" in text and "All rights reserved" in text and "NOT open-source" in text
    assert not re.search(r"Permission is hereby granted|Apache License|GNU General Public|MIT License|BSD", text)
    assert json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))["license"] == "UNLICENSED"
    assert "proprietary" in _text(_doc("license")).lower()


def test_markdown_copies_are_in_sync_with_the_json_source():
    import importlib.util
    spec = importlib.util.spec_from_file_location("gen_legal_docs", ROOT / "backend" / "tools" / "gen_legal_docs.py")
    gen = importlib.util.module_from_spec(spec); spec.loader.exec_module(gen)
    for k, name in gen.NAMES.items():
        assert (DOCS / name).read_text(encoding="utf-8") == gen.render(_doc(k)), f"{name} is stale: run python backend/tools/gen_legal_docs.py"
    assert (DOCS / "PLACEHOLDERS.md").read_text(encoding="utf-8") == gen.render_checklist({k: _doc(k) for k in gen.NAMES})


def test_security_md_has_the_disclosure_section():
    t = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert t.startswith("# Security") and "## Reporting a vulnerability" in t and "## Security design and known limitations" in t
    tmpl = (ROOT / "docs" / "security.txt.template").read_text(encoding="utf-8")
    assert "Do NOT publish it" in tmpl and not (PUB / ".well-known").exists()               # an invalid security.txt must never be served