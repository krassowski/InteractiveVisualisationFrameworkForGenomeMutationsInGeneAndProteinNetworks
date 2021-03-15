import os
import pickle
from contextlib import suppress
from datetime import datetime
from datetime import timedelta
from typing import TYPE_CHECKING

from flask import url_for
from sqlalchemy import and_, not_
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import validates
from werkzeug.utils import cached_property

import security
from database import db, update
from database.types import MediumPickle, DataFrameStore
from database.functions import utc_now, utc_days_after
from exceptions import ValidationError
from .model import Model

if TYPE_CHECKING:
    from search.mutation import MutationSearch


class CMSModel(Model):
    """Models descending from Model are supposed to hold settings and other data

    to handled by 'Content Management System', including Users and Page models.
    """
    __abstract__ = True
    __bind_key__ = 'cms'


class Count(CMSModel):
    """Statistics holder"""
    name = db.Column(db.String(254), unique=True)
    value = db.Column(db.Integer)


class Plot(CMSModel):
    """Holds a plot data"""
    name = db.Column(db.String(254), unique=True)
    value = db.Column(MediumPickle)


class Dataset(CMSModel):
    """Holds a dataset"""
    name = db.Column(db.String(254), unique=True)
    value = db.Column(DataFrameStore)


class VennDiagram(CMSModel):
    """Holds a Venn diagram data"""
    name = db.Column(db.String(254), unique=True)
    value = db.Column(db.PickleType)


class BadWord(CMSModel):
    """Model for words which should be filtered out"""

    word = db.Column(db.Text())


class ShortURL(CMSModel):
    """Model for URL shortening entries"""

    address = db.Column(db.Text())

    alphabet = (
        'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    )

    base = len(alphabet)

    @property
    def shorthand(self):
        if self.id <= 0:
            raise ValueError('ShortURL id has to be greater than 0')

        shorthand = ''
        id_number = self.id - 1

        remainder = id_number % self.base
        id_number //= self.base
        shorthand += self.alphabet[remainder]

        while id_number:
            remainder = id_number % self.base
            id_number //= self.base
            shorthand += self.alphabet[remainder]

        return shorthand

    @staticmethod
    def shorthand_to_id(shorthand):
        id_number = 0
        for pos, letter in enumerate(shorthand):
            weight = pow(ShortURL.base, pos)
            id_number += weight * ShortURL.alphabet.index(letter)
        return id_number + 1


class AnonymousUser:

    is_anonymous = True
    is_active = False
    is_authenticated = False
    datasets = []

    @property
    def access_level(self):
        return 0

    @property
    def is_moderator(self):
        return False

    @property
    def is_admin(self):
        return False

    def datasets_names_by_uri(self):
        return {}

    def get_id(self):
        return None


class UsersMutationsDataset(CMSModel):
    mutations_dir = 'user_mutations'

    name = db.Column(db.String(256))
    uri = db.Column(db.String(256), unique=True, index=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    query_count = db.Column(db.Integer)
    results_count = db.Column(db.Integer)
    # as we get newer MySQL version, use of server_default would be preferable
    created_on = db.Column(db.DateTime, default=utc_now())
    # using default, not server_default as MySQL cannot handle functions as defaults, see:
    # https://dba.stackexchange.com/questions/143953/how-can-i-set-timestamps-default-to-future-date
    store_until = db.Column(db.DateTime, default=utc_days_after(7))

    def __init__(self, *args, **kwargs):
        data = kwargs.pop('data')
        super().__init__(*args, **kwargs)
        self.data = data

    @classmethod
    def by_uri(cls, uri):
        return cls.query.filter_by(uri=uri.rstrip('/')).one()

    @property
    def data(self) -> 'MutationSearch':
        if not hasattr(self, '_data'):
            try:
                self._data = self._load_from_file()
            except FileNotFoundError:
                # None if associated file was deleted.
                # Be aware of this line when debugging.
                return
        return self._data

    @data.setter
    def data(self, data):
        self._data = data
        uri = self._save_to_file(data, self.uri)
        self.uri = uri

    def remove(self, commit=True):
        """Performs hard-delete of dataset.

        Current session won't be committed if commit=False is provided.
        """
        # hard delete of data is the first priority
        with suppress(FileNotFoundError):
            os.remove(self._path)

        # soft delete associated entry
        update(self, store_until=utc_now())
        if commit:
            db.session.commit()

        # prompt python interpreter to remove data from memory
        with suppress(AttributeError):
            del self._data

        # and delete from session
        db.session.delete(self)
        if commit:
            db.session.commit()

    def _save_to_file(self, data, uri=None):
        """Saves data to a file identified by uri argument.

        If no uri is given, new unique file is created and new uri returned.
        Returned uri is unique so it can serve as a kind of a randomized id to
        prevent malicious software from iteration over all entries.
        """
        import base64
        from tempfile import NamedTemporaryFile

        os.makedirs(self.mutations_dir, exist_ok=True)

        encoded_name = str(
            base64.urlsafe_b64encode(bytes(self.name, 'utf-8')),
            'utf-8'
        )

        if uri:
            file_name = uri + '.db'
            path = os.path.join(self.mutations_dir, file_name)
            db_file = open(path, 'wb')
        else:
            db_file = NamedTemporaryFile(
                dir=self.mutations_dir,
                prefix=encoded_name,
                suffix='.db',
                delete=False
            )

        pickle.dump(data, db_file, protocol=4)

        uri_code = os.path.basename(db_file.name)[:-3]

        return uri_code

    @property
    def _path(self):
        from urllib.parse import unquote

        file_name = unquote(self.uri) + '.db'
        return os.path.join(self.mutations_dir, file_name)

    def _load_from_file(self):

        with open(self._path, 'rb') as f:
            data = pickle.load(f)
        return data

    @hybrid_property
    def is_expired(self):
        return self.life_expectancy < timedelta(0)

    @is_expired.expression
    def is_expired(self):
        return UsersMutationsDataset.store_until < utc_now()

    @hybrid_property
    def life_expectancy(self):
        """How much time is left for this dataset before removal."""
        return self.store_until - datetime.utcnow()

    @property
    def query_size(self):
        if self.query_count is None:
            new_lines = self.data.query.count('\n')
            return new_lines + 1 if new_lines else 0
        return self.query_count

    @property
    def mutations(self):
        mutations = []
        results = self.data.results
        for results in results.values():
            for result in results:
                mutations.append(result.mutation)
        return mutations

    @property
    def mutations_count(self):
        if self.results_count is None:
            return len(self.mutations)
        return self.results_count

    def get_mutation_details(self, protein, pos, alt):
        protein_results = self.data.results_by_refseq[protein.refseq]
        return protein_results[pos, alt].meta_user


class User(CMSModel):
    """Model for use with Flask-Login"""

    # http://www.rfc-editor.org/errata_search.php?rfc=3696&eid=1690
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), unique=True)
    access_level = db.Column(db.Integer, default=0)
    is_verified = db.Column(db.Boolean, default=False)
    verification_token = db.Column(db.Text, default=security.generate_random_token)
    pass_hash = db.Column(db.Text())

    # only datasets
    datasets = db.relationship(
        'UsersMutationsDataset',
        # beware: the expression will fail if put into quotation marks;
        # it is somehow related to late evaluation of hybrid attributes
        primaryjoin=and_(id == UsersMutationsDataset.owner_id, not_(UsersMutationsDataset.is_expired))
    )
    all_datasets = db.relationship('UsersMutationsDataset', backref='owner')

    def __init__(self, email, password, access_level=0):

        if not self.is_mail_correct(email):
            raise ValidationError('This email address seems to be incorrect')

        if not self.is_password_strong(password):
            raise ValidationError('The password is not strong enough')

        self.email = email
        self.access_level = access_level
        self.pass_hash = security.generate_secret_hash(password)

    @classmethod
    def user_loader(cls, user_id):
        return cls.query.get(int(user_id))

    def datasets_names_by_uri(self):
        return {d.uri: d.name for d in self.datasets}

    @staticmethod
    def is_mail_correct(email):

        if len(email) > 254:
            return False

        if '@' not in email:
            return False

        # both parts required
        try:
            local, domain = email.split('@')
        except ValueError:
            return False

        # no consecutive dots allowed in domain
        if '..' in domain:
            return False

        return True

    @staticmethod
    def is_password_strong(password):

        # count of different characters used
        if len(set(password)) <= 2:
            return False

        # overall length
        return len(password) >= 5

    @property
    def is_admin(self):
        return self.access_level == 10

    @property
    def is_moderator(self):
        return self.access_level >= 5

    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def authenticate(self, password):
        return self.is_verified and security.verify_secret(password, str(self.pass_hash))

    @cached_property
    def username(self):
        return self.email.split('@')[0].replace('.', ' ').title()

    def __repr__(self):
        return '<User {0} with id {1}>'.format(
            self.email,
            self.id
        )

    def get_id(self):
        return self.id


class Page(CMSModel):
    """Model representing a single CMS page"""

    columns = ('title', 'address', 'content')

    address = db.Column(
        db.String(256),
        unique=True,
        index=True,
        nullable=False,
        default='index'
    )
    title = db.Column(db.String(256))
    content = db.Column(db.Text())

    @validates('address')
    def validate_address(self, key, address):
        if '//' in address or address.endswith('/') or address.startswith('/'):
            raise ValidationError('Address cannot contain neither consecutive nor trailing slashes')
        pages = Page.query.filter_by(address=address).all()
        if pages:
            # ignore if it is the current page:
            if len(pages) == 1 and pages[0] == self:
                return address
            raise ValidationError('Page with address: "' + address + '" already exists.')
        return address

    @property
    def url(self):
        """A URL-like identifier ready to be used in HTML <a> tag"""
        return '/' + self.address + '/'

    def __repr__(self):
        return '<Page /{0} with id {1}>'.format(
            self.address,
            self.id
        )


class MenuEntry(CMSModel):
    """Base for tables defining links in menu"""

    position = db.Column(db.Float, default=5)
    menu_id = db.Column(db.Integer, db.ForeignKey('menu.id'))
    type = db.Column(db.String(32))

    parent_id = db.Column(db.Integer, db.ForeignKey('menuentry.id'))
    children = db.relationship(
        'MenuEntry',
        backref=db.backref('parent', remote_side='MenuEntry.id')
    )

    @property
    def title(self):
        """Name of the link"""
        raise NotImplementedError

    @property
    def url(self):
        """The href value of the link"""
        raise NotImplementedError

    __mapper_args__ = {
        'polymorphic_identity': 'entry',
        'polymorphic_on': type
    }


class PageMenuEntry(MenuEntry):

    @declared_attr
    def __tablename__(self):
        return 'page_menu_entry'

    id = db.Column(db.Integer, db.ForeignKey('menuentry.id'), primary_key=True)

    page_id = db.Column(db.Integer, db.ForeignKey('page.id'))
    page = db.relationship(
        'Page',
        backref=db.backref(
            'page_menu_entries',
            cascade='all, delete-orphan'
        )
    )

    title = association_proxy('page', 'title')

    @property
    def url(self):
        return url_for('ContentManagementSystem:page', address=self.page.address)

    __mapper_args__ = {
        'polymorphic_identity': 'page_entry',
        'inherit_condition': id == MenuEntry.id,
    }


class CustomMenuEntry(MenuEntry):

    @declared_attr
    def __tablename__(self):
        return 'custom_menu_entry'

    id = db.Column(db.Integer, db.ForeignKey('menuentry.id'), primary_key=True)

    title = db.Column(db.String(256))
    address = db.Column(db.String(256))

    @property
    def url(self):
        if self.address.startswith('/'):
            return url_for('ContentManagementSystem:page', address=self.address.rstrip('/'))
        else:
            return self.address

    __mapper_args__ = {
        'polymorphic_identity': 'custom_entry',
        'inherit_condition': id == MenuEntry.id,
    }


class Menu(CMSModel):
    """Model for groups of links used as menu"""
    id = db.Column(db.Integer, primary_key=True)

    # name of the menu
    name = db.Column(db.String(256), nullable=False, unique=True, index=True)

    # list of all entries (links) in this menu
    entries = db.relationship('MenuEntry')

    top_level_entries = db.relationship(
        'MenuEntry',
        primaryjoin=and_(id == MenuEntry.menu_id, MenuEntry.parent_id == None)
    )


class Setting(CMSModel):

    name = db.Column(db.String(256), nullable=False, unique=True, index=True)
    value = db.Column(db.Text())

    @property
    def int_value(self):
        return int(self.value)


class HelpEntry(CMSModel):

    name = db.Column(db.String(256), nullable=False, unique=True, index=True)
    content = db.Column(db.Text())


class TextEntry(CMSModel):

    name = db.Column(db.String(256), nullable=False, unique=True, index=True)
    content = db.Column(db.Text())
