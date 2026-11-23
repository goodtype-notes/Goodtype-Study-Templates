"""Render the pack's editable geometry to SVG and PNG (requires pymupdf)."""
from html import escape
import math

import pymupdf

from validate import ROOT, load, plus, point, validate

OUT = ROOT / "target/preview"
PAPER = "#fcfbf7"
INK = "#172b3c"
MUTED = "#475c6d"
A4 = (210 * 72 / 25.4, 297 * 72 / 25.4)


def text(x, y, value, size, color=INK, *, center=False, bold=False):
    return (f'<text x="{x}" y="{y}" font-family="sans-serif" font-size="{size}" '
            f'fill="{color}" text-anchor="{"middle" if center else "start"}" '
            f'font-weight="{"bold" if bold else "normal"}">{escape(value)}</text>')


def group(content, x, y, scale=1):
    return f'<g transform="translate({x} {y}) scale({scale})">{content}</g>'


def rect(x, y, w, h, fill):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}"/>'


def svg_line(x1, y1, x2, y2, color, weight):
    return f'<path d="M{x1} {y1}L{x2} {y2}" stroke="{color}" stroke-width="{weight}"/>'


def draw_object(obj):
    if obj["type"] != "shape":
        raise ValueError("This pack's preview supports vector drawings only")
    g, style = obj["geometry"], obj["style"]
    stroke = style.get("strokeColor", INK)
    fill = style.get("fillColor") or "none"
    attrs = (f'fill="{fill}" stroke="{stroke}" stroke-width="{style.get("strokeWidthPt", 1.35)}" '
             f'opacity="{style.get("opacity", 1)}" stroke-linecap="round" stroke-linejoin="round"')
    kind = g["kind"]
    if kind == "line":
        x, y = point(g["start"])
        u, v = point(g["end"])
        drawing = f'<path d="M{x} {y} L{u} {v}" {attrs}/>'
    elif kind == "rectangle":
        drawing = f'<rect width="{g["widthPt"]}" height="{g["heightPt"]}" rx="{g["cornerRadiusPt"]}" {attrs}/>'
    elif kind == "ellipse":
        rx, ry = g["widthPt"]/2, g["heightPt"]/2
        drawing = f'<ellipse cx="{rx}" cy="{ry}" rx="{rx}" ry="{ry}" {attrs}/>'
    else:
        knots = g["nodes"]
        positions = [point(knot["point"]) for knot in knots]
        commands = ["M{} {}".format(*positions[0])]
        for index in range(len(knots) if g["closed"] else len(knots)-1):
            successor = (index+1) % len(knots)
            start, end = positions[index], positions[successor]
            outgoing, incoming = knots[index].get("handleOut"), knots[successor].get("handleIn")
            if outgoing or incoming:
                a = plus(start, point(outgoing)) if outgoing else start
                b = plus(end, point(incoming)) if incoming else end
                commands.append("C{} {} {} {} {} {}".format(*a, *b, *end))
            else:
                commands.append("L{} {}".format(*end))
        if g["closed"]:
            commands.append("Z")
        drawing = f'<path d="{" ".join(commands)}" {attrs}/>'
    return group(drawing, obj["x"], obj["y"])


def centered(start, end, spacing):
    midpoint = (start+end)/2
    reach = math.floor((end-start)/2/spacing)
    return [midpoint + i*spacing for i in range(-reach, reach+1)]


def draw_template(template):
    w, h = A4
    paper = [rect(0, 0, w, h, template["backgroundColor"])]
    for e in template["elements"]:
        a = e["area"]
        left, top, right, bottom = a["leftPt"], a["topPt"], w-a["rightPt"], h-a["bottomPt"]
        if left >= right or top >= bottom:
            continue
        kind, color = e["kind"], e["color"]
        if kind == "rule":
            offset = e["offsetPt"]
            edge = e["edge"]
            if edge in {"left", "right", "center_x"}:
                x = {"left": offset, "right": w-offset, "center_x": w/2+offset}[edge]
                coords = (x, top, x, bottom)
            else:
                y = {"top": offset, "bottom": h-offset, "center_y": h/2+offset}[edge]
                coords = (left, y, right, y)
            paper.append(svg_line(*coords, color, e["weightPt"]))
            continue
        xs = centered(left, right, e["spacingPt"])
        ys = centered(top, bottom, e["spacingPt"])
        if kind == "dots":
            for y in ys:
                for x in xs:
                    paper.append(f'<circle cx="{x}" cy="{y}" r="{e["radiusPt"]}" fill="{color}"/>')
            continue
        minor, heavy = [], []
        major = e.get("major")
        if kind == "grid":
            left, right, top, bottom = xs[0], xs[-1], ys[0], ys[-1]
        if kind in {"horizontal_lines", "grid"}:
            for i, y in enumerate(ys):
                coords = (left, y, right, y)
                (heavy if major and major["every"] and (i-len(ys)//2) % major["every"] == 0 else minor).append(coords)
        if kind in {"vertical_lines", "grid"}:
            for i, x in enumerate(xs):
                coords = (x, top, x, bottom)
                (heavy if major and major["every"] and (i-len(xs)//2) % major["every"] == 0 else minor).append(coords)
        paper.extend(svg_line(*coords, color, e["weightPt"]) for coords in minor)
        paper.extend(svg_line(*coords, major["color"], major["weightPt"]) for coords in heavy)
    return "".join(paper)


def save(name, w, h, fragments, *, store=False, scale=1):
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
           + "".join(fragments) + "</svg>")
    (OUT / f"{name}.svg").write_text(svg, encoding="utf-8")
    path = (ROOT / "docs/preview.png") if store else (OUT / f"{name}.png")
    path.parent.mkdir(exist_ok=True)
    with pymupdf.open(stream=svg.encode("utf-8"), filetype="svg") as image:
        page = image[0]
        page.get_pixmap(matrix=pymupdf.Matrix(scale*w/page.rect.width, scale*h/page.rect.height)).save(path)


def shape_tile(item, x, y, scale, strings, size):
    drawing = "".join(draw_object(obj) for obj in item["objects"])
    return (group(drawing, x-item["widthPt"]*scale/2, y-item["heightPt"]*scale/2, scale)
            + text(x, y+38*scale, strings[item["label"]], size, MUTED, center=True))


def shape_sheets(libraries, strings):
    columns, step_x, step_y = 5, 240, 170
    for library in libraries:
        items = library["items"]
        height = 104 + math.ceil(len(items)/columns)*step_y
        parts = [rect(0, 0, 1200, height, PAPER), text(40, 64, strings[library["label"]], 36, bold=True)]
        for index, item in enumerate(items):
            x, y = step_x*(index%columns + .5), 155+step_y*(index//columns)
            parts.append(shape_tile(item, x, y, 1.65, strings, 17))
        save(library["id"], 1200, height, parts)

    parts = [rect(0, 0, 1600, 1000, PAPER), text(120, 154, strings["name"], 77, bold=True),
             text(123, 221, "Circuit, logic, mechanics, flowchart and lab symbols", 32, MUTED)]
    selected = {"resistor", "transformer", "op-amp", "and", "xor", "roller-support",
                "distributed-load", "decision", "erlenmeyer", "bunsen-burner"}
    items = [item for library in libraries for item in library["items"] if item["id"] in selected]
    for i, item in enumerate(items):
        parts.append(shape_tile(item, 245+(i%5)*278, 417+(i//5)*325, 3.2, strings, 21))
    save("store", 1600, 1000, parts, store=True)


def paper_tile(template, x, y, scale):
    w, h = A4
    return (rect(x-1, y-1, w*scale+2, h*scale+2, "#c4ccd1")
            + group(draw_template(template), x, y, scale))


def study_sheets(templates, palettes, strings):
    width, height = 1400, 1400
    parts = [rect(0, 0, width, height, PAPER), text(35, 58, "A4 paper templates", 36, bold=True)]
    for index, item in enumerate(templates):
        template = item["template"]
        name = strings[item["label"]]
        slug = template["id"].split(".", 1)[1]
        save(slug, *A4, [draw_template(template)], scale=2)
        x, y = 85+(index%3)*445, 105+(index//3)*560
        parts.extend([paper_tile(template, x, y, .47), text(x, y+430, name, 22)])
    for i, palette in enumerate(palettes):
        x = 85+i*445
        parts.append(text(x, 1290, strings[palette["label"]], 19))
        parts.extend(rect(x+34*j, 1310, 28, 28, c) for j, c in enumerate(palette["colors"]))
    save("templates-and-palettes", width, height, parts)

    parts = [rect(0, 0, 1600, 1000, PAPER), text(96, 134, strings["name"], 76, bold=True),
             text(99, 192, "Six paper layouts and three pen palettes", 30, MUTED)]
    for i, item in enumerate(templates):
        x = 99+i*238
        parts.append(paper_tile(item["template"], x, 313, .34))
    for i, palette in enumerate(palettes):
        x = 99+i*490
        parts.append(text(x, 753, strings[palette["label"]], 23))
        parts.extend(rect(x+48*j, 781, 39, 39, c) for j, c in enumerate(palette["colors"]))
    save("store", 1600, 1000, parts, store=True)


def main():
    manifest, _ = validate(report=False)
    OUT.mkdir(parents=True, exist_ok=True)
    strings = manifest["strings"]["en"]
    kinds = manifest["contents"]
    if "shapes" in kinds:
        shape_sheets([load(ROOT / path) for path in kinds["shapes"]], strings)
    else:
        templates = [item for path in kinds["templates"] for item in load(ROOT / path)["templates"]]
        palettes = [item for path in kinds["palettes"] for item in load(ROOT / path)["palettes"]]
        study_sheets(templates, palettes, strings)
    print(f"Rendered previews in {OUT}")


if __name__ == "__main__":
    main()
