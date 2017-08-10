from collections import namedtuple, defaultdict

from flask import request, abort, Response, json
from flask import redirect
from flask import url_for
from flask import jsonify
from flask import render_template as template
from flask_login import current_user

from models import Protein, Mutation, Drug, Gene
from helpers.filters import Filter
from helpers.filters import FilterManager
from helpers.widgets import FilterWidget
from views.abstract_protein import AbstractProteinView, get_raw_mutations
from ._global_filters import common_filters, filters_data_view
from ._global_filters import create_widgets


class Target:
    __name__ = 'JavaScript'


def js_toggle(name, default=True):
    return Filter(
        Target(), name,
        comparators=['eq'], default=default
    )


class NetworkViewFilters(FilterManager):

    def __init__(self, protein, **kwargs):

        filters = common_filters(protein, **kwargs)

        # TODO: use filter manager only for true filters, make an "option manager" for options?
        filters += [
            js_toggle('show_sites'),
            js_toggle('clone_by_site'),
            js_toggle('collide_drugs'),
        ]

        super().__init__(filters)
        self.update_from_request(request)


def divide_muts_by_sites(mutations, sites):
    from collections import defaultdict
    muts_by_site = defaultdict(list)

    if not (sites and mutations):
        return muts_by_site

    sites.sort(key=lambda site: site.position)
    mutations.sort(key=lambda mutation: mutation.position)

    m = 0
    for site in sites:
        l = site.position - 7
        p = site.position + 7
        while mutations[m].position < l:
            m += 1
            if m == len(mutations):
                return muts_by_site
        ms = m
        while mutations[ms].position <= p:
            muts_by_site[site].append(mutations[ms])
            ms += 1
            if ms == len(mutations):
                break
    return muts_by_site


class NetworkRepresentation:

    def __init__(self, protein, filter_manager, include_kinases_from_groups=False):
        self.protein = protein
        self.filter_manager = filter_manager
        self.include_kinases_from_groups = include_kinases_from_groups
        self.protein_mutations = get_raw_mutations(protein, filter_manager)

        sites, kinases, kinase_groups = self.get_sites_and_kinases()

        from sqlalchemy import and_
        kinases_counts = dict()
        for kinase in kinases:
            if kinase.protein:

                count = get_raw_mutations(kinase.protein, filter_manager, count=True)

                # related discussion: #72
                kinases_counts[kinase] = count

                # KINASES NOT MAPPED TO PROTEINS ARE NOT SHOWN

        protein_kinases_names = [kinase.name for kinase in kinases]
        kinase_gene_ids = [kinase.protein.gene_id for kinase in kinases if kinase.protein]

        drugs = filter_manager.query_all(
            Drug,
            lambda q: and_(
                q,
                Gene.id.in_(kinase_gene_ids)
            ),
            lambda query: query.join(Drug.target_genes)
        )
        drugs_by_kinase = defaultdict(set)
        for drug in drugs:
            for target_gene in drug.target_genes:
                drugs_by_kinase[target_gene].add(drug)

        kinase_reprs = []
        for kinase, count in kinases_counts.items():
            json_repr = kinase.to_json()
            if json_repr['protein']:
                json_repr['protein']['mutations_count'] = count

            json_repr['drugs_targeting_kinase_gene'] = [
                drug.to_json() for drug in drugs_by_kinase[kinase.protein.gene]
            ]
            kinase_reprs.append(json_repr)

        self.muts_by_site = divide_muts_by_sites(self.protein_mutations, sites)

        sites = [
            site
            for site in sites
            if (
                self.get_site_kinases(site) or
                self.get_site_kinase_groups(site)
            )
        ]

        data = {
            'kinases': kinase_reprs,
            'protein': {
                'name': protein.gene.name,
                'is_preferred': protein.is_preferred_isoform,
                'refseq': protein.refseq,
                'mutations_count': len(self.protein_mutations),
                'kinases': protein_kinases_names
            },
            'sites': [
                self.prepare_site(site)
                for site in sites
            ],
            'kinase_groups': [
                {
                    'name': group.name,
                    'kinases': list(
                        {
                            kinase.name
                            for kinase in group.kinases
                        }.intersection(protein_kinases_names)
                    ),
                    'total_cnt': len(group.kinases)
                }
                for group in kinase_groups
            ]
        }
        self.data = data

    @staticmethod
    def most_significant_impact(impacts):
        desc = ['direct', 'network-rewiring', 'proximal', 'distal', 'none']
        for impact in desc:
            if impact in impacts:
                return impact
        return desc[-1]

    def get_site_kinases(self, site):
        return site.kinases

    def get_site_kinase_groups(self, site):
        return site.kinase_groups

    def prepare_site(self, site):
        site_mutations = self.muts_by_site[site]
        mutations = [
            {
                'ref': mutation.ref,
                'pos': mutation.position,
                'alt': mutation.alt,
                'impact': mutation.impact_on_specific_ptm(site)
            }
            for mutation in site_mutations
        ]

        site_kinases = self.get_site_kinases(site)
        site_kinase_groups = self.get_site_kinase_groups(site)

        return {
            'position': site.position,
            'residue': site.residue,
            'ptm_type': site.type,
            'kinases': [kinase.name for kinase in site_kinases],
            'kinase_groups': [group.name for group in site_kinase_groups],
            'kinases_count': len(site_kinases),
            'sequence': site.sequence,
            'mutations_count': len(site_mutations),
            'mutations': mutations,
            'mimp_losses': [
                mimp.pwm
                for mutation in site_mutations
                for mimp in mutation.meta_MIMP
                if mimp.is_loss
            ],
            'mimp_losses_family': [
                mimp.pwm_family
                for mutation in site_mutations
                for mimp in mutation.meta_MIMP
                if mimp.is_loss
            ],
            'mimp_gains_family': [
                mimp.pwm_family
                for mutation in site_mutations
                for mimp in mutation.meta_MIMP
                if mimp.is_gain
            ],
            'mimp_gains': [
                mimp.pwm
                for mutation in site_mutations
                for mimp in mutation.meta_MIMP
                if mimp.is_gain
            ],
            'impact': self.most_significant_impact(set(
                mutation['impact']
                for mutation in mutations
            ))
        }

    def as_json(self):
        return self.data

    def get_sites_and_kinases(self):
        from models import Site
        from sqlalchemy import and_
        from sqlalchemy import or_
        sites = [
            site
            for site in self.filter_manager.query_all(
                Site,
                lambda q: and_(
                    q,
                    Site.protein == self.protein,
                    or_(
                        Site.kinases.any(),
                        Site.kinase_groups.any()
                    )
                )
            )
        ]

        kinases = set(
            kinase
            for site in sites
            for kinase in (
                site.kinases +
                (site.kinase_groups if self.include_kinases_from_groups else [])
            )
        )

        groups = set()

        for site in sites:
            groups.update(site.kinase_groups)

        return sites, kinases, groups

    def as_tsv(self):
        header = [
            'target_protein', 'target_protein_refseq',
            'target_site', 'target_site_type',
            'target_site_mutation_impact', 'bound_enzyme',
            'drug_targeting_bound_enzyme'
        ]
        content = ['#' + '\t'.join(header)]

        network = self.data

        for site in network['sites']:
            target_site = '%s,%s' % (site['position'], site['residue'])
            protein_and_site = [
                self.protein.gene_name,
                self.protein.refseq,
                target_site,
                site['ptm_type'],
                site['impact']
            ]

            for kinase_name in site['kinases']:
                try:
                    kinase = list(filter(lambda k: k['name'] == kinase_name, network['kinases']))[0]
                except IndexError:
                    continue
                drugs = kinase['drugs_targeting_kinase_gene']
                drugs = ','.join([drug['name'] for drug in drugs]) or ''
                row = protein_and_site + [kinase_name, drugs]
                content.append('\t'.join(row))

            for kinase_group in site['kinase_groups']:
                row = protein_and_site + [kinase_group]
                content.append('\t'.join(row))

        return '\n'.join(content)


def list_without_nones(iterable):
    return list(filter(lambda x: x is not None, iterable))


class PredictedNetworkRepresentation(NetworkRepresentation):

    def get_sites_and_kinases(self):
        mimp_mutations = [m for m in self.protein_mutations if m.meta_MIMP]
        sites = set()
        kinases = set()
        groups = set()
        for mimp_mutation in mimp_mutations:
            for mimp in mimp_mutation.meta_MIMP:
                sites.add(mimp.site)
                kinases.add(mimp.kinase)
                groups.add(mimp.kinase_group)
        return list_without_nones(sites), list_without_nones(kinases), list_without_nones(groups)

    def get_site_kinases(self, site):
        site_mutations = self.muts_by_site[site]
        return list_without_nones({
            mimp.kinase
            for mutation in site_mutations
            for mimp in mutation.meta_MIMP
        })

    def get_site_kinase_groups(self, site):
        site_mutations = self.muts_by_site[site]
        return list_without_nones({
            mimp.kinase_group
            for mutation in site_mutations
            for mimp in mutation.meta_MIMP
        })


def create_representation(protein, filter_manager, include_mimp_gain_kinases=False):
    if include_mimp_gain_kinases:
        representation = PredictedNetworkRepresentation(protein, filter_manager)
    else:
        representation = NetworkRepresentation(protein, filter_manager)
    return representation


class NetworkView(AbstractProteinView):
    """View for local network of proteins"""

    filter_class = NetworkViewFilters

    def _create_option_widgets(self, filter_manager):

        return [
            FilterWidget(
                'Show sites', 'binary',
                filter=filter_manager.filters['JavaScript.show_sites']
            ),
            FilterWidget(
                'Clone kinases by site', 'binary',
                filter=filter_manager.filters['JavaScript.clone_by_site']
            ),
            FilterWidget(
                'Prevent drug overlapping', 'binary',
                filter=filter_manager.filters['JavaScript.collide_drugs']
            ),
        ]

    def index(self):
        """Show SearchView as default page"""
        return redirect(url_for('SearchView:default', target='proteins'))

    def show(self, refseq, predicted_interactions=False):
        """Show a protein network visualisation"""

        protein, filter_manager = self.get_protein_and_manager(refseq)

        user_datasets = current_user.datasets_names_by_uri()

        return template(
            'network/show.html', protein=protein,
            filters=filter_manager,
            option_widgets=self._create_option_widgets(filter_manager),
            widgets=create_widgets(
                protein,
                filter_manager.filters,
                custom_datasets_names=user_datasets.values()
            ),
            mutation_types=Mutation.types,
            predicted_interactions=predicted_interactions
        )

    def predicted(self, refseq):
        return self.show(refseq, predicted_interactions=True)

    def download_predicted(self, refseq, format):
        return self.download(refseq, format, include_mimp_gain_kinases=True)

    def download(self, refseq, format, include_mimp_gain_kinases=False):

        protein, filter_manager = self.get_protein_and_manager(refseq)

        Formatter = namedtuple('Formatter', 'get_content mime_type extension')

        representation = create_representation(protein, filter_manager, include_mimp_gain_kinases)

        formatters = {
            'json': Formatter(
                lambda: json.dumps(representation.as_json()),
                'text/json',
                'json'
            ),
            'tsv': Formatter(
                representation.as_tsv,
                'text/tsv',
                'tsv'
            )
        }

        if format not in formatters:
            raise abort(404)

        formatter = formatters[format]

        name = refseq + '-' + filter_manager.url_string(expanded=True)

        if include_mimp_gain_kinases:
            name = 'predicted-' + name

        filename = '%s.%s' % (name, formatter.extension)

        return Response(
            formatter.get_content(),
            mimetype=formatter.mime_type,
            headers={'Content-disposition': 'attachment; filename="%s"' % filename}
        )

    def predicted_representation(self, refseq):
        """Representation (of predicted network) exposed to an API user"""
        return self.representation(refseq, include_mimp_gain_kinases=True)

    def representation(self, refseq, include_mimp_gain_kinases=False):
        """Representation (of network) exposed to an API user"""

        protein, filter_manager = self.get_protein_and_manager(refseq)

        representation = create_representation(protein, filter_manager, include_mimp_gain_kinases)

        response = {'network': representation.as_json()}

        return jsonify(response)

    def predicted_data(self, refseq):
        return self.data(refseq, include_mimp_gain_kinases=True)

    def data(self, refseq, include_mimp_gain_kinases=False):
        """Internal endpoint used for network rendering and asynchronous updates"""

        protein, filter_manager = self.get_protein_and_manager(refseq)

        representation = create_representation(protein, filter_manager, include_mimp_gain_kinases)

        response = {
            'representation': {
                'network': representation.as_json(),
                'clone_by_site': filter_manager.get_value('JavaScript.clone_by_site'),
                'show_sites': filter_manager.get_value('JavaScript.show_sites'),
                'collide_drugs': filter_manager.get_value('JavaScript.collide_drugs'),
            },
            'filters': filters_data_view(protein, filter_manager)
        }

        return jsonify(response)

