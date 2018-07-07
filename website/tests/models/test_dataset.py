from database import db
from model_testing import ModelTest
from models import User
from models import UsersMutationsDataset


test_query = """\
HTR3E I183823756M
STAT6 W737C
chr12 57490358 C A\
"""


def create_test_dataset(owner=None):
    from views.search import MutationSearch

    search = MutationSearch(text_query=test_query)

    dataset = UsersMutationsDataset(
        name='test',
        data=search,
        owner=owner
    )

    db.session.add(dataset)
    db.session.commit()

    return dataset


class DatasetTest(ModelTest):

    def test_init(self):
        user = User('user@domain', 'password')

        dataset = create_test_dataset(owner=user)

        assert user.datasets == [dataset]

        public_id = dataset.uri

        d = UsersMutationsDataset.query.filter_by(uri=public_id).one()

        assert d == dataset

        assert dataset.data
        assert dataset.query_size == 3

        # should be empty as no mutations where imported
        assert not dataset.mutations

        assert dataset.name == 'test'

        from datetime import timedelta
        assert dataset.life_expectancy < timedelta(days=7)
