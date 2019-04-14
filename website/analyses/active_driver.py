from datetime import datetime
from os import cpu_count
from tempfile import NamedTemporaryFile

import gc
from traceback import print_exc
from typing import Mapping, Union

from rpy2.rinterface import RRuntimeError
from rpy2.robjects import pandas2ri, r
from rpy2.robjects.packages import importr
from pandas import read_table, Series, DataFrame
from flask import current_app
from tqdm import tqdm
from gprofiler import GProfiler

from database import get_or_create, db
from exports.protein_data import sites_ac
from helpers.cache import cache_decorator, Cache
from imports import MutationImportManager
from models import Gene, GeneList, GeneListEntry, MC3Mutation, MutationSource, ClinicalData, InheritedMutation, Protein, Mutation

from ._paths import ANALYSES_OUTPUT_PATH


def load_active_driver(local_ad=True):
    if local_ad:
        r.source("ActiveDriver/R/ActiveDriver.R")
        # ActiveDriver is in the global namespace now
        return r
    else:
        return importr("ActiveDriver")


def get_date() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d_%H%-M%-S")


def export_and_load(exporter, *args, compression=None, **kwargs) -> DataFrame:
    with current_app.app_context():
        with NamedTemporaryFile() as file:
            exporter(*args, path=file.name, **kwargs)
            return read_table(file.name, compression=compression)


def series_from_preferred_isoforms(trait, subset=None) -> Series:

    sequences = []
    names = []
    for gene in tqdm(Gene.query.all()):
        if not gene.preferred_isoform:
            continue
        sequence = getattr(gene.preferred_isoform, trait)
        sequences.append(sequence)
        names.append(gene.name)

    series = Series(sequences, names)

    if subset is not None:
        series = series[series.index.isin(subset)]

    return series


manager = MutationImportManager()
cache = Cache('active_driver_data')
cache.reset('cull_limit', 0)
cached = cache_decorator(cache)


@cached
def prepare_active_driver_data(mutation_source: str, site_type=None, mutation_query=None, sites=None):
    if sites is None:
        sites = export_and_load(sites_ac)

    if site_type:
        sites = sites[sites['type'].str.contains(site_type)]

    genes_with_sites = sites.gene
    gc.collect()

    importer_class = manager.importers[mutation_source]
    importer = importer_class()
    mutations = importer.export_to_df(only_preferred=True)
    mutations = mutations[mutations.gene.isin(genes_with_sites)]

    if mutation_query:
        mutations = mutations.query(mutation_query)

    gc.collect()

    sequences = series_from_preferred_isoforms('sequence', subset=genes_with_sites)
    sequences = sequences.str.rstrip('*')

    disorder = series_from_preferred_isoforms('disorder_map', subset=genes_with_sites)
    gc.collect()

    return sequences, disorder, mutations, sites


def run_active_driver(sequences, disorder, mutations, sites, mc_cores=None, progress_bar=True, **kwargs):

    if not mc_cores:
        mc_cores = cpu_count()

    arguments = [
        pandas2ri.py2ri(python_object)
        for python_object in [sequences, disorder, mutations, sites]
    ]

    active_driver = load_active_driver()

    # uncomment to debug a stalled run
    # r('debug(ActiveDriver)')

    try:
        result = active_driver.ActiveDriver(
            *arguments, mc_cores=mc_cores, progress_bar=progress_bar, **kwargs
        )
        if result:
            return {k: pandas2ri.ri2py(v) for k, v in result.items()}
    except RRuntimeError as e:
        print_exc()
        return e


def profile_genes_with_active_sites(enriched_genes, background=None) -> DataFrame:

    if len(enriched_genes) == 0:
        return DataFrame()

    gp = GProfiler('ActiveDriverDB', want_header=True)

    response = gp.gprofile(enriched_genes, custom_bg=background)

    if not response:
        return DataFrame()

    header, *rows = response

    return DataFrame(rows, columns=header)


ActiveDriverResult = Mapping[str, Union[DataFrame, 'ActiveDriverResult']]


def process_result(result, sites, fdr_cutoff=0.05) -> ActiveDriverResult:

    if not result:
        return {}

    all_genes = sites.gene.unique()

    enriched = result['all_gene_based_fdr']
    enriched = enriched[enriched.fdr < fdr_cutoff]
    enriched = enriched.sort_values('fdr')

    enriched_genes = enriched.gene.unique()

    result['profile'] = profile_genes_with_active_sites(enriched_genes)
    result['profile_against_genes_with_sites'] = profile_genes_with_active_sites(enriched_genes, all_genes)
    result['top_fdr'] = enriched.reset_index(drop=True)

    return result


def save_all(analysis_name: str, data, base_path=None):
    if base_path:
        path = base_path / analysis_name
    else:
        base_path = ANALYSES_OUTPUT_PATH
        path = base_path / analysis_name / get_date()

    # create what's needed
    path.mkdir(parents=True, exist_ok=True)

    for name, datum in data.items():

        # deal with the nested case
        if isinstance(datum, dict):
            save_all(name, datum, base_path=path)
            continue

        # save to tsv file
        datum.to_csv(path / f'{name}.tsv', sep='\t')


def create_gene_list(name: str, list_data: DataFrame, mutation_source: MutationSource=None) -> GeneList:
    gene_list, created = get_or_create(GeneList, name=name)

    if not created:
        for old_entry in gene_list.entries:
            db.session.delete(old_entry)

    print(('Creating' if created else 'Updating') + f' gene list: {name}')

    if mutation_source:
        gene_list.mutation_source_name = mutation_source.name

    entries = []

    for raw_entry in list_data.itertuples(index=False):

        gene, created = get_or_create(Gene, name=raw_entry.gene)
        entry = GeneListEntry(
            gene=gene,
            fdr=raw_entry.fdr,
            p=raw_entry.p
        )
        entries.append(entry)

    gene_list.entries = entries

    db.session.commit()

    return gene_list


@cached
def per_cancer_analysis(site_type: str):

    sequences, disorder, all_mutations, sites = prepare_active_driver_data('mc3', site_type)

    results = {}

    for cancer_type in all_mutations.cancer_type.unique():
        mutations = all_mutations[all_mutations.cancer_type == cancer_type]
        result = run_active_driver(sequences, disorder, mutations, sites)
        result = process_result(result, sites)
        results[cancer_type] = result
        create_gene_list(f'ActiveDriver: {cancer_type} in {site_type} sites', result['top_fdr'], MC3Mutation)

    save_all(f'per_cancer-{site_type}', results)

    return results


def source_specific_analysis(mutations_source, site_type=None, mutation_query=None):

    sequences, disorder, mutations, sites = prepare_active_driver_data(mutations_source, site_type, mutation_query)
    result = run_active_driver(sequences, disorder, mutations, sites, mc_cores=1)
    result = process_result(result, sites)
    source = manager.importers[mutations_source].model
    create_gene_list(f'ActiveDriver: {source.name} {site_type} sites', result['top_fdr'], source)

    save_all(f'{mutations_source}-{site_type}', result)

    return result


@cached
def pan_cancer_analysis(site_type: str):
    return source_specific_analysis('mc3', site_type)


@cached
def clinvar_analysis(site_type: str, mode='strict'):
    significances = ClinicalData.significance_subsets[mode]
    return source_specific_analysis('clinvar', site_type, mutation_query=f'significance in {significances}')


def mutations_from_significant_genes(result: ActiveDriverResult, mutation_model=MC3Mutation, cancer_type=None, keep_model=False):

    details_filters = {
        MC3Mutation: lambda mutation: MC3Mutation.cancer_code == mutation.cancer_type,
        InheritedMutation: lambda mutation: (
            InheritedMutation.clin_data.any(
                ClinicalData.disease_name == mutation.disease
            )
        )
    }

    mutations = result['all_active_mutations']
    mutations = mutations.merge(result['top_fdr'], on='gene')
    int_columns = ['count', 'position', 'active_region']
    mutations[int_columns] = mutations[int_columns].astype(int)

    if cancer_type:
        mutations = mutations[mutations.cancer_type == cancer_type]

    details_filter = details_filters[mutation_model]

    mutations = mutations.assign(mutation=Series(
        mutation_model.query.filter_by(
            mutation=Mutation.query.filter_by(
                protein=Protein.query.filter_by(refseq=mutation.isoform).one(),
                position=mutation.position,
                alt=mutation.mut_residue
            ).one()
        ).filter(details_filter(mutation))
        .one()
        for mutation in mutations.itertuples(index=False)
    ).values)

    if mutation_model is MC3Mutation:
        mutations = mutations.assign(
            barcodes=mutations.mutation.apply(
                lambda mut: mut.samples
            )
        )

    if not keep_model:
        mutations = mutations.drop(['mutation'], axis=1)

    return mutations
