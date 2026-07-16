#!/usr/bin/env python3
"""The adjudication CLI: one row, one keypress. Renders adjudicate.py's sheet.

A dumb renderer on purpose — it knows about sections, questions and rows, and
nothing about relations. What is being asked lives in the sheet, so a new section
is an adjudicate.py change and never a change here.

Every vote is written to disk as it is cast, so quitting is a pause, not a loss,
and a second run picks up where the first stopped. That is not a nicety: this is
the only step of STU-540 a human has to do, and the whole method dies if it is
long enough to abandon.

Order within a section is the sheet's, and the sheet is sorted by name — a row
never says which arm claimed the pair. See adjudicate.py for why, and for the one
case where blindness leaks.

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


def ask(header: str, body: list[str], question: str, hint: str, progress: str) -> str | None:
    """Returns 'o' | 'n' | 's' (skip), or None to stop."""
    while True:
        os.system("clear")
        print(f"\033[2m{progress}\033[0m\n")
        print(f"\033[1m{header}\033[0m\n")
        for block in body:
            print(textwrap.fill(block, WIDTH, initial_indent="  ", subsequent_indent="  "))
            print()
        print(question + (f"   \033[2m{hint}\033[0m" if hint else ""))
        print("\033[2m[o]ui  [n]on  [s]auter  [q]uitter\033[0m")
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
        sections = json.load(f)["sections"]

    votes = {s["id"]: {} for s in sections}
    if os.path.exists(args.votes) and not args.restart:
        with open(args.votes, encoding="utf-8") as f:
            for section, cast in json.load(f).items():
                votes.setdefault(section, {}).update(cast)

    def save() -> None:
        with open(args.votes, "w", encoding="utf-8") as f:
            json.dump(votes, f, ensure_ascii=False, indent=2)

    todo = [(s, row) for s in sections for row in s["rows"] if row["key"] not in votes[s["id"]]]
    total = sum(len(s["rows"]) for s in sections)
    done = total - len(todo)

    if not todo:
        print(f"{total}/{total} déjà voté.\n\n  python score_adjudication.py --votes {args.votes}")
        return

    for section, row in todo:
        done += 1
        answer = ask(row["key"], row["body"] or ["(aucun extrait)"], section["question"],
                     section.get("hint", ""), f"{done}/{total}  ({section['id']})")
        if answer is None:
            save()
            cast = sum(len(v) for v in votes.values())
            print(f"\n{cast}/{total} voté. `python vote.py` reprend ici.")
            return
        if answer != "s":
            votes[section["id"]][row["key"]] = answer
            save()

    save()
    os.system("clear")
    print(f"{total}/{total} voté.\n\n  python score_adjudication.py --votes {args.votes}")


if __name__ == "__main__":
    main()
