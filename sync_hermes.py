"""Brings the Hermes Agent code in hermes_memory\\ to the commit of a Hermes checkout. Never imported by Hey Jev.

    python sync_hermes.py <path to a hermes-agent checkout>            show what changed upstream, write nothing
    python sync_hermes.py <path to a hermes-agent checkout> --write    copy it over and record the new commit

hermes_memory\\UPSTREAM.json lists each file: copied whole with a few fixed import rewrites (so it stands alone, see
_compat.py), or named pieces picked out of one or more Hermes files. A rewrite that no longer matches stops it, so
an upstream change to those lines is looked at rather than copied blind. Run the tests after --write.
"""
import ast
import json
import os
import subprocess
import sys
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "hermes_memory")
HEADER = ("# From Hermes Agent by Nous Research, {src} at commit {sha}\n"
          "# https://github.com/NousResearch/hermes-agent, MIT License, see LICENSE in this folder.\n"
          "# Copied by sync_hermes.py; only the imports are changed, see UPSTREAM.json. Don't edit by hand.\n")


def rewrite(text, pairs, where):
    for old, new in pairs:
        if old not in text:
            raise SystemExit(f"{where}: {old!r} isn't there any more: look at the upstream change, then fix UPSTREAM.json")
        text = text.replace(old, new)
    return text


def pieces(source, names, where):
    """The source of each named top-level definition (or Class.method, dedented, decorators off), in that order."""
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    found = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            found[node.name] = node
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, ast.FunctionDef):
                        found[f"{node.name}.{sub.name}"] = sub
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for t in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                if isinstance(t, ast.Name):
                    found[t.id] = node
    out = []
    for name in names:
        if name not in found:
            raise SystemExit(f"{where}: {name} isn't there any more")
        node = found[name]
        start = node.lineno if not getattr(node, "decorator_list", None) else node.lineno  # def line, decorators off
        text = "".join(lines[start - 1:node.end_lineno])
        out.append(textwrap.dedent(text) if "." in name else text)
    return "\n\n".join(p.rstrip() + "\n" for p in out)


def build(spec, hermes, sha):
    if "from" in spec:
        with open(os.path.join(hermes, spec["from"]), encoding="utf-8") as f:
            text = f.read()
        return HEADER.format(src=spec["from"], sha=sha) + rewrite(text, spec.get("rewrite", []), spec["from"])
    parts = [HEADER.format(src=", ".join(e["from"] for e in spec["extract"]), sha=sha), '"""' + spec["doc"] + '"""\n',
             spec.get("imports", "") + "\n"]
    for e in spec["extract"]:
        with open(os.path.join(hermes, e["from"]), encoding="utf-8") as f:
            text = f.read()
        parts.append(f"\n# --- {e['from']} ---\n\n" + rewrite(pieces(text, e["names"], e["from"]), e.get("rewrite", []),
                                                             e["from"]))
    return "\n".join(parts)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    hermes, write = sys.argv[1], "--write" in sys.argv
    with open(os.path.join(TARGET, "UPSTREAM.json"), encoding="utf-8") as f:
        upstream = json.load(f)
    sha = subprocess.run(["git", "-C", hermes, "rev-parse", "HEAD"], capture_output=True, text=True,
                         check=True).stdout.strip()
    sources = sorted({s["from"] for s in upstream["files"] if "from" in s} |
                     {e["from"] for s in upstream["files"] for e in s.get("extract", [])})
    if sha != upstream["commit"]:
        diff = subprocess.run(["git", "-C", hermes, "diff", "--stat", upstream["commit"], sha, "--", *sources],
                              capture_output=True, text=True).stdout
        print(f"Upstream {upstream['commit'][:10]} -> {sha[:10]}, changes in the files Hey Jev takes:\n{diff or '  none'}")
    for spec in upstream["files"]:
        text = build(spec, hermes, sha)
        path = os.path.join(TARGET, spec["to"])
        old = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
        print(f"  {spec['to']}: {'same' if old == text else 'changed'}")
        if write and old != text:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
    if write:
        upstream["commit"] = sha
        with open(os.path.join(TARGET, "UPSTREAM.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(upstream, f, indent=1)
            f.write("\n")
        print("Written. Now run the tests: python -m unittest discover -s tests -t .")


if __name__ == "__main__":
    main()
