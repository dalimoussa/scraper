"""
Parser for the Bet365 "gen5" delimited feed format.

This is a faithful port of the tree-reconstruction logic in Bet365's own
client bundle (DataUtil.ParseMessage). Instead of keeping records in a flat
list and navigating them by index, it rebuilds the real node tree.

Wire format
-----------
A transport buffer may contain several *frames* separated by ``\\b`` (0x08).
Each frame is::

    <TYPE> | <record> | <record> | ...

  TYPE   : one char  -> F=snapshot  U=update  I=insert  D=delete
  record : "<NT>;K1=v1;K2=v2;..."   (a trailing ';' yields an empty last field)
  NT     : 2-letter node type (CL, EV, MG, MA, PA, CO, ...)
  fields : 2-char key, the '=' at index 2 is skipped, value is the rest

The hierarchy is NOT encoded with indentation or parent ids. It is implied by
record ORDER plus a "currently open node" pointer per node type: every record
attaches to the nearest open ancestor and then becomes the current pointer for
its own type. (``|`` and newlines are both accepted as record separators, so a
log where ``|`` was replaced by ``\\n`` parses identically.)
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterator, List


FILTER_TOKEN = re.compile(r"(IF|W0|01)")
ESPORTS_CLASSIFICATION_ID = "151"



# ---------------------------------------------------------------------------
# node model (mirrors the Stem / FixtureStem classes in the bet365 bundle)
# ---------------------------------------------------------------------------

class Node:
    __slots__ = ("type", "properties", "children", "parent",
                 "team_groups", "stat_groups", "additional_scores", "filtered")

    def __init__(self, node_type: str | None = None):
        self.type = node_type
        self.properties: Dict[str, str] = {}
        self.children: List["Node"] = []        # _actualChildren
        self.parent: "Node | None" = None
        self.team_groups: List["Node"] = []     # FixtureStem TG side-array
        self.stat_groups: List["Node"] = []     # FixtureStem SG side-array
        self.additional_scores: List["Node"] = []  # FixtureStem ES side-array
        self.filtered = False                    # hidden by FF filter flags

    # -- property helpers (kept API-compatible with the old Bet365Section) --
    def get_property(self, key: str, default: Any = "") -> str:
        return str(self.properties.get(key, default))

    def has_property(self, key: str) -> bool:
        return key in self.properties

    def as_section_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "properties": self.properties}

    # -- traversal ----------------------------------------------------------
    def visible_children(self) -> List["Node"]:
        return [c for c in self.children if not c.filtered]

    def walk(self) -> Iterator["Node"]:
        """Depth-first iterator over this node and all descendants."""
        yield self
        for child in self.children:
            yield from child.walk()

    def find_sections(self, node_type: str | None = None, **filters) -> Iterator["Node"]:
        """Yield every descendant matching ``node_type`` and ``filters``.

        A filter value may be a plain string (equality against the property)
        or a callable ``(key, value) -> bool``.
        """
        for node in self.walk():
            if node_type is not None and node.type != node_type:
                continue
            if node._matches(filters):
                yield node

    def _matches(self, filters: Dict[str, Any]) -> bool:
        for key, expected in filters.items():
            actual = self.get_property(key)
            if callable(expected):
                if not expected(key, actual):
                    return False
            elif actual != expected:
                return False
        return True
    
    @property
    def label(self):
        return (self.get_property("NA") or self.get_property("FD")
                 or self.get_property("OD"))

    def __repr__(self) -> str:
        label = (self.label or self.properties)
        return f"<Node {self.type} {label!r} children={len(self.children)}>"


def _attach(parent: Node, child: Node) -> Node:
    child.parent = parent
    parent.children.append(child)
    return child


# ---------------------------------------------------------------------------
# field / FF parsing
# ---------------------------------------------------------------------------

def _is_filtered(ff: str) -> bool:
    """Port of the FilterToken (/\\^\\^\\^/) scan: filtered if a ``^^^`` token
    starts at an even index."""
    idx = 0
    while True:
        pos = ff.find("^^^", idx)
        if pos == -1:
            return False
        if not (pos & 1):
            return True
        idx = pos + 2


def _parse_record(record: str, start: int):
    parts = record.split(";")
    node_type = parts[0]
    props: Dict[str, str] = {}
    # len-1 drops the trailing empty field produced by the closing ';'
    for s in parts[start:len(parts) - 1]:
        if len(s) >= 2:
            props[s[:2]] = s[3:]   # 2-char key, skip '=' at index 2, rest is value
    return node_type, props


# ---------------------------------------------------------------------------
# the core: rebuild the tree from record order
# ---------------------------------------------------------------------------

def parse_message(msg_type: str, records: List[str]) -> Node:
    snapshot = (msg_type == "F")
    start = 1 if snapshot else 0   # snapshot records lead with the node-type token

    root = Node("ROOT")

    # one "currently open" pointer per node type (the locals in ParseMessage)
    cl = ev = mg = ma = co = pa = ct = cs = None
    tg = sg = es = sc = asec = ap = at = ac = None
    op = be = sh = pd = ps = xl = None
    num_stack: Dict[int, Node] = {}    # I[] -> generic numeric-depth nesting
    h: Node | None = None              # last node (persists across records)

    for rec in records:
        if not rec:
            continue
        d, props = _parse_record(rec, start)

        if d == "PA":                                   # participant / selection
            h = Node(); _attach(co or ma or be or sh or root, h); pa = h
        elif d == "CO":                                 # market column
            h = Node(); _attach(ma or sh or root, h); co = h
        elif d == "MA":                                 # market
            co = None
            h = Node(); _attach(mg or ev or sh or root, h); ma = h
        elif d == "MG":                                 # market group
            co = None
            h = Node(); _attach(ev or sh or root, h); mg = h
        elif d == "CT":                                 # category
            h = Node(); _attach(cl or sh or root, h); ct = h
        elif d == "EV":                                 # event (FixtureStem)
            h = Node()
            if cl is None:
                cl = pd or sh or root
            _attach(ct or cl, h); ev = h
        elif d == "CL":                                 # classification
            ct = None
            h = Node(); _attach(cs or sh or root, h); cl = h
        elif d == "CS":                                 # class section
            h = Node(); _attach(root, h); cs = h
        elif d == "TG":                                 # team group -> EV side-array
            h = Node(); h.parent = ev; (ev or root).team_groups.append(h); tg = h
        elif d == "TE":
            h = Node(); _attach(tg or root, h)
        elif d == "SG":                                 # stat group -> EV side-array
            h = Node(); h.parent = ev; (ev or root).stat_groups.append(h); sg = h
        elif d == "ST":
            h = Node(); _attach(sg or root, h)
        elif d == "ES":                                 # extra score -> EV side-array
            h = Node(); h.parent = ev; (ev or root).additional_scores.append(h); es = h
        elif d == "SC":
            h = Node(); _attach(es or root, h); sc = h
        elif d == "SL":
            h = Node(); _attach(sc or root, h)
        elif d == "AS":
            h = Node(); _attach(ev or sh or root, h); asec = h
        elif d == "AP":
            h = Node(); _attach(asec or root, h); ap = h
        elif d == "AT":
            h = Node(); _attach(ap or root, h); at = h
        elif d == "AC":
            h = Node(); _attach(at or root, h); ac = h
        elif d == "AE":
            h = Node(); _attach(ac or root, h)
        elif d == "SP":                                 # sub-participant
            h = Node(); _attach(pa or root, h)
        elif d == "IN":                                 # info/header (no node)
            h = None
        elif d == "PD":                                 # pull/drill-down container
            h = Node()
            if ps is None:
                ps = xl or sh or root
            _attach(ps, h); pd = h
        elif d == "PS":
            h = Node()
            if xl is None:
                xl = root
            _attach(xl, h); ps = h
        elif d == "XL":
            h = Node(); _attach(root, h); xl = h
        elif d == "LG":                                 # reparents current node under EV
            if h is not None and ev is not None:
                _attach(ev, h)
        elif d in ("XI", "CG"):                         # new root context
            h = Node("ROOT"); root = h
        elif d in ("OP", "CF"):
            h = Node(); op = h
        elif d == "BE":
            h = Node(); _attach(op or root, h); be = h
        elif d == "SH":                                 # shadow / reset boundary
            h = Node(); sh = h
            cs = ev = mg = ma = co = None
            num_stack = {}
        else:                                           # numeric depth stack
            if d and d.lstrip("-").isdigit():
                level = int(d)
                h = Node()
                if level:
                    _attach(num_stack.get(level - 1, root), h)
                    num_stack[level] = h
                else:
                    h.parent = root
                    num_stack[0] = h
                    if root.children:
                        root.children[0] = h
                    else:
                        root.children.append(h)
            else:
                h = None

        if h is not None:
            h.type = d
            h.properties = props
            ff = props.get("FF")
            if ff:
                h.filtered = _is_filtered(ff)

    # snapshot collapse: a lone top-level PA becomes the root
    if len(root.children) == 1 and root.children[0].type == "PA":
        root = root.children[0]
    return root


# ---------------------------------------------------------------------------
# transport-buffer splitting (frames -> messages -> trees)
# ---------------------------------------------------------------------------

_RECORD_SEP = re.compile(r"[\b|\n\r]+")   # backspace frames, pipe + newline records


def get_parsers(data: str) -> List[Node]:
    """Parse a raw transport buffer into a list of message root Nodes.

    A new message starts at each bare ``F``/``U``/``I``/``D`` token.
    """
    roots: List[Node] = []
    msg_type: str | None = None
    records: List[str] = []

    for token in _RECORD_SEP.split(data):
        if not token:
            continue
        if len(token) == 1 and token in "FUID":     # message boundary
            if msg_type is not None:
                roots.append(parse_message(msg_type, records))
            msg_type, records = token, []
        else:
            records.append(token)

    if msg_type is not None:
        roots.append(parse_message(msg_type, records))
    return roots


def parse_file(path: str) -> List[Node]:
    with open(path, encoding="utf-8") as fh:
        return get_parsers(fh.read())


# ---------------------------------------------------------------------------
# table extraction (now driven by the tree, not flat-list index math)
# ---------------------------------------------------------------------------

def read_table(market_group: Node, extra_properties: List[str] | None = None) -> Dict[str, Any]:
    """Turn a market-group (MG) node into a column/row table.

    Each MA child is a column (or, if it has CO children, each CO is a column);
    the column's PA descendants are the rows.
    """
    extra_properties = extra_properties or []
    result: Dict[str, Any] = {"title": market_group.get_property("NA"), "data": []}

    def add_column(source: Node, name: str):
        rows = [pa for pa in source.children if pa.type == "PA"]
        extra = {p: source.get_property(p) for p in extra_properties if source.get_property(p)}
        result["data"].append({"name": name or "No row", "values": rows, "extra": extra})

    for ma in market_group.children:
        if ma.type != "MA":
            continue
        columns = [c for c in ma.children if c.type == "CO"]
        if columns:
            for co in columns:
                add_column(co, co.get_property("NA") or ma.get_property("NA"))
        else:
            add_column(ma, ma.get_property("NA"))
    return result


def parse_bb(data: str) -> Dict[str, Any]:
    """Parse a 'BB' (button bar) property value into a dict."""
    results = {}
    for line in data.split("@"):
        parts = line.split(",")
        results[parts[0]] = {"PD": parts[1], "is_active": bool(int(parts[2]))}
    return results


def fix_data(table: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = table["data"]
    if not data or not data[0]["values"]:
        return []
    result = []
    for i in range(len(data[0]["values"])):
        result.append(
            {
                "FD": data[0]["values"][i].get_property("FD", ""),
                "ODS": [
                    data[j]["values"][i].get_property("OD", "")
                    for j in range(1, len(data))
                ],
                "ODS_IDS": [
                    data[j]["values"][i].get_property("ID", "")
                    for j in range(1, len(data))
                ],
                "other_properties": data[0]["values"][i].properties,
            }
        )
    return result

def parse_market(text):
    parts = text.split("@@")

    classification_id = ""
    market_group_parent_id = ""
    market_name = ""

    if len(parts) > 1:
        extra = parts[1].split("¬")
        classification_id = extra[0]

        if len(extra) > 1:
            tmp = extra[1].split("+")
            market_group_parent_id = tmp[0]
            if len(tmp) > 1:
                market_name = tmp[1]

    fields = parts[0].split("$")

    market_id = fields[0]
    headings = fields[1].split("¬") if len(fields) > 1 and fields[1] else []
    participant_count = int(fields[2]) if len(fields) > 2 and fields[2] else 0
    participant_headings = fields[3:]

    return {
        "id": market_id,
        "classificationId": classification_id,
        "marketGroupParentId": market_group_parent_id,
        "headings": headings,
        "participantCount": participant_count,
        "participantHeadings": participant_headings,
        "marketName": market_name,
    }


def parse_market_group(text):
    display_secondary_markets = ("@@" not in text) and ("@1" in text)

    if display_secondary_markets:
        text = text.replace("@1", "")

    sep = text.find("^")
    if sep == -1:
        return None

    header = text[:sep].split("#")

    group_id = header[0] if len(header) > 0 else ""
    name = header[1] if len(header) > 1 else ""
    draw_text = header[2] if len(header) > 2 else ""
    filter_text = header[3] if len(header) > 3 else ""

    # JS equivalent:
    # FilterToken.exec(undefined) searches "undefined"
    for m in FILTER_TOKEN.finditer(str(filter_text)):
        if m.start() % 2 == 0:
            return None

    markets = []
    horizontal = False

    for market_text in text[sep + 1:].split("^"):
        if not market_text:
            continue

        market = parse_market(market_text)

        if len(market["headings"]) > 1:
            horizontal = True

        if (
            market["classificationId"]
            and market["classificationId"] != ESPORTS_CLASSIFICATION_ID
        ):
            display_secondary_markets = True

        markets.append(market)

    return {
        "id": group_id,
        "name": name,
        "drawText": draw_text,
        "markets": markets,
        "horizontal": horizontal,
        "displaySecondaryMarkets": display_secondary_markets,
    }