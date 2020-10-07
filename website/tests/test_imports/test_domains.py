from collections import defaultdict

from database import db
from database_testing import DatabaseTest
from miscellaneous import make_named_temp_file, make_named_gz_file
from imports.protein_data import domains as domains_importer, domains_hierarchy, domains_types
from models import Protein, Gene, InterproDomain

# domain ranges slightly modified to test more combinations
domains_data = """\
Gene stable ID	Transcript stable ID	Protein stable ID	Chromosome/scaffold name	Gene start (bp)	Gene end (bp)	RefSeq mRNA ID	Interpro ID	Interpro Short Description	Interpro Description	Interpro end	Interpro start
ENSG00000104129	ENST00000220496	ENSP00000220496	15	41060067	41099675	NM_018163	IPR001623	DnaJ_domain	DnaJ domain	31	13
ENSG00000104129	ENST00000220496	ENSP00000220496	15	41060067	41099675	NM_018163	IPR001623	DnaJ_domain	DnaJ domain	46	31
ENSG00000078043	ENST00000585916	ENSP00000465676	18	44388353	44500123	NM_004671	IPR003034	SAP_dom	SAP domain	65	1
ENSG00000078043	ENST00000585916	ENSP00000465676	18	44388353	44500123	NM_004671	IPR003034	SAP_dom	SAP domain	45	11
ENSG00000078043	ENST00000585916	ENSP00000465676	18	44388353	44500123	NM_004671	IPR004181	Znf_MIZ	Zinc finger, MIZ-type	390	342
ENSG00000078043	ENST00000585916	ENSP00000465676	18	44388353	44500123	NM_004671	IPR004181	Znf_MIZ	Zinc finger, MIZ-type	408	390
ENSG00000078043	ENST00000585916	ENSP00000465676	18	44388353	44500123	NM_004671	IPR023321	PINIT	PINIT domain	297	141
ENSG00000078043	ENST00000585916	ENSP00000465676	18	44388353	44500123	NM_004671	IPR023321	PINIT	PINIT domain	299	175
"""


# head of data/ParentChildTreeFile.txt*
domains_hierarchy_data = """\
IPR000008::C2 domain
--IPR002420::Phosphatidylinositol 3-kinase, C2 domain
--IPR014020::Tensin phosphatase, C2 domain
--IPR033884::Calpain C2 domain
IPR000010::Cystatin domain
--IPR025760::Fetuin-A-type cystatin domain
--IPR025764::Fetuin-B-type cystatin domain
--IPR027358::Kininogen-type cystatin domain
IPR000053::Thymidine/pyrimidine-nucleoside phosphorylase
--IPR013466::Thymidine phosphorylase/AMP phosphorylase
----IPR017713::AMP phosphorylase
----IPR028579::Putative thymidine phosphorylase
--IPR018090::Pyrimidine-nucleoside phosphorylase, bacterial/eukaryotic
----IPR013465::Thymidine phosphorylase
IPR000056::Ribulose-phosphate 3-epimerase-like
--IPR026019::Ribulose-phosphate 3-epimerase
"""


minimal_interpro_xml = """\
<?xml version="1.0" encoding="ISO-8859-1"?>
<!DOCTYPE interprodb SYSTEM "interpro.dtd">
<interprodb>
<release>
  <dbinfo dbname="INTERPRO" entry_count="29700" file_date="03-NOV-16" version="60.0"/>
</release>
<interpro id="IPR000001" protein_count="3451" short_name="Kringle" type="Domain">
  <name>Kringle</name>
</interpro>
<interpro id="IPR000003" protein_count="1285" short_name="Retinoid-X_rcpt/HNF4" type="Family">
  <name>Retinoid X receptor/HNF4</name>
</interpro>
<interpro id="IPR000006" protein_count="604" short_name="Metalthion_vert" type="Family">
  <name>Metallothionein, vertebrate</name>
</interpro>
</interprodb>\
"""


class TestImport(DatabaseTest):

    def test_domains_types(self):
        domain_one = InterproDomain(accession='IPR000001')
        domain_three = InterproDomain(accession='IPR000003')
        db.session.add_all([domain_one, domain_three])

        filename = make_named_gz_file(minimal_interpro_xml)

        new_objects = domains_types.load(filename)

        assert domain_one.type == 'Domain'
        assert domain_three.type == 'Family'

        # no new domains should be created (there is no needed for it)
        assert not new_objects

    def test_domains_hierarchy(self):
        existing_top_level_domain = InterproDomain(accession='IPR000008', description='C2 domain')
        existing_domain = InterproDomain(accession='IPR033884', description='Calpain C2 domain')

        db.session.add_all([existing_top_level_domain, existing_domain])

        filename = make_named_temp_file(domains_hierarchy_data)
        new_domains = domains_hierarchy.load(filename)

        assert len(new_domains) == 16 - 2

        assert existing_top_level_domain.level == 0
        assert existing_top_level_domain.parent is None

        assert existing_domain.parent is existing_top_level_domain

        new_domains = {domain.accession: domain for domain in new_domains}

        # this domain was already was in database
        assert 'IPR033884' not in new_domains

        # does a new top level domain have a None parent?
        expected_top_level_domains = ['IPR000010', 'IPR000056']

        for domain in expected_top_level_domains:
            assert new_domains[domain].parent is None

        expected_parents = {
            'IPR025760': 'IPR000010',   # had first-level domain assigned correct parent?
            'IPR018090': 'IPR000053',   # is parent assignment working when going one level back?
            'IPR026019': 'IPR000056'    # does going multiple levels higher back work?
        }

        for child, parent in expected_parents.items():
            assert new_domains[child].parent is new_domains[parent]

    def test_domains(self):
        proteins = [
            Protein(
                refseq='NM_018163',
                sequence='MAVTKELLQMDLYALLGIEEKAADKEVKKAYRQKALSCHPDKNPDNPRAAELFHQLSQALEVLTDAAARAAYDKVRKAKKQAAERTQKLDEKRKKVKLDLEARERQAQAQESEEEEESRSTRTLEQEIERLREEGSRQLEEQQRLIREQIRQERDQRLRGKAENTEGQGTPKLKLKWKCKKEDESKGGYSKDVLLRLLQKYGEVLNLVLSSKKPGTAVVEFATVKAAELAVQNEVGLVDNPLKISWLEGQPQDAVGRSHSGLSKGSVLSERDYESLVMMRMRQAAERQQLIARMQQEDQEGPPT*',
                gene=Gene(chrom='15')
            ),
            Protein(
                refseq='NM_004671',
                sequence='MADFEELRNMVSSFRVSELQVLLGFAGRNKSGRKHDLLMRALHLLKSGCSPAVQIKIRELYRRRYPRTLEGLSDLSTIKSSVFSLDGGSSPVEPDLAVAGIHSLPSTSVTPHSPSSPVGSVLLQDTKPTFEMQQPSPPIPPVHPDVQLKNLPFYDVLDVLIKPTSLVQSSIQRFQEKFFIFALTPQQVREICISRDFLPGGRRDYTVQVQLRLCLAETSCPQEDNYPNSLCIKVNGKLFPLPGYAPPPKNGIEQKRPGRPLNITSLVRLSSAVPNQISISWASEIGKNYSMSVYLVRQLTSAMLLQRLKMKGIRNPDHSRALIKEKLTADPDSEIATTSLRVSLMCPLGKMRLTIPCRAVTCTHLQCFDAALYLQMNEKKPTWICPVCDKKAAYESLILDGLFMEILNDCSDVDEIKFQEDGSWCPMRPKKEAMKVSSQPCTKIESSSVLSKPCSVTVASEASKKKVDVIDLTIESSSDEEEDPPAKRKCIFMSETQSSPTKGVLMYQPSSVRVPSVTSVDPAAIPPSLTDYSVPFHHTPISSMSSDLPGLDFLSLIPVDPQYCPPMFLDSLTSPLTASSTSVTTTSSHESSTHVSSSSSRSETGVITSSGSNIPDIISLD*',
                gene=Gene(chrom='18')
            )
        ]

        db.session.add_all(proteins)

        filename = make_named_temp_file(domains_data)

        new_domains = domains_importer.load(filename)

        assert len(new_domains) == 6
        assert len(proteins[0].domains) == 2

        domains = defaultdict(list)

        for domain in proteins[1].domains:
            domains[domain.interpro.short_description].append(domain)

        def assert_ranges(domain, start, end):
            assert domain.start == start and domain.end == end

        # two SAP domains should be merged for representation purposes due to similarity criteria
        # (these two domain annotation overlap so the smaller one is contained in the bigger)
        sap_domain = domains['SAP_dom'][0]
        assert_ranges(sap_domain, 1, 65)

        intepro_domain = sap_domain.interpro
        assert intepro_domain.accession == 'IPR003034'
        assert intepro_domain.description == 'SAP domain'

        # here the two annotations overlap with more than 75% of common
        assert_ranges(domains['PINIT'][0], 141, 299)

        # and here overlap was too small to merge those domains
        assert len(domains['Znf_MIZ']) == 2
