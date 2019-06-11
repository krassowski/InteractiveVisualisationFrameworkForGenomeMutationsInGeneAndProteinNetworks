from itertools import chain
from typing import Tuple

from pandas import DataFrame
from sqlalchemy import and_
from sqlalchemy.orm import aliased

from models import SiteType, Site, Protein, Mutation, source_manager, InheritedMutation, db


def site_type_filter_from_str(query, site=Site):
    if query == 'any':
        return

    if query.startswith('not'):
        query = query[4:]
        negate = True
    else:
        negate = False

    site_type = SiteType.query.filter_by(name=query).one()
    site_filter = SiteType.fuzzy_filter(site_type, join=True, site=site)

    if negate:
        site_filter = ~site_filter
    return site_filter


def ptm_sites_proximity(type_1: str, type_2: str, distance: int = 7, only_preferred=True) -> int:
    site_1 = Site
    site_2 = aliased(Site)

    site_and_type = [(site_1, type_1), (site_2, type_2)]

    sites = site_1.query.join(
        site_2,
        and_(
            site_1.position.between(
                site_2.position - distance,
                site_2.position + distance
            ),
            site_1.protein_id == site_2.protein_id
        )
    )

    for site, type_name in site_and_type:
        site_filter = site_type_filter_from_str(type_name, site=site)
        if not site_filter:
            continue
        sites = sites.filter(site_filter)

    if only_preferred:
        # no need to repeat as we already joined on protein_id
        sites = sites.join(Site.protein).filter(Protein.is_preferred_isoform)

    return sites.count()


def ptm_muts_around_other_ptm_sites(
    source: str, mutation_ptm: str, other_type: str, only_preferred=True, mutation_filter=None,
    distance=7
) -> Tuple[int, int]:
    source = source_manager.source_by_name[source]
    other_site = aliased(Site)

    if mutation_filter is None:
        mutation_filter = True

    mut_ptm_filter = site_type_filter_from_str(mutation_ptm)
    query = (
        source.query
        .join(Mutation)
        .filter(mutation_filter)
        .join(Mutation.affected_sites).filter(mut_ptm_filter)
        .join(
            other_site,
            and_(
                Mutation.position.between(
                    other_site.position - distance,
                    other_site.position + distance
                ),
                Mutation.protein_id == other_site.protein_id
            )
        )
    )
    type_filter = site_type_filter_from_str(other_type, site=other_site)

    if type_filter is not None:
        query = query.filter(type_filter)

    if only_preferred:
        query = query.join(Site.protein).filter(Protein.is_preferred_isoform)

    distinct_mutations = query.count()
    if hasattr(source, 'count'):
        mutation_occurrences = sum(m.count for m in query)
    else:
        # average frequency
        mutation_occurrences = sum(m.maf_all for m in query) / distinct_mutations
    return mutation_occurrences, distinct_mutations


def glycosylation_muts(only_preferred=True):
    results = {}
    site_type_names = [name for (name, ) in db.session.query(SiteType.name)]
    cases = [
        ('MC3', None),
        ('ClinVar', InheritedMutation.significance_filter('strict')),
        ('ESP6500', None),
        ('1KGenomes', None),
    ]
    for source, additional_filter in cases:
        result = {}
        for type_query in chain(site_type_names, ['not glycosylation']):
            occurrences, distinct = ptm_muts_around_other_ptm_sites(
                source, 'glycosylation', type_query,
                only_preferred=only_preferred,
                mutation_filter=additional_filter
            )
            result[type_query] = occurrences
        results[source] = result
    df = DataFrame(data=results).transpose()
    print(df)
    return df


def ptm_sites_in_proximity(type_1: str, type_2: str, distance: int = 7, only_preferred=True):
    site_1 = Site
    site_2 = aliased(Site)

    site_and_type = [(site_1, type_1), (site_2, type_2)]

    sites = site_1.query.join(
        site_2,
        and_(
            site_1.position.between(
                site_2.position - distance,
                site_2.position + distance
            ),
            site_1.protein_id == site_2.protein_id
        )
    )

    for site, type_name in site_and_type:
        site_filter = site_type_filter_from_str(type_name, site=site)
        if site_filter is None:
            continue
        sites = sites.filter(site_filter)

    if only_preferred:
        # no need to repeat as we already joined on protein_id
        sites = sites.join(Site.protein).filter(Protein.is_preferred_isoform)

    return sites, [site_1, site_2]


def count_ptm_sites_in_proximity(*args, **kwargs):
    sites, _ = ptm_sites_in_proximity(*args, **kwargs)
    return sites.count()


def mutated_ptm_sites_in_proximity(mutation_source, type_1: str, type_2: str, mutation_filter=True, distance: int = 7, only_preferred=True):
    sites, (site_1, site_2) = ptm_sites_in_proximity(type_1, type_2, distance, only_preferred)
    for site in (site_1, site_2):
        sites = sites.filter(
            site.affected_by_mutations.any(
                and_(
                    Mutation.in_sources(mutation_source),
                    mutation_filter
                )
            )
        )
    return sites


def mutated_sites_overlap(site_type_name, cases, only_preferred=True, additional_types={'not glycosylation'}):
    results = {}
    site_type_names = [name for (name, ) in db.session.query(SiteType.name)]
    for source, additional_filter in cases:
        result = {}
        for type_query in chain(site_type_names, additional_types):
            sites = mutated_ptm_sites_in_proximity(
                source, site_type_name, type_query,
                only_preferred=only_preferred,
                mutation_filter=additional_filter
            )
            sites_count = sites.count()
            result[type_query] = sites_count
        results[source.name] = result
    df = DataFrame(data=results).transpose()
    return df


def total_mutated_sites_overlap(site_type_name, cases, other_type_names, only_preferred=True):
    all_sites = set()
    for source, additional_filter in cases:
        for type_query in other_type_names:
            sites = mutated_ptm_sites_in_proximity(
                source, site_type_name, type_query,
                only_preferred=only_preferred,
                mutation_filter=additional_filter
            )
            all_sites.update(sites)
    return all_sites
