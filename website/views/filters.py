from sqlalchemy import exists

from models import MC3Mutation, Disease, source_manager, SiteType, PCAWGMutation
from models.bio.drug import DrugGroup, Drug
from models import Cancer
from models import Mutation
from models import Site
from models import The1000GenomesMutation
from models import ExomeSequencingMutation
from models import ClinicalData
from database import has_or_any, db
from helpers.filters import Filter
from helpers.widgets import FilterWidget


class FiltersData:
    """State transfer object AsyncFiltersHandler from filters.js"""

    def __init__(self, filter_manager):
        from flask import request
        self.query = filter_manager.url_string() or ''
        self.expanded_query = filter_manager.url_string(expanded=True) or ''
        self.checksum = request.args.get('checksum', '')
        self.dynamic_widgets = ''

    def to_json(self):
        return self.__dict__


class ProteinFiltersData(FiltersData):

    def __init__(self, filter_manager, protein):
        super().__init__(filter_manager)
        from flask import render_template
        self.dynamic_widgets = render_template(
            'widgets/widget_list.html',
            widgets=create_dataset_specific_widgets(protein, filter_manager.filters),
            collapse=True
        )


def populations_labels(populations):
    return [
        population_name + ' (' + field_name[4:].upper() + ')'
        for field_name, population_name
        in populations.items()
    ]


class SourceDependentFilter(Filter):

    def __init__(self, *args, **kwargs):
        self.source = kwargs.pop('source')
        super().__init__(*args, **kwargs)

    @property
    def visible(self):
        return self.manager.get_value('Mutation.sources') == self.source


class MutationDetailsFilter(SourceDependentFilter):
    """Mutation details restrict returned mutations to those
    which have at least on MutationDetails passing given criteria.

    Example mutation details attributes include:
        disease_name, cancer_type, population_name and so on

    As there may be hundreds of mutations per protein, to improve speed
    of filtering, the MutationDetails filters must be defined in a way
    which allows conversion to database-side SQL 'where' clauses.

    This means that 'as_sqlalchemy' will be set to True by default and
    it's strongly discouraged to turned it off; Still, one can overwrite
    as_sqlalchemy with a function defining custom sqlalchemy filter.

    Also the filters should be constructed in a way that the default
    value is equivalent to having the filter disabled. If it is not
    possible to achieve, one need to provide 'skip_if_default=False'
    """

    def __init__(
        self, target_details_class, attribute,
        nullable=False, as_sqlalchemy=True, skip_if_default=True,
        **kwargs
    ):
        target = [Mutation, target_details_class]
        super().__init__(
            target, attribute,
            nullable=nullable, as_sqlalchemy=as_sqlalchemy, skip_if_default=skip_if_default,
            **kwargs
        )


def sqlalchemy_filter_from_source_name(source_name):
    """Adapt mutation source filter to SQLAlchemy clause (for use in mutation query)"""
    if source_name == 'user':
        return True
    field_name = source_manager.visible_fields[source_name]
    field = getattr(Mutation, field_name)
    return has_or_any(field)


class UserMutations:
    pass


def create_dataset_labels():
    # map dataset display names to dataset names
    dataset_labels = {
        dataset.name: dataset.display_name
        for dataset in source_manager.all
    }
    # hide user's mutations in dataset choice
    # (there is separate widget for that, shown only if there are any user's datasets)
    dataset_labels['user'] = None
    return dataset_labels


class HashableDict(dict):
    def __hash__(self):
        return hash(tuple(self.items()))


class CachedQueries:

    def __init__(self):
        self.reload()

    def reload(self):
        """Should be called after each cancer and public-dataset addition or change
        (It should not happen during normal service, only after migrations and during tests)
        """
        self.drug_groups = sorted([group.name for group in DrugGroup.query])

        self.all_disease_names_by_id = HashableDict({
            disease.id: disease.name
            for disease in sorted(Disease.query, key=lambda disease: disease.name.lower())
        })
        self.all_cancer_codes_mc3 = [
            cancer.code for cancer in Cancer.query
            if db.session.query(exists().where(MC3Mutation.cancer == cancer)).scalar()
        ]
        self.all_cancer_codes_pcawg = [
            cancer.code for cancer in Cancer.query
            if db.session.query(exists().where(PCAWGMutation.cancer == cancer)).scalar()
        ]
        self.all_cancer_names = {
            cancer.code: f'{cancer.name} ({cancer.code})'
            for cancer in Cancer.query
        }
        self.dataset_labels = create_dataset_labels()

        self.site_types = SiteType.query.all()


cached_queries = CachedQueries()


def common_filters(
    protein,
    default_source='MC3',
    source_nullable=False,
    custom_datasets_ids=[]
):

    return [
        Filter(
            Mutation, 'sources', comparators=['in'],
            choices=list(source_manager.visible_fields.keys()),
            default=default_source, nullable=source_nullable,
            as_sqlalchemy=sqlalchemy_filter_from_source_name
        ),
        Filter(
            UserMutations, 'sources', comparators=['in'],
            choices=list(custom_datasets_ids),
            default=None, nullable=True
        ),
        Filter(
            Mutation, 'is_ptm', comparators=['eq']
        ),
        Filter(
            Drug, 'groups.name', comparators=['in'],
            nullable=False,
            choices=cached_queries.drug_groups,
            default=['approved'],
            multiple='all',
            as_sqlalchemy=True
        ),
        Filter(
            Site, 'types', comparators=['in'],
            choices={
                site_type.name: site_type
                for site_type in SiteType.available_types()
            },
            custom_comparators={'in': SiteType.fuzzy_comparator},
            as_sqlalchemy=SiteType.fuzzy_filter,
            as_sqlalchemy_joins=[Site.types]
        )
    ] + source_dependent_filters(protein)


def source_dependent_filters(protein=None):

    if protein:
        cancer_codes_mc3 = protein.cancer_codes(MC3Mutation)
        cancer_codes_pcawg = protein.cancer_codes(PCAWGMutation)
        disease_names_by_id = protein.disease_names_by_id
    else:
        cancer_codes_mc3 = cached_queries.all_cancer_codes_mc3
        cancer_codes_pcawg = cached_queries.all_cancer_codes_pcawg
        disease_names_by_id = cached_queries.all_disease_names_by_id

    # Python 3.4: cast keys() to list
    populations_1kg = list(The1000GenomesMutation.populations.values())
    populations_esp = list(ExomeSequencingMutation.populations.values())
    significances = list(ClinicalData.significance_codes.keys())

    default_significances = {'Pathogenic', 'Pathogenic/Likely pathogenic', 'Likely pathogenic'}
    default_significance_codes = [
        code
        for code, significance in ClinicalData.significance_codes.items()
        if significance in default_significances
    ]

    gold_starts = [*sorted(ClinicalData.stars_by_status.values(), reverse=True), -1]

    return [
        MutationDetailsFilter(
            MC3Mutation, 'mc3_cancer_code',
            comparators=['in'],
            choices=cached_queries.all_cancer_codes_mc3,
            default=cancer_codes_mc3,
            source='MC3',
            multiple='any',
        ),
        MutationDetailsFilter(
            PCAWGMutation, 'pcawg_cancer_code',
            comparators=['in'],
            choices=cached_queries.all_cancer_codes_pcawg,
            default=cancer_codes_pcawg,
            source='PCAWG',
            multiple='any',
        ),
        MutationDetailsFilter(
            The1000GenomesMutation, 'populations_1KG',
            comparators=['in'],
            choices=populations_1kg,
            default=populations_1kg,
            source='1KGenomes',
            multiple='any',
        ),
        MutationDetailsFilter(
            ExomeSequencingMutation, 'populations_ESP6500',
            comparators=['in'],
            choices=populations_esp,
            default=populations_esp,
            source='ESP6500',
            multiple='any'
        ),
        MutationDetailsFilter(
            ClinicalData, 'sig_code',
            comparators=['in'],
            choices=significances,
            default=default_significance_codes,
            source='ClinVar',
            skip_if_default=False,
            multiple='any',
        ),
        MutationDetailsFilter(
            ClinicalData, 'gold_stars',
            comparators=['in'],
            choices=gold_starts,
            default=gold_starts,
            source='ClinVar',
            multiple='any',
        ),
        # We use disease id by default (instead of disease name)
        # because the names often include some characters or
        # symbols which make escaping and encoding tricky and
        # might cause server to crash; also querying a lot of
        # diseases at a time caused the url queries to exceed
        # limits back then when the diseases where filtered by
        # names and not identifiers.
        MutationDetailsFilter(
            ClinicalData, 'disease_id',
            comparators=['in'],
            # casting to list() proved to be necessary
            # as we would otherwise get wrong result of
            # comparison: f.value != f.default
            # (due to types difference)
            choices=list(disease_names_by_id.keys()),
            default=list(disease_names_by_id.keys()),
            source='ClinVar',
            multiple='any',
        ),
        # Disease_name is not visible from the user interface,
        # but was added to provide backward compatibility with
        # 1.0 version of ActiveDriverDB and enable creation of
        # API queries knowing only the disease names (not our
        # internal, volatile disease identifiers)
        MutationDetailsFilter(
            ClinicalData, 'disease_name',
            comparators=['in'],
            # casting to list(): see note in disease_id
            choices=list(disease_names_by_id.values()),
            default=list(disease_names_by_id.values()),
            source='ClinVar',
            multiple='any',
        ),
    ]


def create_dataset_specific_widgets(protein, filters_by_id, population_widgets=True):
    if protein:
        cancer_codes_mc3 = protein.cancer_codes(MC3Mutation)
        cancer_codes_pcawg = protein.cancer_codes(PCAWGMutation)
        disease_names_by_id = protein.disease_names_by_id
    else:
        cancer_codes_mc3 = [] #cached_queries.all_cancer_codes_mc3
        cancer_codes_pcawg = []
        disease_names_by_id = cached_queries.all_disease_names_by_id

    widgets = [
        FilterWidget(
            'Cancer type', 'checkbox_multiple',
            filter=filters_by_id['Mutation.mc3_cancer_code'],
            labels=cached_queries.all_cancer_names,
            choices=cancer_codes_mc3,
            all_selected_label='Any cancer type'
        ),
        FilterWidget(
            'Cancer type', 'checkbox_multiple',
            filter=filters_by_id['Mutation.pcawg_cancer_code'],
            choices=cancer_codes_pcawg,
            all_selected_label='Any cancer type'
        ),
        FilterWidget(
            'Clinical significance', 'checkbox_multiple',
            filter=filters_by_id['Mutation.sig_code'],
            all_selected_label='Any clinical significance class',
            labels=ClinicalData.significance_codes.values(),
            # do not collapse this filter by default so that the user
            # # is aware that we only show a subset of mutations
            expanded=True
        ),
        FilterWidget(
            'Disease', 'checkbox_multiple',
            filter=filters_by_id['Mutation.disease_id'],
            all_selected_label='Any disease',
            labels=disease_names_by_id
        ),
        FilterWidget(
            'Gold stars', 'checkbox_multiple',
            filter=filters_by_id['Mutation.gold_stars'],
            all_selected_label='Any number of stars',
            labels=['4 stars', '3 stars', '2 stars', '1 star', '0 stars', 'unknown'],
        )
    ]
    if population_widgets:
        widgets += [
            FilterWidget(
                'Ethnicity', 'checkbox_multiple',
                filter=filters_by_id['Mutation.populations_1KG'],
                labels=populations_labels(The1000GenomesMutation.populations),
                all_selected_label='Any ethnicity'
            ),
            FilterWidget(
                'Ethnicity', 'checkbox_multiple',
                filter=filters_by_id['Mutation.populations_ESP6500'],
                labels=populations_labels(ExomeSequencingMutation.populations),
                all_selected_label='Any ethnicity'
            )
        ]
    return widgets


def create_widgets(protein, filters_by_id, custom_datasets_names=None):
    """Widgets to be displayed on a bar above visualisation."""

    return {
        'dataset': FilterWidget(
            'Mutation dataset', 'radio',
            filter=filters_by_id['Mutation.sources'],
            labels=cached_queries.dataset_labels,
            class_name='dataset-widget'
        ),
        'custom_dataset': FilterWidget(
            'Custom mutation dataset', 'radio',
            filter=filters_by_id['UserMutations.sources'],
            labels=custom_datasets_names
        ),
        'dataset_specific': create_dataset_specific_widgets(protein, filters_by_id),
        'is_ptm': FilterWidget(
            'PTM mutations only', 'checkbox',
            filter=filters_by_id['Mutation.is_ptm'],
            disabled_label='all mutations',
            labels=['PTM mutations only']
        ),
        'ptm_type': FilterWidget(
            'Type of PTM site', 'radio',
            filter=filters_by_id['Site.types'],
            disabled_label='Any site',
            hierarchy={
                site_type.name: [sub_type.name for sub_type in site_type.sub_types]
                for site_type in cached_queries.site_types
                if site_type.sub_types
            }
        ),
        'other': [FilterWidget(
            'Drug group', 'checkbox_multiple',
            filter=filters_by_id['Drug.groups.name'],
            labels=[group.title() for group in cached_queries.drug_groups],
        )]
    }
