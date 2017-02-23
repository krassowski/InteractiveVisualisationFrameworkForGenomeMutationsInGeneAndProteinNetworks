from view_testing import ViewTest
from models import Protein
from models import Gene
from models import Mutation
from models import Cancer
from models import CancerMutation
from models import InheritedMutation
from models import ClinicalData
from models import The1000GenomesMutation
from models import ExomeSequencingMutation
from models import Site
from database import db
import json


def test_protein_data():
    return {
        'refseq': 'NM_000123',
        'gene': Gene(name='SomeGene'),
        'sequence': 'MART'
    }


class TestProteinView(ViewTest):

    def test_show(self):

        p = Protein(**test_protein_data())
        db.session.add(p)

        response = self.client.get('/protein/show/NM_000123')

        assert response.status_code == 200
        assert b'SomeGene' in response.data
        assert b'NM_000123' in response.data
        assert b'MART' in response.data

    def test_sites(self):

        p = Protein(**test_protein_data())

        sites = [
            Site(position=3, residue='R', type='phosphorylation'),
            Site(position=4, residue='T', type='methylation')
        ]
        db.session.add(p)
        p.sites = sites

        response = self.client.get('/protein/sites/NM_000123')

        assert response.status_code == 200
        assert response.content_type == 'application/json'

        json_response = json.loads(response.data.decode())
        assert len(json_response) == 2

        phospo_site_repr = None

        for site_repr in json_response:
            if site_repr['type'] == 'phosphorylation':
                phospo_site_repr = site_repr

        assert phospo_site_repr

    def test_details(self):

        p = Protein(**test_protein_data())

        p.mutations = [
            Mutation(
                position=1,
                alt='K',
                meta_cancer=[
                    CancerMutation(
                        cancer=Cancer(name='Ovarian', code='OV')
                    ),
                    CancerMutation(
                        cancer=Cancer(name='Breast', code='BRCA')
                    )
                ]
            ),
            Mutation(
                position=2,
                alt='K',
                meta_inherited=InheritedMutation(
                    clin_data=[
                        ClinicalData(
                            disease_name='Disease X',
                            sig_code='1'
                        ),
                        ClinicalData(
                            disease_name='Disease Y',
                            sig_code='1'
                        )
                    ]
                )
            ),
            Mutation(
                position=3,
                alt='K',
                meta_1KG=The1000GenomesMutation(
                    maf_afr=0.5,
                    maf_eur=0.2
                )
            ),
            Mutation(
                position=4,
                alt='K',
                meta_ESP6500=ExomeSequencingMutation(
                    maf_ea=0.5
                )
            )
        ]

        db.session.add(p)

        expected_source_meta = {
            'TCGA': ['OV', 'BRCA'],
            'ClinVar': ['Disease X', 'Disease Y'],
            '1KGenomes': ['African', 'European'],
            'ESP6500': ['European American']
        }

        for source, expected_meta in expected_source_meta.items():
            response = self.client.get(
                '/protein/details/NM_000123?filters=Mutation.sources:in:%s' % source
            )
            assert response.status_code == 200
            assert response.content_type == 'application/json'
            json_response = json.loads(response.data.decode())
            assert json_response['refseq'] == 'NM_000123'
            assert set(json_response['meta']) == set(expected_meta)
            assert json_response['muts_count'] == 1
