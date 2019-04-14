from database import db
from database_testing import DatabaseTest
from miscellaneous import make_named_temp_file
from imports.sites.ptm_var import PTMVarImporter
from test_imports.test_proteins import create_test_proteins

sites_data = """\
gene	position	residue	enzymes	pmid	type
NM_003955	6	K		12459551,LT_LIT.1	ubiquitination
NM_003955	204	Y	JAK2,LCK	12783885,LT_LIT.1,LT_LIT.2,LT_LIT.3,MS_LIT.1	phosphorylation
NM_003955	221	Y	JAK2,LCK	12783885,15173187,LT_LIT.1,LT_LIT.2,LT_LIT.3	phosphorylation
"""


class TestImport(DatabaseTest):

    def test_sites(self):
        proteins = create_test_proteins(['NM_003955'])
        # Sequence is needed for validation. Validation is tested on model level.
        proteins['NM_003955'].sequence = 'MVTHSKFPAAGMSRPLDTSLRLKTFSSKSEYQLVVNAVRKLQESGFYWSAVTGGEANLLLSAEPAGTFLIRDSSDQRHFFTLSVKTQSGTKNLRIQCEGGSFSLQSDPRSTQPVPRFDCVLKLVHHYMPPPGAPSFPSPPTEPSSEVPEQPSAQPLPGSPPRRAYYIYSGGEKIPLVLSRPLSSNVATLQHLCRKTVNGHLDSYEKVTQLPGPIREFLDQYDAPL*'
        db.session.add_all(proteins.values())

        filename = make_named_temp_file(sites_data)

        importer = PTMVarImporter()

        sites = importer.load_sites(filename)

        assert len(sites) == 3
        sites = {site.position: site for site in sites}

        assert sites[6].residue == 'K'
        assert sites[6].types_names == {'ubiquitination'}

        assert {kinase.name for kinase in sites[204].kinases} == {'JAK2', 'LCK'}
