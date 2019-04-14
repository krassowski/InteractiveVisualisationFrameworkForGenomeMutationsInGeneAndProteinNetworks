from itertools import chain
from warnings import warn

import flask
from flask import request, flash
from flask_classful import FlaskView
from flask_login import current_user
from sqlalchemy import and_

from helpers.filters.manager import FilterManager
from models import Protein, Mutation, UsersMutationsDataset


class GracefulFilterManager(FilterManager):

    def update_from_request(self, request, **kwargs):
        if kwargs:
            warn(
                UserWarning('GracefulFilterManager does not support raise_on_forbidden adjustment')
             )
        # sometimes user comes with a disease which is not associated
        # with any of mutations in given protein. We do not want to
        # raise ValidationError for the user, but rather just skip
        # the faulty filter value and let the user know of that.

        # Example:
        # /protein/show/NM_001042351?filters=Mutation.disease_name:in:%27Cataract,%20nuclear%20total%27,G6PD%20SPLIT;Mutation.sources:in:ClinVar
        skipped_filters, rejected_values_by_filters = super().update_from_request(request, raise_on_forbidden=False)

        for filter_id, rejected_values in rejected_values_by_filters.items():
            filtered_property = filter_id.split('.')[-1].replace('_', ' ')

            plural = len(rejected_values) > 1

            and_more = ''

            if len(rejected_values) > 15:
                and_more = f'and {len(rejected_values) - 10} more '
                rejected_values = rejected_values[:5] + ['...'] + rejected_values[-5:]

            message = (
                f'<i>{", ".join(map(str, rejected_values))}</i> {and_more}'
                f'{"do" if plural else "does"} not occur in <i>{filtered_property}</i> '
                f'for this protein and therefore {"they were" if plural else "it was"} left out.'
            )

            flash(message, category='warning')


class AbstractProteinView(FlaskView):

    filter_class = None

    def before_request(self, name, *args, **kwargs):
        user_datasets = current_user.datasets_names_by_uri()
        refseq = kwargs.get('refseq', None)
        protein = (
            Protein.query.filter_by(refseq=refseq).first_or_404()
            if refseq else
            None
        )

        filter_manager = self.filter_class(
            protein,
            custom_datasets_ids=user_datasets.keys()
        )

        flask.g.filter_manager = filter_manager

        endpoint = self.build_route_name(name)

        return filter_manager.reformat_request_url(
            request, endpoint, *args, **kwargs
        )

    @property
    def filter_manager(self):
        return flask.g.filter_manager

    def get_protein_and_manager(self, refseq, **kwargs):
        protein = Protein.query.filter_by(refseq=refseq).first_or_404()

        if kwargs:
            user_datasets = current_user.datasets_names_by_uri()
            filter_manager = self.filter_class(
                protein,
                custom_datasets_ids=user_datasets.keys(),
                **kwargs
            )
        else:
            filter_manager = self.filter_manager

        return protein, filter_manager


def get_raw_mutations(protein, filter_manager, count=False):

    custom_dataset = filter_manager.get_value('UserMutations.sources')

    mutation_filters = [Mutation.protein == protein]

    if custom_dataset:
        dataset = UsersMutationsDataset.query.filter_by(
            uri=custom_dataset
        ).one()

        filter_manager.filters['Mutation.sources']._value = 'user'

        mutation_filters.append(
            Mutation.id.in_([m.id for m in dataset.mutations])
        )

    getter = filter_manager.query_count if count else filter_manager.query_all

    raw_mutations = getter(
        Mutation,
        lambda q: and_(q, and_(*mutation_filters))
    )

    return raw_mutations


class ProteinRepresentation:

    def __init__(self, protein, filter_manager, include_kinases_from_groups=False):
        self.protein = protein
        self.filter_manager = filter_manager
        self.include_kinases_from_groups = include_kinases_from_groups
        self.protein_mutations = get_raw_mutations(protein, filter_manager)
        self.json_data = None

    def get_sites_and_kinases(self, only_sites_with_kinases=True):
        from models import Site
        from sqlalchemy import and_
        from sqlalchemy import or_

        additional_criteria = []

        if only_sites_with_kinases:
            additional_criteria.append(
                or_(
                    Site.kinases.any(),
                    Site.kinase_groups.any()
                )
            )

        sites = [
            site
            for site in self.filter_manager.query_all(
                Site,
                lambda q: and_(
                    q,
                    Site.protein == self.protein,
                    *additional_criteria
                )
            )
        ]

        kinases = set(
            kinase
            for site in sites
            for kinase in chain(
                site.kinases,
                site.kinase_groups if self.include_kinases_from_groups else []
            )
        )

        groups = set()

        for site in sites:
            groups.update(site.kinase_groups)

        return sites, kinases, groups

    def as_json(self):
        return self.json_data
