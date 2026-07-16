#!/usr/bin/env python3
"""The adjudication CLI: one row, one keypress. Reads adjudicate.py's sheet.

Every vote is written to disk as it is cast, so quitting is a pause, not a loss,
and a second run picks up where the first stopped. That is not a nicety: this is
the only step of STU-540 a human has to do, and the whole method dies if it is
long enough to abandon.

Order is the sheet's, and the sheet is sorted by name — a row never says which
arm claimed the pair. See adjudicate.py for why, and for the one case where
blindness leaks.

Usage:
    python vote.py                 # resumes
    python vote.py --restart       # discards existing votes
"""
import argparse
import json
import os
import sys
import termios
import textwrap
import tty

WIDTH = 88


def getch() -> str:
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def ask(header: str, body: list[str], question: str, progress: str) -> str | None:
    """Returns 'o' | 'n' | 's' (skip), or None to stop."""
    while True:
        os.system("clear")
        print(f"\033[2m{progress}\033[0m\n")
        print(f"\033[1m{header}\033[0m\n")
        for block in body:
            print(textwrap.fill(block, WIDTH, initial_indent="  ", subsequent_indent="  "))
            print()
        print(f"{question}   \033[2m[o]ui  [n]on  [s]auter  [q]uitter\033[0m")
        key = getch().lower()
        if key in ("o", "n", "s"):
            return key
        if key in ("q", "\x03"):  # ctrl-c is a quit here, not a traceback
            return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", default="adjudication.json")
    ap.add_argument("--votes", default="votes.json")
    ap.add_argument("--restart", action="store_true")
    args = ap.parse_args()

    with open(args.sheet, encoding="utf-8") as f:
        sheet = json.load(f)

    votes = {"detection": {}, "typing": {}}
    if os.path.exists(args.votes) and not args.restart:
        with open(args.votes, encoding="utf-8") as f:
            votes.update(json.load(f))

    def save() -> None:
        with open(args.votes, "w", encoding="utf-8") as f:
            json.dump(votes, f, ensure_ascii=False, indent=2)

    todo = [("detection", r) for r in sheet["detection"] if r["key"] not in votes["detection"]]
    todo += [("typing", r) for r in sheet["typing"] if r["key"] not in votes["typing"]]
    done = len(votes["detection"]) + len(votes["typing"])
    total = len(sheet["detection"]) + len(sheet["typing"])

    if not todo:
        print(f"{total}/{total} déjà voté. python score_adjudication.py --votes {args.votes}")
        return

    for section, row in todo:
        done += 1
        if section == "detection":
            body = row["windows"] or [
                "Les deux noms ne partagent jamais une fenêtre de 5 phrases dans le livre."
            ]
            question = "Le livre montre-t-il une VRAIE RELATION entre ces deux-là ?"
        else:
            a = row["key"].split(" | ")[0]
            body = [f"type : {row['relationship_type']}    direction : {row['direction']}  (A = {a})"]
            body += [f"« {e} »" for e in row["evidence"]]
            question = "Le type et la direction sont-ils justes ?"

        answer = ask(row["key"], body, question, f"{done}/{total}  ({section})")
        if answer is None:
            save()
            cast = len(votes["detection"]) + len(votes["typing"])
            print(f"\n{cast}/{total} voté. `python vote.py` reprend ici.")
            return
        if answer != "s":
            votes[section][row["key"]] = answer
            save()

    save()
    os.system("clear")
    print(f"{total}/{total} voté.\n\n  python score_adjudication.py --votes {args.votes}")


if __name__ == "__main__":
    main()
