"""Legacy ranking arithmetic over bulk ordered rows."""

from collections import Counter, defaultdict


def calculate_ranks(track_ids, eligible, ordered_records, maxrecs):
    total = len(track_ids)
    if not total:
        return []
    sums = {int(pid): [0, 0] for pid in eligible}
    occurrences = Counter(track_ids)
    counts = defaultdict(int)
    for track, player in ordered_records:
        counts[track] += 1
        rank = counts[track]
        if rank > maxrecs or player not in sums:
            continue
        multiple = occurrences[track]
        sums[player][0] += rank * multiple
        sums[player][1] += multiple
    return [(pid, round((score + (total - count) * maxrecs) / total * 10000))
            for pid, (score, count) in sums.items()]
