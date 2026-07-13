#!/usr/bin/env python3
"""Paramasastra — stdlib OOXML (.docx) reader/writer.

The docx analog of plain-text parsing: a .docx is a zip of XML parts;
this module extracts a paragraph stream the validator can consume and
gives docxtool.py safe, whole-paragraph edit primitives. No third-party
dependencies — zipfile + xml.etree only (engine invariant).

Model:
  * The PARAGRAPH is the "line": Finding.line for a .docx is the 1-based
    index of the paragraph in word/document.xml body order (including
    paragraphs inside tables; headers/footers/footnotes are separate
    parts and are not governed in v1).
  * Paragraph text = concatenated w:t runs (run fragmentation is
    invisible after concatenation). Field INSTRUCTION regions
    (fldChar begin..separate) are excluded; field RESULT text is
    included, so extracted prose reads like the rendered document.
    Tracked-change deletions (w:del) are excluded; insertions included.
  * Each paragraph also carries SEGMENTS — the ordered mix of plain
    text and field objects — so docxtool can render citation fields as
    {{field:k}} placeholders and splice them back verbatim on replace
    (a rewrite mechanically cannot drop a Zotero citation).
  * Citations are native fields — Zotero/Mendeley
    `ADDIN [ZOTERO_ITEM] CSL_CITATION {json}` or Word-native
    `CITATION <tag>` resolved against customXml bibliography sources.
  * Heading level = w:outlineLvl resolved through the style basedOn
    chain (never style NAMES — those are localized).
"""
import json
import io
import os
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
B = "http://schemas.openxmlformats.org/officeDocument/2006/bibliography"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def w(tag):
    return f"{{{W}}}{tag}"


CSL_RE = re.compile(r"^\s*ADDIN\s+(?:ZOTERO_ITEM\s+)?CSL_CITATION\b", re.I)
WORD_CITE_RE = re.compile(r"^\s*CITATION\s+(\S+)", re.I)


class DocxError(Exception):
    pass


class CiteField:
    """One reconstructed field. kind: 'csl' (Zotero/Mendeley),
    'word' (native CITATION), 'other' (HYPERLINK/PAGEREF/TOC/... —
    ignored by citation checks). items: [{doi, isbn, title}]."""
    __slots__ = ("para_index", "instr", "kind", "items", "tag", "result",
                 "broken", "reason", "child_span", "matched", "location")

    def __init__(self, para_index, instr):
        self.para_index = para_index
        self.instr = instr
        self.kind = "other"
        self.items = []
        self.tag = None
        self.result = ""
        self.broken = False
        self.reason = ""
        self.child_span = None   # (start, end) indices into list(paragraph)
        self.matched = None      # bib key set by the validator
        self.location = "body"   # or "footnote" (detected, not editable)
        self._classify()

    def _classify(self):
        s = self.instr.strip()
        if CSL_RE.match(s):
            self.kind = "csl"
            brace = s.find("{")
            if brace < 0:
                self.broken, self.reason = True, "CSL field has no JSON payload"
                return
            try:
                data, _ = json.JSONDecoder().raw_decode(s[brace:])
            except ValueError:
                self.broken, self.reason = True, "undecodable CSL JSON payload"
                return
            for ci in data.get("citationItems", []) or []:
                item = ci.get("itemData", {}) or {}
                self.items.append({"doi": item.get("DOI") or "",
                                   "isbn": item.get("ISBN") or "",
                                   "title": item.get("title") or ""})
            return
        m = WORD_CITE_RE.match(s)
        if m:
            self.kind = "word"
            self.tag = m.group(1)

    @property
    def is_citation(self):
        return self.kind in ("csl", "word")


class Para:
    __slots__ = ("index", "element", "text", "segments", "style_id",
                 "outline_level", "fields", "run_count", "mixed_format")

    def __init__(self, index, element):
        self.index, self.element = index, element
        self.text = ""
        self.segments = []       # ordered ("t", str) | ("f", CiteField)
        self.style_id = None
        self.outline_level = None
        self.fields = []         # citation fields anchored here
        self.run_count = 0
        self.mixed_format = False

    def cite_segments(self):
        return [v for k, v in self.segments
                if k == "f" and v.is_citation and not v.broken]


def _parse_part(data):
    """Parse an XML part, returning (root, [(prefix, uri), ...]) so the
    original namespace prefixes can be re-registered before serializing
    (ET would otherwise rename them, breaking mc:Ignorable lists)."""
    ns = []
    for _, pair in ET.iterparse(io.BytesIO(data), events=("start-ns",)):
        ns.append(pair)
    return ET.fromstring(data), ns


def _serialize(root, ns):
    for prefix, uri in ns:
        ET.register_namespace(prefix, uri)
    xml = ET.tostring(root, encoding="unicode")
    xml = _restore_root_namespaces(xml, ns)
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
            + xml).encode("utf-8")


def _restore_root_namespaces(xml, ns):
    """ET.tostring only redeclares a namespace if some surviving tag or
    attribute still uses its URI, silently dropping declarations that
    became unused after an edit (e.g. deleting the last w15:-prefixed
    element). But Word declares every namespace it might ever need on
    the root regardless of whether the current content uses it, and
    prefix-list attributes like mc:Ignorable="w14 w15 wp14" name those
    prefixes as plain text — untouched by ET, since it isn't a QName.
    A dropped declaration leaves such a prefix dangling, which Word's
    strict parser rejects as unreadable content. Re-declaring the
    original root namespaces unconditionally is always safe (a root
    xmlns applies to every descendant) and keeps every part byte-
    identical to Word's own output whenever nothing was actually
    trimmed."""
    end = xml.index(">")
    head = xml[:end]
    missing = []
    for prefix, uri in ns:
        attr = f"xmlns:{prefix}=" if prefix else "xmlns="
        if attr not in head:
            missing.append(f' {attr}"{uri}"')
    if not missing:
        return xml
    return head + "".join(missing) + xml[end:]


def _style_outline_map(styles_root):
    """styleId -> heading level (1-based), resolved through basedOn
    chains. outlineLvl val 0-8 maps to level 1-9; val 9 = body text."""
    info = {}
    for st in styles_root.iter(w("style")):
        if st.get(w("type")) != "paragraph":
            continue
        sid = st.get(w("styleId"))
        lvl = None
        ppr = st.find(w("pPr"))
        if ppr is not None:
            ol = ppr.find(w("outlineLvl"))
            if ol is not None:
                try:
                    v = int(ol.get(w("val"), "9"))
                    lvl = v + 1 if 0 <= v <= 8 else None
                except ValueError:
                    pass
        based = st.find(w("basedOn"))
        info[sid] = (lvl, based.get(w("val")) if based is not None else None)

    resolved = {}

    def resolve(sid, seen):
        if sid in resolved:
            return resolved[sid]
        if sid not in info or sid in seen:
            return None
        seen.add(sid)
        lvl, based = info[sid]
        r = lvl if lvl is not None else (resolve(based, seen) if based else None)
        resolved[sid] = r
        return r

    for sid in info:
        resolve(sid, set())
    return resolved


class Doc:
    def __init__(self, path):
        self.path = path
        try:
            with zipfile.ZipFile(path) as z:
                self.members = {i.filename: z.read(i.filename)
                                for i in z.infolist()}
        except (zipfile.BadZipFile, OSError) as e:
            raise DocxError(f"not a readable .docx zip: {e}")
        if "word/document.xml" not in self.members:
            raise DocxError("word/document.xml missing — not a Word document")
        try:
            self.document, self._doc_ns = _parse_part(
                self.members["word/document.xml"])
        except ET.ParseError as e:
            raise DocxError(f"word/document.xml does not parse: {e}")
        self.styles, self._sty_ns = None, []
        if "word/styles.xml" in self.members:
            try:
                self.styles, self._sty_ns = _parse_part(
                    self.members["word/styles.xml"])
            except ET.ParseError:
                pass
        self._styles_dirty = False
        self._scan()

    # -------------------------------------------------------- scanning

    def _scan(self):
        """One pass over all paragraphs: reconstruct complex fields
        (fldChar state machine — instrText is routinely split across
        runs and reassembled), collect ordered text/field segments,
        resolve heading levels. Text is assembled AFTER the pass so
        cross-paragraph fields still land in their begin paragraph."""
        self.paras, self.fields = [], []
        outline = _style_outline_map(self.styles) if self.styles is not None else {}
        raw = []      # (para, parts) — parts: ("t", str) | ("f", open-dict)
        stack = []    # open complex fields, innermost last
        self._by_index = {}
        for pi, p in enumerate(self.document.iter(w("p")), 1):
            para = Para(pi, p)
            self._by_index[pi] = para
            parts, rprs = [], set()
            for ci, child in enumerate(list(p)):
                self._walk(child, pi, ci, para, parts, rprs, stack)
            para.mixed_format = len(rprs) > 1
            ppr = p.find(w("pPr"))
            if ppr is not None:
                ps = ppr.find(w("pStyle"))
                if ps is not None:
                    para.style_id = ps.get(w("val"))
                ol = ppr.find(w("outlineLvl"))
                if ol is not None:
                    try:
                        v = int(ol.get(w("val"), "9"))
                        para.outline_level = v + 1 if 0 <= v <= 8 else None
                    except ValueError:
                        pass
            if para.outline_level is None and para.style_id:
                para.outline_level = outline.get(para.style_id)
            self.paras.append(para)
            raw.append((para, parts))
        for fo in stack:   # unclosed at EOF => structurally broken
            fld = CiteField(fo["pi"], "".join(fo["instr"]))
            fld.result = "".join(fo["result"])
            fld.broken = True
            fld.reason = fld.reason or "field opened but never closed"
            fo["field_obj"] = fld
            self._register(fld)
        for para, parts in raw:
            segs, buf = [], []
            for k, v in parts:
                if k == "t":
                    buf.append(v)
                    continue
                fld = v.get("field_obj")
                if fld is None:
                    continue   # should not happen; defensive
                if buf:
                    segs.append(("t", "".join(buf)))
                    buf = []
                segs.append(("f", fld))
            if buf:
                segs.append(("t", "".join(buf)))
            para.segments = segs
            para.text = "".join(v if k == "t" else (v.result or "")
                                for k, v in segs)
        self._scan_footnotes()

    def _scan_footnotes(self):
        """Citation fields inside word/footnotes.xml are DETECTED (so a
        fabricated footnote citation cannot hide) but not editable —
        docxtool does not touch footnotes in v1. They report at line 0."""
        data = self.members.get("word/footnotes.xml")
        if not data:
            return
        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            return

        def add(fld, broken=False):
            if not fld.is_citation:
                return
            fld.location = "footnote"
            if broken:
                fld.broken = True
                fld.reason = fld.reason or "field opened but never closed"
            self.fields.append(fld)

        stack = []
        for r in root.iter(w("r")):
            for sub in r:
                if sub.tag == w("fldChar"):
                    t = sub.get(w("fldCharType"))
                    if t == "begin":
                        stack.append([])
                    elif t == "end" and stack:
                        add(CiteField(0, "".join(stack.pop())))
                elif sub.tag == w("instrText") and stack:
                    stack[-1].append(sub.text or "")
        for parts in stack:
            add(CiteField(0, "".join(parts)), broken=True)
        for fs in root.iter(w("fldSimple")):
            add(CiteField(0, fs.get(w("instr"), "")))

    def _walk(self, elem, pi, ci, para, parts, rprs, stack):
        tag = elem.tag
        if tag in (w("pPr"), w("del")):
            return   # properties / tracked-change deletions: not prose
        if tag == w("fldSimple"):
            fld = CiteField(pi, elem.get(w("instr"), ""))
            fld.child_span = (ci, ci)
            fo = {"pi": pi, "ci": ci, "phase": "result",
                  "instr": [], "result": [], "field_obj": None}
            if not stack:
                parts.append(("f", fo))
            stack.append(fo)
            for sub in elem:
                self._walk(sub, pi, ci, para, parts, rprs, stack)
            stack.pop()
            fld.result = "".join(fo["result"])
            fo["field_obj"] = fld
            self._register(fld)
            return
        if tag == w("r"):
            para.run_count += 1
            for sub in elem:
                st = sub.tag
                if st == w("fldChar"):
                    ftype = sub.get(w("fldCharType"))
                    if ftype == "begin":
                        fo = {"pi": pi, "ci": ci, "phase": "instr",
                              "instr": [], "result": [], "field_obj": None}
                        if not stack:
                            parts.append(("f", fo))
                        stack.append(fo)
                    elif ftype == "separate" and stack:
                        stack[-1]["phase"] = "result"
                    elif ftype == "end" and stack:
                        fo = stack.pop()
                        fld = CiteField(fo["pi"], "".join(fo["instr"]))
                        fld.result = "".join(fo["result"])
                        if fo["pi"] != pi:
                            fld.broken = True
                            fld.reason = "field spans multiple paragraphs"
                        else:
                            fld.child_span = (fo["ci"], ci)
                        fo["field_obj"] = fld
                        self._register(fld)
                elif st == w("instrText"):
                    if stack:
                        stack[-1]["instr"].append(sub.text or "")
                elif st in (w("t"), w("tab"), w("br")):
                    txt = ((sub.text or "") if st == w("t")
                           else "\t" if st == w("tab") else " ")
                    if any(f["phase"] == "instr" for f in stack):
                        pass   # field instruction region: not prose
                    elif stack:
                        stack[0]["result"].append(txt)
                    else:
                        parts.append(("t", txt))
                        if st == w("t"):
                            rpr = elem.find(w("rPr"))
                            rprs.add(ET.tostring(rpr, encoding="unicode")
                                     if rpr is not None else "")
            return
        for sub in elem:   # hyperlink / sdtContent / ins / smartTag / ...
            self._walk(sub, pi, ci, para, parts, rprs, stack)

    def _register(self, fld):
        if not fld.is_citation:
            return   # TOC/HYPERLINK/PAGEREF/...: no citation semantics
        self.fields.append(fld)
        para = self._by_index.get(fld.para_index)
        if para is not None:
            para.fields.append(fld)

    # -------------------------------------------------------- queries

    def sources(self):
        """Word-native bibliography: tag -> {doi, isbn, title} parsed
        from customXml/item*.xml (b:Sources)."""
        out = {}
        for name, data in self.members.items():
            if not (name.startswith("customXml/item") and name.endswith(".xml")):
                continue
            try:
                root = ET.fromstring(data)
            except ET.ParseError:
                continue
            if not root.tag.endswith("}Sources"):
                continue
            for src in root.iter(f"{{{B}}}Source"):
                def val(local):
                    el = src.find(f"{{{B}}}{local}")
                    return (el.text or "").strip() if el is not None else ""
                tag = val("Tag")
                if tag:
                    out[tag] = {"doi": val("DOI"),
                                "isbn": val("StandardNumber"),
                                "title": val("Title")}
        return out

    def body(self):
        b = self.document.find(w("body"))
        if b is None:
            raise DocxError("document has no w:body")
        return b

    def parent_of(self, elem):
        for parent in self.document.iter():
            for child in parent:
                if child is elem:
                    return parent
        return None

    # -------------------------------------------------------- mutation

    def append_paragraph(self, p_elem):
        """Insert before the trailing sectPr (Word convention)."""
        b = self.body()
        kids = list(b)
        if kids and kids[-1].tag == w("sectPr"):
            b.insert(len(kids) - 1, p_elem)
        else:
            b.append(p_elem)

    def insert_paragraph(self, p_elem, ref_para, before=False):
        parent = self.parent_of(ref_para.element)
        if parent is None:
            raise DocxError(f"paragraph {ref_para.index} has no parent")
        idx = list(parent).index(ref_para.element)
        parent.insert(idx if before else idx + 1, p_elem)

    def remove_paragraph(self, para):
        parent = self.parent_of(para.element)
        if parent is None:
            raise DocxError(f"paragraph {para.index} has no parent")
        parent.remove(para.element)

    def ensure_style(self, style_id, xml_template):
        """Create a paragraph style if styles.xml lacks it."""
        if self.styles is None:
            raise DocxError("document has no styles.xml part")
        for st in self.styles.iter(w("style")):
            if st.get(w("styleId")) == style_id:
                return False
        self.styles.append(ET.fromstring(xml_template))
        self._styles_dirty = True
        return True

    def save(self, path=None):
        """Atomic in-place save: only document.xml (and styles.xml when
        touched) are re-serialized; every other zip member is copied
        byte-for-byte."""
        path = path or self.path
        self.members["word/document.xml"] = _serialize(self.document,
                                                       self._doc_ns)
        if self._styles_dirty and self.styles is not None:
            self.members["word/styles.xml"] = _serialize(self.styles,
                                                         self._sty_ns)
        d = os.path.dirname(os.path.abspath(path)) or "."
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".docx.tmp")
        os.close(fd)
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
                for name, data in self.members.items():
                    z.writestr(name, data)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        self._scan()


def load(path):
    return Doc(path)


# ---------------------------------------------------------------- matching


def _norm_doi(d):
    return re.sub(r"^https?://(?:dx\.)?doi\.org/", "", (d or "").strip().lower())


def _norm_isbn(i):
    return re.sub(r"[^0-9Xx]", "", i or "").upper()


def match_bib(item, entries, threshold=0.85):
    """Map one cited item {doi, isbn, title} to a bib entry: DOI first,
    ISBN second, fuzzy title last (reusing citecheck's matcher).
    Returns (key or None, how)."""
    doi = _norm_doi(item.get("doi", ""))
    if doi:
        for e in entries:
            if _norm_doi(e["fields"].get("doi", "")) == doi:
                return e["key"], "doi"
    isbn = _norm_isbn(item.get("isbn", ""))
    if isbn:
        for e in entries:
            if _norm_isbn(e["fields"].get("isbn", "")) == isbn:
                return e["key"], "isbn"
    title = (item.get("title") or "").strip()
    if title:
        from citecheck import similar
        best, score = None, 0.0
        for e in entries:
            bt = e["fields"].get("title", "")
            if bt:
                s = similar(title, bt)
                if s > score:
                    best, score = e["key"], s
        if best and score >= threshold:
            return best, "title"
    return None, "none"


# ---------------------------------------------------------------- validator


def iter_prose_units(doc, cfg):
    """Validator frontend: yields (para_index, prose, raw, meta) with a
    synthetic blank unit after every paragraph so each paragraph is its
    own density scope. Marker paragraphs surface their token text in
    raw, so workflow-marker regexes match verbatim."""
    levels = set(cfg.get("docx", {}).get("density_section_levels", [1, 2]))
    for para in doc.paras:
        lvl = para.outline_level
        yield para.index, para.text, para.text, {
            "blank": not para.text.strip(),
            "heading": lvl is not None and lvl in levels,
            "level": lvl, "cites": para.fields}
        yield para.index, "", "", {"blank": True, "heading": False}


# ---------------------------------------------------------------- builders


def make_run(text, rpr=None):
    r = ET.Element(w("r"))
    if rpr is not None:
        r.append(rpr)
    t = ET.SubElement(r, w("t"))
    t.set(XML_SPACE, "preserve")
    t.text = text
    return r


def make_paragraph(text="", style_id=None):
    p = ET.Element(w("p"))
    if style_id:
        ppr = ET.SubElement(p, w("pPr"))
        ET.SubElement(ppr, w("pStyle")).set(w("val"), style_id)
    if text:
        p.append(make_run(text))
    return p


def fld_char_run(fld_type):
    r = ET.Element(w("r"))
    ET.SubElement(r, w("fldChar")).set(w("fldCharType"), fld_type)
    return r


def instr_run(text):
    r = ET.Element(w("r"))
    it = ET.SubElement(r, w("instrText"))
    it.set(XML_SPACE, "preserve")
    it.text = text
    return r


def csl_field_runs(csl_json_text, result_text, split=1):
    """A complete Zotero-compatible complex field as a run list. split>1
    fragments the instruction across runs (as Word itself does), which
    the scanner must reassemble — selftest uses this to prove it."""
    instr = " ADDIN ZOTERO_ITEM CSL_CITATION " + csl_json_text + " "
    runs = [fld_char_run("begin")]
    n = max(1, int(split))
    step = max(1, (len(instr) + n - 1) // n)
    for i in range(0, len(instr), step):
        runs.append(instr_run(instr[i:i + step]))
    runs.append(fld_char_run("separate"))
    runs.append(make_run(result_text))
    runs.append(fld_char_run("end"))
    return runs


MARKER_STYLE_XML = f"""<w:style xmlns:w="{W}" w:type="paragraph" w:styleId="{{style_id}}">
<w:name w:val="Harness Marker"/><w:basedOn w:val="Normal"/>
<w:pPr><w:shd w:val="clear" w:color="auto" w:fill="FFF2CC"/></w:pPr>
<w:rPr><w:color w:val="7F6000"/></w:rPr>
</w:style>"""


# ---------------------------------------------------------------- new file

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

_STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W}">
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:b/><w:sz w:val="24"/></w:rPr></w:style>
</w:styles>"""

_DOCUMENT = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W}"><w:body><w:sectPr/></w:body></w:document>"""


def new_docx(path, title=None):
    """Write a minimal valid .docx (used by docxtool new, the scaffold
    skill, and selftest fixtures — no binary fixtures in git)."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
        z.writestr("word/styles.xml", _STYLES)
        z.writestr("word/document.xml", _DOCUMENT)
    if title:
        doc = load(path)
        doc.append_paragraph(make_paragraph(title, style_id="Heading1"))
        doc.save()
    return path
