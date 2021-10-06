import collections
import csv
import datetime
import itertools
import json
import os
import pathlib
import re
import statistics
import sys

here = pathlib.Path(__file__).parent.resolve()
root = here.parent.parent
sys.path.append(str(root))

if not hasattr(datetime.datetime, "fromisoformat"):
    print("ERROR: datetime.fromisoformat missing")
    print("Install 'fromisoformat' backport package or use a Python version >= 3.7")
    exit(1)

print("1. Did errors occur?")
print("--------------------")
err_pattern = re.compile(r"(:1\]|warn|error)", re.I)
with open("klangbecken.log") as log_file:
    errors = [line.rstrip() for line in log_file if re.search(err_pattern, line)]
if errors:
    print("❌ Errors:")
    for error in errors:
        print(error)
else:
    print("✅ No")
print()

print("2. State of the data directory still good?")
print("------------------------------------------")

from klangbecken.cli import fsck_cmd  # noqa: E402

try:
    fsck_cmd("data")
except SystemExit as e:
    if e.code == 0:
        print("✅ Yes")
    else:
        print("❌ Error ocurred")
print()

print("3. Did all played tracks get logged?")
print("------------------------------------")
with open("klangbecken.log") as log_file:
    played = sum(1 for line in log_file if "INFO: Playing:" in line)

log_entries = []
for f in os.listdir("data/log"):
    log_entries.extend(csv.DictReader(open(os.path.join("data/log", f))))

logged = len(log_entries)

if logged == played:
    print("✅ Yes")
else:
    print(
        f"❌ Error: Number of played tracks ({played}) is different from the "
        f"number of logged tracks ({logged})"
    )
print()


print("4. Ratio music vs. classics")
print("---------------------------")
music = sum(1 for entry in log_entries if entry["playlist"] == "music")
classics = sum(1 for entry in log_entries if entry["playlist"] == "classics")
ratio = music / classics

if abs(ratio - 5) > 0.1:
    print(f"❌ Music vs. classics ration is off: {ratio:.2f} to 1")
else:
    print(f"✅ Good: {ratio:.2f} to 1")
print()

print("5. Music play distribution")
print("--------------------------")
with open("data/index.json") as index_file:
    index_entries = json.load(index_file)

music_plays = [
    entry["play_count"]
    for entry in index_entries.values()
    if entry["playlist"] == "music"
]
avg = statistics.mean(music_plays)
stdev = statistics.pstdev(music_plays, avg)
deciles = statistics.quantiles(music_plays, n=10)
normal_dist = statistics.NormalDist(avg, stdev)
differences = [
    measured - expected
    for measured, expected in zip(deciles, normal_dist.quantiles(n=10))
]

if all(abs(diff) <= 1 for diff in differences):
    print(f"✅ Normal distribution: {avg:.2f}±{stdev:.2f}")
elif all(abs(diff) <= 3 for diff in differences):
    print(f"🔶 Almost normal distribution: {avg:.2f}±{stdev:.2f}")
    for i, diff in enumerate(differences):
        if diff > 1:
            print(
                f" - {i + 1}. decile: {diff:.2f} off (measured {deciles[i]:.2f}, "
                f"expected {deciles[i] - diff:.2f})"
            )
else:
    print("❌ Not normally distributed")
print()

print("6. Classics play distribution")
print("-----------------------------")
classics_plays = [
    entry["play_count"]
    for entry in index_entries.values()
    if entry["playlist"] == "classics"
]
avg = statistics.mean(classics_plays)
stdev = statistics.pstdev(classics_plays, avg)
deciles = statistics.quantiles(classics_plays, n=10)
normal_dist = statistics.NormalDist(avg, stdev)
differences = [
    measured - expected
    for measured, expected in zip(deciles, normal_dist.quantiles(n=10))
]

if all(abs(diff) <= 1 for diff in differences):
    print(f"✅ Normal distribution: {avg:.2f}±{stdev:.2f}")
elif all(abs(diff) <= 3 for diff in differences):
    print(f"🔶 Almost normal distribution: {avg:.2f}±{stdev:.2f}")
    for i, diff in enumerate(differences):
        if diff > 1:
            print(
                f" - {i + 1}. decile: {diff:.2f} off (measured {deciles[i]:.2f}, "
                f"expected {deciles[i] - diff:.2f})"
            )
else:
    print("❌ Not normally distributed")
print()

print("6. Weighted jingle play distribution")
print("------------------------------------")
jingles_plays = [
    entry["play_count"] / entry["weight"]
    for entry in index_entries.values()
    if entry["playlist"] == "jingles" and entry["weight"] != 0
]
avg = statistics.mean(jingles_plays)
stdev = statistics.pstdev(jingles_plays, avg)
deciles = statistics.quantiles(jingles_plays, n=10)
normal_dist = statistics.NormalDist(avg, stdev)
differences = [
    measured - expected
    for measured, expected in zip(deciles, normal_dist.quantiles(n=10))
]
if all(abs(diff) <= stdev / 2 for diff in differences):
    print(f"✅ Normal distribution: {avg:.2f}±{stdev:.2f}")
elif all(abs(diff) <= stdev for diff in differences):
    print(f"🔶 Almost normal distribution: {avg:.2f}±{stdev:.2f}")
    for i, diff in enumerate(differences):
        if diff > stdev / 2:
            print(
                f" - {i + 1}. decile: {diff:.2f} off (measured {deciles[i]:.2f}, "
                f"expected {deciles[i] - diff:.2f})"
            )
else:
    print("❌ Not normally distributed")
print()

print("7. Disabled jingles not played?")
print("-------------------------------")
disabled_plays = sum(
    entry["play_count"]
    for entry in index_entries.values()
    if entry["playlist"] == "jingles" and entry["weight"] == 0
)
if disabled_plays == 0:
    print("✅ Yes")
else:
    print(f"❌ {disabled_plays} plays of disabled tracks")
print()

print("8. Jingle weights respected?")
print("----------------------------")
prioritized_jingles = [
    entry
    for entry in index_entries.values()
    if entry["playlist"] == "jingles" and entry["weight"] > 1
]
by_weight = sorted(prioritized_jingles, key=lambda x: x["weight"])
by_plays = sorted(prioritized_jingles, key=lambda x: x["play_count"])
if by_weight == by_plays:
    print("✅ Yes")
else:
    print("❌ No")
print()

print("9. Are Jingles played regularly?")
print("--------------------------------")
spacings = []
spacing = 0
jingle_plays = 0
for entry in log_entries:
    if entry["playlist"] == "jingles":
        spacings.append(spacing)
        spacing = 0
        jingle_plays += 1
    else:
        spacing += 1
counter = collections.Counter(spacings)
almost_all = counter.most_common()[:-2]
almost_all_min = min(spacing for spacing, _ in almost_all)
almost_all_max = max(spacing for spacing, _ in almost_all)
almost_all_count = sum(count for _, count in almost_all)
most_common_min = min(spacing for spacing, _ in counter.most_common(3))
most_common_max = max(spacing for spacing, _ in counter.most_common(3))
most_common_count = sum(count for _, count in counter.most_common(3))
if (
    almost_all_min > 1
    and almost_all_max < 10
    and almost_all_count / jingle_plays > 0.99
    and most_common_min > 2
    and most_common_max < 7
    and most_common_count / jingle_plays > 0.8
):
    print("✅ Yes")
else:
    print("❌ No")
print()

print("10. Waiting time between track plays respected?")
print("-----------------------------------------------")

ids = index_entries.keys()

music = [
    (entry["id"], entry["last_play"])
    for entry in log_entries
    if entry["playlist"] in ("music", "classics")
]
music_plays = {
    id: [
        datetime.datetime.fromisoformat(last_play)
        for id_, last_play in music
        if id_ == id
    ]
    for id in ids
}
music_diffs = [
    [(l2 - l1).total_seconds() for l1, l2 in zip(lst, lst[1:])]
    for id, lst in music_plays.items()
]
music_too_short = [[v for v in lst if v < 1728] for lst in music_diffs if lst]
music_too_short = list(itertools.chain(*music_too_short))

jingles = [
    (entry["id"], entry["last_play"])
    for entry in log_entries
    if entry["playlist"] == "jingles"
]
jingles_plays = {
    id: [
        datetime.datetime.fromisoformat(last_play)
        for id_, last_play in jingles
        if id_ == id
    ]
    for id in ids
}
jingles_diffs = [
    [(l2 - l1).total_seconds() for l1, l2 in zip(lst, lst[1:])]
    for id, lst in jingles_plays.items()
]
jingles_too_short = [[v for v in lst if v < 36] for lst in jingles_diffs if lst]
jingles_too_short = list(itertools.chain(*jingles_too_short))

too_short = len(music_too_short) + len(jingles_too_short)
percentage = too_short / logged * 100

if too_short == 0:
    print("✅ Waiting period always met")
elif percentage < 0.5:
    print(
        "✅ Waiting period almost always met: {too_short} missed out of {logged} "
        f"({percentage:.2f}%)"
    )
elif percentage < 2:
    print(
        f"🔶 Waiting period mostly met: {too_short} missed out of {logged} "
        f"({percentage:.2f}%)"
    )
else:
    print(
        f"❌ Waiting period not met: {too_short} missed out of {logged} "
        f"({percentage:.2f}%)"
    )
print()
