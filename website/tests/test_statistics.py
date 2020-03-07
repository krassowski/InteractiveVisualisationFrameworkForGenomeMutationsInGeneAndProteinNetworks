from database_testing import DatabaseTest
from database import db
import models


class StatisticsTest(DatabaseTest):

    def exposed_stats(self, limit_to):
        from stats import Statistics
        s = Statistics()
        s.calc_all(limit_to=limit_to)
        return s.get_all()

    def test_simple_models(self):

        model_stats = {
            'pathways': models.Pathway,
            'proteins': models.Protein,
            'genes': models.Gene,
            'kinases': models.Kinase,
            'kinase_groups': models.KinaseGroup,
            'sites': models.Site,
            'cancer': models.Cancer
        }

        for name, model in model_stats.items():
            model_objects = [model() for _ in range(10)]
            db.session.add_all(model_objects)

        stats = self.exposed_stats(limit_to='|'.join(model_stats))

        for name, model in model_stats.items():
            assert stats[name] == 10

    def test_mutations_count(self):

        mutation_counts = {
            models.MIMPMutation: 100,
            models.The1000GenomesMutation: 3,
            models.MC3Mutation: 5,
            models.ExomeSequencingMutation: 2,
            models.InheritedMutation: 4
        }

        mutation_models = {
            model.name: model
            for model in mutation_counts.keys()
        }

        for model, count in mutation_counts.items():
            for _ in range(count):
                m = models.Mutation()
                metadata = model(mutation=m)
                db.session.add(metadata)
            db.session.commit()

        stats = self.exposed_stats(limit_to='mutations')

        def get_var_name(model_name):
            return model_name.replace('1', 'T')

        for name, model in mutation_models.items():
            assert stats['muts'][get_var_name(name)] == mutation_counts[model]

        assert stats['muts']['all'] == sum(mutation_counts.values())

        # confirmed are all without mimp
        assert stats['muts']['all_confirmed'] == 3 + 5 + 2 + 4

    def test_from_many_sources(self):

        # create one mutation which is present in multiple sources
        m = models.Mutation()
        metadata_1 = models.InheritedMutation(mutation=m)
        metadata_2 = models.MC3Mutation(mutation=m)
        db.session.add_all([metadata_1, metadata_2])

        from stats import Statistics
        statistics = Statistics()

        in_many_sources = statistics.from_more_than_one_source()

        assert in_many_sources == 1

    def test_interactions(self):

        from models import Protein, Site, Kinase, KinaseGroup

        p1 = Protein(
            sites=[
                Site(),
                Site(kinases={Kinase()}, kinase_groups={KinaseGroup()})
            ]
        )
        db.session.add(p1)
        p2 = Protein(
            sites=[Site(kinases={Kinase()})]
        )
        db.session.add(p2)

        u_all_interactions = 0
        u_kinases_covered = set()
        u_kinase_groups_covered = set()
        u_proteins_covered = set()
        for protein in models.Protein.query.all():
            for site in protein.sites:
                kinases = site.kinases
                kinase_groups = site.kinase_groups
                u_all_interactions += len(kinases) + len(kinase_groups)
                u_kinases_covered.update(kinases)
                u_kinase_groups_covered.update(kinase_groups)

                if kinases or kinase_groups:
                    u_proteins_covered.add(protein)

        from stats import Statistics
        statistics = Statistics()
        all_interactions = statistics.interactions()
        kinases_covered = statistics.kinases_covered()
        kinase_groups_covered = statistics.kinase_groups_covered()
        proteins_covered = statistics.proteins_covered()

        assert all_interactions == u_all_interactions
        assert kinases_covered == len(u_kinases_covered)
        assert kinase_groups_covered == len(u_kinase_groups_covered)
        assert proteins_covered == len(u_proteins_covered)

    def test_table_generation(self):
        from stats.table import generate_source_specific_summary_table

        table = generate_source_specific_summary_table()
        assert table
