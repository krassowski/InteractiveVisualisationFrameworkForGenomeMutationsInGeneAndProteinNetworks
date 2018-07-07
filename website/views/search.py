import json
from operator import itemgetter
from urllib.parse import unquote

from flask import make_response, redirect
from flask import render_template as template
from flask import request
from flask import jsonify
from flask import url_for
from flask import flash
from flask import current_app
from flask_classful import FlaskView
from flask_classful import route
from flask_login import current_user
from Levenshtein import distance
from sqlalchemy.orm.exc import NoResultFound

from models import Protein, Pathway, Cancer, GeneList, MC3Mutation
from models import Gene
from models import Mutation
from models import UsersMutationsDataset
from models import UserUploadedMutation
from sqlalchemy import and_, exists, or_
from helpers.filters import FilterManager
from helpers.filters import Filter
from helpers.widgets import FilterWidget
from ._commons import get_genomic_muts
from ._commons import get_protein_muts
from database import db, levenshtein_sorted


class GeneResult:

    def __init__(self, gene, matched_isoforms=None):
        self.gene = gene
        if not matched_isoforms:
            matched_isoforms = []
        self.matched_isoforms = matched_isoforms

    def __getattr__(self, key):
        return getattr(self.gene, key)


def search_proteins(phase, limit=None, filter_manager=None):
    """Search for a protein isoform or gene.
    Only genes which have a primary isoforms will be returned.

    Args:
        'limit': number of genes to be returned (for limit=10 there
                 may be 100 -or more- isoforms and 10 genes returned)
    """
    if not phase:
        return []

    # find by gene name
    filters = [Gene.name.like(phase + '%')]
    sql_filters = None

    if filter_manager:
        divided_filters = filter_manager.prepare_filters(Protein)
        sql_filters, manual_filters = divided_filters
        if manual_filters:
            raise ValueError(
                'From query can apply only use filters with'
                ' sqlalchemy interface'
            )

    if sql_filters:
        filters += sql_filters

    orm_query = (
        Gene.query
        # join with proteins so PTM filter can be applied
        .join(Protein, Gene.preferred_isoform)
        .filter(and_(*filters))
    )

    if limit:
        orm_query = orm_query.limit(limit)

    genes = {gene.name: GeneResult(gene) for gene in orm_query}

    # looking up both by name and refseq is costly - perform it wisely
    if phase.isnumeric():
        phase = 'NM_' + phase
    if phase.startswith('NM_') or phase.startswith('nm_'):

        # TODO: tests for lowercase
        filters = [Protein.refseq.like(phase + '%')]

        if sql_filters:
            filters += sql_filters

        query = Protein.query.filter(and_(*filters))

        if limit:
            # we want to display up to 'limit' genes;
            # still it would be good to restrict isoforms
            # query in such way then even when getting
            # results where all isoforms match the same
            # gene it still provides more than one gene
            query = query.limit(limit * 20)

        for isoform in query:
            if limit and len(genes) > limit:
                break

            gene = isoform.gene

            # add isoform to promoted (matched) isoforms of the gene
            if gene.name in genes:
                if isoform not in genes[gene.name].matched_isoforms:
                    genes[gene.name].matched_isoforms.add(isoform)
            else:
                genes[gene.name] = GeneResult(gene, matched_isoforms={isoform})

        def sort_key(gene):
            return min(
                [
                    distance(isoform.refseq, phase)
                    for isoform in gene.matched_isoforms
                ]
            )

    else:
        # if the phrase is not numeric
        def sort_key(gene):
            return distance(gene.name, phase)

    return sorted(
        genes.values(),
        key=sort_key
    )


class MutationSearch:

    def __init__(self, vcf_file=None, text_query=None, filter_manager=None):
        # note: entries from both file and textarea will be merged

        self.query = ''
        self.results = {}
        self.without_mutations = []
        self.badly_formatted = []
        self.hidden_results_cnt = 0

        if filter_manager:
            def data_filter(elements):
                return filter_manager.apply(
                    elements,
                    itemgetter=itemgetter('mutation')
                )
        else:
            def data_filter(elements):
                return elements

        self.data_filter = data_filter

        if vcf_file:
            self.parse_vcf(vcf_file)

        if text_query:
            self.query += text_query
            self.parse_text(text_query)

        # when parsing is complete, quickly forget where is such complex object
        # like filter_manager so any instance of this class can be pickled.
        self.data_filter = None

    def add_mutation_items(self, items, query_line):

        if not items:
            self.without_mutations.append(query_line)
            return False

        items = self.data_filter(items)

        if not items:
            self.hidden_results_cnt += 1
            return False

        if query_line in self.results:
            for item in self.results[query_line]:
                item['mutation'].meta_user.count += 1
        else:
            for item in items:
                item['mutation'].meta_user = UserUploadedMutation(
                    count=1,
                    query=query_line
                )
            self.results[query_line] = items

    def parse_vcf(self, vcf_file):

        for line in vcf_file:
            line = line.decode('latin1').strip()
            if line.startswith('#'):
                continue
            data = line.split()

            if len(data) < 5:
                if not line:    # if we reached end of the file
                    break
                self.badly_formatted.append(line)
                continue

            chrom, pos, var_id, ref, alts = data[:5]

            if chrom.startswith('chr'):
                chrom = chrom[3:]

            alts = alts.split(',')
            for alt in alts:

                items = get_genomic_muts(chrom, pos, ref, alt)

                chrom = 'chr' + chrom
                parsed_line = ' '.join((chrom, pos, ref, alt)) + '\n'

                self.add_mutation_items(items, parsed_line)

                # we don't have queries in our format for vcf files:
                # those need to be built this way
                self.query += parsed_line

    def parse_text(self, text_query):

        for line in text_query.splitlines():
            data = line.strip().split()
            if len(data) == 4:
                chrom, pos, ref, alt = data
                chrom = chrom[3:]

                items = get_genomic_muts(chrom, pos, ref, alt)

            elif len(data) == 2:
                gene, mut = [x.upper() for x in data]

                items = get_protein_muts(gene, mut)
            else:
                self.badly_formatted.append(line)
                continue

            self.add_mutation_items(items, line)


class SearchViewFilters(FilterManager):

    def __init__(self, **kwargs):
        filters = [
            # Why default = False? Due to used widget: checkbox.
            # It is not possible to distinguish between user not asking for
            # all mutations (so sending nothing in post, since un-checking it
            # will cause it to be skipped in the form) or user doing nothing

            # Why or? Take a look on table:
            # is_ptm    show all muts (by default only ptm)     include?
            # 0         0                                       0
            # 0         1                                       1
            # 1         0                                       1
            # 1         1                                       1
            Filter(
                Mutation, 'is_ptm', comparators=['or'],
                is_attribute_a_method=True,
                default=False
            ),
            Filter(
                Protein, 'has_ptm_mutations', comparators=['eq'],
                as_sqlalchemy=True
            )
        ]
        super().__init__(filters)
        self.update_from_request(request)


def make_widgets(filter_manager):
    return {
        'is_ptm': FilterWidget(
            'Show all mutations (by default only PTM mutations are shown)',
            'checkbox',
            filter=filter_manager.filters['Mutation.is_ptm']
        ),
        'at_least_one_ptm': FilterWidget(
            'Show only proteins with PTM mutations', 'checkbox',
            filter=filter_manager.filters['Protein.has_ptm_mutations']
        )
    }


class SearchView(FlaskView):
    """Enables searching in any of registered database models."""

    def before_request(self, name, *args, **kwargs):
        filter_manager = SearchViewFilters()
        endpoint = self.build_route_name(name)

        return filter_manager.reformat_request_url(
            request, endpoint, *args, **kwargs
        )

    @route('/')
    def default(self):
        """Render default search form prompting to search for a protein."""
        return self.proteins()

    def proteins(self):
        """Render search form and results (if any) for proteins"""

        filter_manager = SearchViewFilters()

        query = request.args.get('proteins', '')

        results = search_proteins(query, 20, filter_manager)

        return template(
            'search/index.html',
            target='proteins',
            results=results,
            widgets=make_widgets(filter_manager),
            query=query
        )

    @route('saved/<uri>')
    def user_mutations(self, uri):

        filter_manager = SearchViewFilters()

        dataset = UsersMutationsDataset.query.filter_by(
            uri=uri
        ).one()

        if dataset.owner and dataset.owner != current_user:
            current_app.login_manager.unauthorized()

        response = make_response(template(
            'search/index.html',
            target='mutations',
            results=dataset.data.results,
            widgets=make_widgets(filter_manager),
            without_mutations=dataset.data.without_mutations,
            query=dataset.data.query,
            badly_formatted=dataset.data.badly_formatted,
            dataset=dataset
        ))
        return response

    @route('/mutations', methods=['POST', 'GET'])
    def mutations(self):
        """Render search form and results (if any) for proteins or mutations"""

        filter_manager = SearchViewFilters()

        if request.method == 'POST':
            textarea_query = request.form.get('mutations', False)
            vcf_file = request.files.get('vcf-file', False)

            mutation_search = MutationSearch(
                vcf_file,
                textarea_query,
                filter_manager
            )

            store_on_server = request.form.get('store_on_server', False)

            if store_on_server:
                name = request.form.get('dataset_name', 'Custom Dataset')

                if current_user.is_authenticated:
                    user = current_user
                else:
                    user = None
                    flash(
                        'To browse uploaded mutations easily in the '
                        'future, please register or log in with this form',
                        'warning'
                    )

                dataset = UsersMutationsDataset(
                    name=name,
                    data=mutation_search,
                    owner=user
                )

                db.session.add(dataset)
                db.session.commit()

                url = url_for(
                    'SearchView:user_mutations',
                    uri=dataset.uri,
                    _external=True
                )

                flash(
                    'Your mutations have been saved on the server.'
                    '<p>You can access the results later using following URL: '
                    '<a href="' + url + '">' + url + '</a></p>',
                    'success'
                )
        else:
            mutation_search = MutationSearch()

        response = make_response(template(
            'search/index.html',
            target='mutations',
            hidden_results_cnt=mutation_search.hidden_results_cnt,
            results=mutation_search.results,
            widgets=make_widgets(filter_manager),
            without_mutations=mutation_search.without_mutations,
            query=mutation_search.query,
            badly_formatted=mutation_search.badly_formatted
        ))

        return response

    def form(self, target):
        """Return an empty HTML form appropriate for given target."""
        filter_manager = SearchViewFilters()
        return template(
            'search/forms/' + target + '.html',
            target=target,
            widgets=make_widgets(filter_manager)
        )

    def anything(self):
        query = unquote(request.args.get('query')) or ''
        if ' ' in query:
            return redirect(url_for('SearchView:mutations', mutations=query))
        else:
            return redirect(url_for('SearchView:proteins', proteins=query))

    def autocomplete_all(self):
        """
        Supports:
            Protein or gene:
            {refseq_id}
            {gene}

            Mutation:
            {gene} {ref}{pos}{alt}
            {chr} {pos} {ref} {alt}

            Pathway:
            {pathway}
            GO:{pathway_gene_ontology_id}
            REAC:{pathway_reactome_id}

            Genes with mutations detected in cancer samples:
            {cancer name}
        """

        query = unquote(request.args.get('q')) or ''

        if ' ' in query:
            items = autocomplete_mutation(query)
        else:
            items = autocomplete_gene(query)

        pathways = suggest_matching_pathways(query)

        cancers = suggest_matching_cancers(query)

        items.extend(cancers)
        items.extend(pathways)

        return json.dumps({'entries': items})


def suggest_matching_cancers(query, count=2):
    cancers = Cancer.query.filter(
        or_(
            Cancer.code.ilike(query + '%'),
            Cancer.name.ilike('%' + query + '%'),
        )
    ).limit(count)

    tcga_list = GeneList.query.filter_by(mutation_source_name=MC3Mutation.name).one()

    return [
        {
            'name': cancer.name,
            'code': cancer.code,
            'type': 'cancer',
            'url': url_for(
                'GeneView:list',
                list_name=tcga_list.name,
                filters=(
                    'Mutation.sources:in:%s' % tcga_list.mutation_source_name
                    +
                    ';Mutation.mc3_cancer_code:in:%s' % cancer.code
                )
            )
        }
        for cancer in cancers
    ]


def suggest_matching_pathways(query, count=2):
    go = reactome = None

    if query.startswith('GO:'):
        go = query[3:]
        pathway_filter = Pathway.gene_ontology.like(go + '%')
        column = Pathway.gene_ontology
    elif query.startswith('REAC:'):
        reactome = query[5:]
        pathway_filter = Pathway.reactome.like(reactome + '%')
        column = Pathway.reactome
    else:
        pathway_filter = Pathway.description.like('%' + query + '%')
        column = Pathway.description

    pathways = Pathway.query.filter(pathway_filter)
    pathways = levenshtein_sorted(pathways, column, query)

    pathways = pathways.limit(count + 1).all()

    # show {count} of pathways; if we got {count} + 1 results suggest searching for all

    def display_name(pathway):
        name = pathway.description
        if go:
            name += ' (GO:' + pathway.gene_ontology + ')'
        if reactome:
            name += ' (REAC:' + pathway.reactome + ')'

        return name

    items = [
        {
            'name': display_name(pathway),
            'type': 'pathway',
            'gene_ontology': pathway.gene_ontology,
            'reactome': pathway.reactome,
            'url': url_for('PathwaysView:show', gene_ontology_id=pathway.gene_ontology, reactome_id=pathway.reactome)
        }
        for pathway in pathways[:count]
    ]
    if len(pathways) > count:
        items.append(
            {
                'name': 'Show all pathways matching <i>%s</i>' % query,
                'type': 'see_more',
                'url': url_for('PathwaysView:all', query=query)
            }
        )
    return items


def gene_exists(name):
    return db.session.query(exists().where(Gene.name == name)).scalar()


def json_message(msg):
    return [{'name': msg, 'type': 'message'}]


def autocomplete_gene(query):
    entries = search_proteins(query, 6)
    items = [
        gene.to_json()
        for gene in entries
    ]
    for item in items:
        item['type'] = 'gene'

    return items


def autocomplete_mutation(query):
    import re
    # TODO: rewriting this into regexp-based set of function may increase readability

    data = query.upper().strip().split()

    if len(data) == 1:

        if query.startswith('CHR'):
            return json_message('Awaiting for mutation in <code>{chrom} {pos} {ref} {alt}</code> format')
        else:
            gene = data[0].strip()

            if not gene_exists(gene):
                return json_message('Gene %s not found in the database' % gene)

            return json_message('Awaiting for <code>{ref}{pos}{alt}</code> - expecting mutation in <code>{gene} {ref}{pos}{alt}</code> format')

    elif len(data) == 4:
        if not query.startswith('CHR'):
            return []

        chrom, pos, ref, alt = data
        chrom = chrom[3:]

        try:
            items = get_genomic_muts(chrom, pos, ref, alt)
        except ValueError:
            return json_message(
                'Did you mean to search for mutation with <code>{chrom} {pos} {ref} {alt}</code> format?'
                ' The <code>{pos}</code> should be an integer.'
            )

        value_type = 'nucleotide mutation'

    elif len(data) == 3:
        if not query.startswith('CHR'):
            return []

        return json_message('Awaiting for mutation in <code>{chrom} {pos} {ref} {alt}</code> format')

    elif len(data) == 2:
        gene, mut = data

        if gene.startswith('CHR'):
            return json_message('Awaiting for mutation in <code>{chrom} {pos} {ref} {alt}</code> format')

        try:
            gene_obj = Gene.query.filter_by(name=gene).one()
        except NoResultFound:
            return json_message('No isoforms for %s found' % gene)

        all_parts = re.fullmatch('(?P<ref>\D)(?P<pos>(\d)+)(?P<alt>\D)', mut)
        ref_and_pos = re.fullmatch('(?P<ref>\D)(?P<pos>(\d)+)', mut)

        if all_parts:
            mut_data = all_parts.groupdict()

        if ref_and_pos:
            mut_data = ref_and_pos.groupdict()

        if all_parts or ref_and_pos:
            ref = mut_data['ref']
            try:
                pos = int(mut_data['pos'])
            except ValueError:
                return json_message(
                    'Did you mean to search for mutation with <code>{gene} {ref}{pos}{alt}</code> format?'
                    ' The <code>{pos}</code> should be an integer.'
                )

            # validate if ref is correct
            valid = False
            for isoform in gene_obj.isoforms:
                try:
                    if isoform.sequence[pos - 1] == ref:
                        valid = True
                        break
                except IndexError:
                    # not in range of this isoform, nothing scary.
                    pass

            if not valid:
                return json_message(
                    'Given reference residue <code>%s</code> does not match any of %s isoforms of %s gene at position <code>%s</code>'
                    %
                    (ref, len(gene_obj.isoforms), gene, pos)
                )

        if ref_and_pos:
            # if ref is correct and ask user to specify alt
            return json_message('Awaiting for <code>{alt}</code> - expecting mutation in <code>{gene} {ref}{pos}{alt}</code> format')

        only_ref = re.fullmatch('(?P<ref>\D)', mut)
        if only_ref:
            # prompt user to write more
            return json_message('Awaiting for <code>{pos}{alt}</code> - expecting mutation in <code>{gene} {ref}{pos}{alt}</code> format')

        try:
            items = get_protein_muts(gene, mut)
        except ValueError:
            return json_message(
                'Did you mean to search for mutation with <code>{gene} {ref}{pos}{alt}</code> format?'
                ' The <code>{pos}</code> should be an integer.'
            )

        value_type = 'aminoacid mutation'
    else:
        items = []
        value_type = 'incomplete mutation'

    for item in items:
        item['protein'] = item['protein'].to_json()
        item['mutation'] = item['mutation'].to_json()
        item['input'] = query
        item['type'] = value_type

    return items
