"""Validate the manifest and the content kinds shipped by this pack (Python 3.12+)."""
import json
import math
from pathlib import Path, PureWindowsPath
import re

ROOT = Path(__file__).resolve().parents[1]
MIB = 1024 * 1024
KINDS = {"shapes", "templates", "palettes"}
ID = r"[a-z0-9]+(?:-[a-z0-9]+)*"
HEX = r"#[0-9a-fA-F]{6}"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def keys(value, required, optional=""):
    required, optional = set(required.split()), set(optional.split())
    require(isinstance(value, dict) and required <= value.keys() <= required | optional,
            f"Expected keys {sorted(required)} with optional {sorted(optional)}: {value!r}")


def unique_pairs(pairs):
    result = dict(pairs)
    require(len(result) == len(pairs), "Duplicate JSON object key")
    return result


def load(path, limit=MIB):
    require(path.is_file() and not path.is_symlink() and not path.is_junction(), f"Invalid file: {path}")
    data = path.read_bytes()
    require(len(data) <= limit, f"File exceeds byte limit: {path}")
    return json.loads(data.decode("utf-8"), object_pairs_hook=unique_pairs,
                      parse_constant=lambda token: number(token))


def matches(value, pattern):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def identifier(value):
    require(matches(value, ID) and len(value) <= 48, f"Invalid identifier: {value!r}")
    return value


def seq(value, low, high):
    require(isinstance(value, list) and low <= len(value) <= high, f"Expected {low}–{high} entries")
    return value


def number(value, low=-math.inf, high=math.inf):
    require(type(value) in (int, float) and math.isfinite(value) and low <= value <= high,
            f"Invalid number {value!r}, expected {low}–{high}")
    return value


def positive(value, high=math.inf):
    require(number(value, 0, high) > 0, "Expected a positive value")
    return value


def color(value, alpha=True):
    require(matches(value, HEX + (r"(?:[0-9a-fA-F]{2})?" if alpha else "")), f"Invalid hex colour: {value}")


def point(value):
    keys(value, "x y")
    return number(value["x"]), number(value["y"])


def plus(a, b):
    return tuple(x + y for x, y in zip(a, b))


def cubic_extrema(a, b, c, d):
    """Return interior extrema of one axis of a cubic Bézier."""
    p, q, r = -a + 3*b - 3*c + d, 2*(a - 2*b + c), b - a
    if p == 0:
        roots = [-r/q] if q else []
    else:
        discriminant = q*q - 4*p*r
        roots = [(-q + sign*math.sqrt(discriminant))/(2*p) for sign in (-1, 1)] if discriminant >= 0 else []
    return [(1-t)**3*a + 3*(1-t)**2*t*b + 3*(1-t)*t*t*c + t**3*d for t in roots if 0 < t < 1]


def bounds(g):
    kind = g.get("kind")
    if kind == "line":
        keys(g, "kind start end")
        start, end = point(g["start"]), point(g["end"])
        require(start != end, "Line endpoints must differ")
        return tuple(zip(start, end))
    if kind in {"rectangle", "ellipse"}:
        keys(g, "kind widthPt heightPt" + (" cornerRadiusPt" if kind == "rectangle" else ""))
        w, h = (positive(g[key], 100_000) for key in ("widthPt", "heightPt"))
        if kind == "rectangle":
            number(g["cornerRadiusPt"], 0, min(w, h)/2)
        return (0, w), (0, h)
    require(kind == "spline", f"Unknown geometry kind: {kind}")
    keys(g, "kind nodes closed")
    require(type(g["closed"]) is bool, "Spline closed must be a Boolean")
    nodes = []
    for node in seq(g["nodes"], 3 if g["closed"] else 2, 256):
        keys(node, "point", "handleIn handleOut")
        anchor = point(node["point"])
        handles = [plus(anchor, point(node[key])) if node.get(key) is not None else anchor
                   for key in ("handleIn", "handleOut")]
        nodes.append((anchor, *handles))
    extents = [list(axis) for axis in zip(*(node[0] for node in nodes))]
    successors = nodes[1:] + (nodes[:1] if g["closed"] else [])
    for (start, _, outgoing), (end, incoming, _) in zip(nodes, successors):
        for axis in range(2):
            controls = [number(p[axis]) for p in (start, outgoing, incoming, end)]
            extents[axis].extend(cubic_extrema(*controls))
    return extents


def shape_object(obj, w, h):
    if obj.get("type") == "typst":
        keys(obj, "type x y source layoutWidthPt scale")
        source = obj["source"]
        require(isinstance(source, str) and 0 < len(source.encode("utf-8")) <= 2048,
                "Typst label source must be 1–2048 bytes")
        # Check its declared width. The sandboxed host measures the text height after compilation.
        overhang = max(w, h) / 2
        x = number(obj["x"], -overhang, w + overhang)
        number(obj["y"], -overhang, h + overhang)
        number(x + positive(obj["layoutWidthPt"], 10_000) * positive(obj["scale"]), -overhang, w + overhang)
        return
    keys(obj, "type x y geometry style")
    require(obj["type"] == "shape" and isinstance(obj["geometry"], dict), "Expected shape geometry")
    for values, offset, extent in zip(bounds(obj["geometry"]), (obj["x"], obj["y"]), (w, h)):
        number(offset)
        for coordinate in values:
            number(offset + coordinate, -1e-9, extent + 1e-9)
    style = obj["style"]
    keys(style, "", "strokeColor strokeWidthPt fillColor opacity pattern patternSpacing patternOffsetPt")
    if "strokeColor" in style:
        color(style["strokeColor"])
    if style.get("fillColor") not in (None, "pen"):
        color(style["fillColor"])
    positive(style.get("strokeWidthPt", 1), 256)
    number(style.get("opacity", 1), 0, 1)
    require(style.get("pattern", "solid") in ("solid", "dashed", "dotted"), "Invalid stroke pattern")
    number(style.get("patternSpacing", 1), 0.5, 3)
    number(style.get("patternOffsetPt", 0), 0, 1e6)


def template(value, prefix):
    keys(value, "id name backgroundColor elements")
    key = value["id"]
    require(isinstance(key, str) and key.startswith(prefix) and len(key.encode("utf-8")) <= 64,
            f"Expected template ID prefix {prefix}")
    identifier(key.removeprefix(prefix))
    name = value["name"]
    require(isinstance(name, str) and 0 < len(name.encode("utf-8")) <= 96, "Invalid template name")
    color(value["backgroundColor"])
    for element in seq(value["elements"], 0, 16):
        kind = element.get("kind")
        require(kind in ("grid", "dots", "rule", "horizontal_lines", "vertical_lines"), "Unknown template element")
        measure = "radiusPt" if kind == "dots" else "weightPt"
        extra = "edge offsetPt" if kind == "rule" else "spacingPt"
        keys(element, f"kind area color {measure} {extra}", "major" if kind == "grid" else "")
        area = element["area"]
        keys(area, "topPt rightPt bottomPt leftPt")
        for inset in area.values():
            number(inset, 0, 2000)
        color(element["color"])
        positive(element[measure], 8)
        if kind == "rule":
            require(element["edge"] in ("top", "right", "bottom", "left", "center_x", "center_y"), "Unknown rule edge")
            number(element["offsetPt"], -2000, 2000)
        else:
            number(element["spacingPt"], 3, 500)
        if kind == "grid" and (major := element.get("major")) is not None:
            keys(major, "every color weightPt")
            require(type(major["every"]) is int, "Major interval must be an integer")
            number(major["every"], 0, 64)
            color(major["color"])
            number(major["weightPt"], 0, 8)
    return key


def payload_path(root, kind, relative):
    # The host accepts exactly content/<kind>/<file>.json.
    require(matches(relative, rf"content/{kind}/[a-zA-Z0-9_-]+\.json"),
            f"Invalid {kind} path: {relative}")
    parts = relative.split("/")
    require(not any(PureWindowsPath(part).is_reserved() for part in parts),
            f"Invalid Windows package path: {relative}")
    path = root
    for part in parts:
        path = path / part
        require(not path.is_symlink() and not path.is_junction(), f"Unexpected link: {path}")
    return path


def add_id(seen, identifier_value):
    require(identifier_value not in seen, f"Duplicate declaration ID: {identifier_value}")
    seen.add(identifier_value)


def validate(root=ROOT, *, report=True):
    manifest_path = root / "goodtype-addon.json"
    m = load(manifest_path, 64 * 1024)
    keys(m, "manifestVersion id version apiVersion target transport contents strings settings permissions commands")
    addon_id = identifier(m["id"])
    require(type(m["manifestVersion"]) is int and m["manifestVersion"] == 1, "Expected manifest version 1")
    require(matches(m["version"], r"[0-9]+\.[0-9]+\.[0-9]+") and len(m["version"]) <= 32, "Invalid release version")
    require(m["apiVersion"] == "goodtype-api 0.1" and m["target"] == "x86_64-pc-windows-msvc"
            and m["transport"] == "content", "Wrong API, target or transport")
    require(m.get("permissions", []) == m.get("commands", []) == m["settings"] == [], "Expected empty privileges and settings")
    strings = m["strings"]
    keys(strings, "en de")
    for catalog in strings.values():
        require(isinstance(catalog, dict) and "name" in catalog and len(catalog) <= 128, "Invalid localization table")
        for key, label in catalog.items():
            identifier(key)
            require(matches(label, r"[^<>\x00-\x1f\x7f-\x9f]{1,256}") and "{{" not in label and "}}" not in label,
                    f"Invalid plain-text translation for {key}")
    require(strings["en"].keys() == strings["de"].keys(), "Locale keys differ")

    def label(key):
        require(identifier(key) in strings["en"], f"Missing localized string: {key}")

    contents = m["contents"]
    require(isinstance(contents, dict) and contents.keys() <= KINDS,
            "This pack validates only shapes, templates and palettes")
    inventory = {"goodtype-addon.json": manifest_path}
    folded_paths = set()
    counts = {"libraries": 0, "shapes": 0, "templates": 0, "palettes": 0}
    ids = {kind: set() for kind in ("libraries", "templates", "palettes")}
    for kind, files in contents.items():
        for relative in seq(files, 0, 32):
            path = payload_path(root, kind, relative)
            add_id(folded_paths, relative.casefold())
            inventory[relative] = path
            data = load(path)
            try:
                if kind == "shapes":
                    keys(data, "id label items")
                    add_id(ids["libraries"], identifier(data["id"]))
                    label(data["label"])
                    counts["libraries"] += 1
                    item_ids = set()
                    for item in seq(data["items"], 1, 512):
                        keys(item, "id label search widthPt heightPt objects")
                        add_id(item_ids, identifier(item["id"]))
                        label(item["label"])
                        label(item["search"])
                        w, h = (positive(item[key], 100_000) for key in ("widthPt", "heightPt"))
                        for obj in seq(item["objects"], 1, 64):
                            shape_object(obj, w, h)
                        counts["shapes"] += 1
                else:
                    keys(data, kind)
                    for item in seq(data[kind], 0, 32 if kind == "templates" else 16):
                        label(item["label"])
                        if kind == "templates":
                            keys(item, "label template")
                            item_id = template(item["template"], addon_id + ".")
                        else:
                            keys(item, "id label colors")
                            item_id = identifier(item["id"])
                            colors = seq(item["colors"], 2, 24)
                            for swatch in colors:
                                color(swatch, alpha=False)
                            require(len({c.lower() for c in colors}) == len(colors), "Duplicate palette colour")
                        add_id(ids[kind], item_id)
                        counts[kind] += 1
            except (ValueError, AttributeError, KeyError, TypeError, OverflowError) as exc:
                raise ValueError(f"{relative}: {exc}") from exc
    require(len(inventory) > 1, "Content pack must list at least one file")
    require(counts["shapes"] <= 512 and counts["templates"] <= 32 and counts["palettes"] <= 16, "Pack exceeds item limit")
    require(sum(path.stat().st_size for path in inventory.values()) <= 16*MIB, "Expanded package exceeds 16 MiB")
    require({p.relative_to(root).as_posix() for p in (root / "content").rglob("*") if not p.is_dir()}
            == set(inventory) - {"goodtype-addon.json"}, "Content inventory differs from the manifest")
    if report:
        print(f"{addon_id} {m['version']} valid: " + ", ".join(f"{n} {kind}" for kind, n in counts.items()))
    return m, inventory


if __name__ == "__main__":
    try:
        validate()
    except (ValueError, KeyError, OSError, OverflowError) as exc:
        raise SystemExit(str(exc))
