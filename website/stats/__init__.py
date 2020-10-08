from collections import defaultdict, Counter

from flask import current_app

from .plots import Plots
from .stats import Statistics
from .venn import VennDiagrams


def hypermutated_samples(path, sample_column: int, threshold=900):
    from helpers.parsers import iterate_tsv_gz_file

    samples_cnt = Counter()
    muts = defaultdict(set)
    total = 0

    for line in iterate_tsv_gz_file(path):
        total += 1
        muts[','.join([line[0], '%x' % int(line[1]), '%x' % int(line[2]), line[3], line[4]])].add(line[sample_column])

    for samples in muts.values():
        for sample in samples:
            samples_cnt[sample] += 1

    hypermutated = {}
    for sample, count in samples_cnt.most_common():
        if count > threshold:
            hypermutated[sample] = count
        else:
            break

    percent = sum(hypermutated.values()) / total * 100
    print(f'There are {len(hypermutated)} hypermutated samples.')
    print(f'Hypermutated samples represent {percent} percent of analysed mutations.')

    return hypermutated


store_classes = [Statistics, VennDiagrams, Plots]


if current_app.config['LOAD_STATS']:
    print('Loading statistics')
    STORES = {
        counter.__name__: counter().get_all()
        for counter in store_classes
    }
else:
    print('Skipping loading statistics')
    STORES = defaultdict(dict)
