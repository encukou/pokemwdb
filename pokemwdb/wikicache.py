#! /usr/bin/env python
# Encoding: UTF-8

from __future__ import unicode_literals

import os
import urllib
import shutil
import time
import datetime

from sqlalchemy.ext.declarative import declarative_base, DeclarativeMeta
from sqlalchemy import Column, ForeignKey, MetaData, PrimaryKeyConstraint, Table, UniqueConstraint
from sqlalchemy.types import Unicode, Integer, Boolean, DateTime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import sqlalchemy.exc

try:
    import xml.etree.cElementTree as ElementTree
except ImportError:
    import xml.etree.ElementTree as ElementTree
import yaml

metadata = MetaData()
TableBase = declarative_base(metadata=metadata)

class Article(TableBase):
    __tablename__ = 'article'
    name = Column(Unicode, primary_key=True, nullable=False)
    contents = Column(Unicode, nullable=True)
    revision = Column(Integer, nullable=False)
    up_to_date = Column(Boolean, nullable=False)

class DBInfo(TableBase):
    __tablename__ = 'dbinfo'
    url_base = Column(Unicode, nullable=False, primary_key=True)
    last_revision = Column(Integer, nullable=True)
    last_update = Column(DateTime, nullable=True)

class WikiCache(object):
    """A local MediaWiki article cache

    The cache automatically synchronizes with the server when the WikiCache
    object is created (or when update() is called).

    No locking is implemented, so only one WikiCache may work with a given path
    at one time.

    init arguments:
    `url_base`:  The URL base for MW API requests, including trailing '?' (e.g.
            'http://en.wikipedia.org/w/api.php?'
    `path`:  Local filesystem path for the cache. If empty, the cache is
            initialized.

    Articles are retreived using __getitem__; if the requested article is not
    in the cache it's fetched from the server.
    """
    seconds_per_request = 5

    def __init__(self, url_base, db_path):
        db_path = os.path.abspath(db_path)
        engine = create_engine('sqlite:///' + db_path)
        sm = sessionmaker(bind=engine)
        self.session = sm()

        try:
            self.dbinfo = self.session.query(DBInfo).one()
        except sqlalchemy.exc.OperationalError:
            metadata.create_all(engine)
            self.dbinfo = DBInfo()
            self.dbinfo.url_base = url_base
            self.dbinfo.last_revision = None
            self.session.add(self.dbinfo)
            self.session.commit()
        else:
            assert self.dbinfo.url_base == url_base

        self.url_base = url_base

        hour_ago = datetime.datetime.today() - datetime.timedelta(hours=1)
        if not self.dbinfo.last_update or self.dbinfo.last_update < hour_ago:
            self.update()
        else:
            print 'DB cache: Skipping update: %s < %s' % (
                    self.dbinfo.last_update, hour_ago)

    def query(self):
        return self.session.query(Article)

    def article_object(self, pagename):
        try:
            return self.query().filter_by(name=pagename).one()
        except sqlalchemy.orm.exc.NoResultFound:
            obj = Article()
            obj.name = pagename
            obj.revision = 0
            obj.up_to_date = False
            return obj

    def apirequest_raw(self, **params):
        """Raw MW API request; returns filelike object"""

        now = lambda: datetime.datetime.today()
        try:
            next_time = self._next_request_time
        except AttributeError:
            pass
        else:
            while now() < next_time:
                print 'Sleeping...'
                time.sleep(1)

        try:
            enc = lambda s: unicode(s).encode('utf-8')
            params = [(enc(k), enc(v)) for k, v in params.items()]
            url = self.url_base + urllib.urlencode(params)
            print 'GET', url
            result = urllib.urlopen(url)
            return result
        finally:
            self._next_request_time = now() + datetime.timedelta(
                    seconds=self.seconds_per_request)

    def apirequest(self, **params):
        """MW API request; returns result dict"""
        params['format'] = 'yaml'
        return yaml.load(self.apirequest_raw(**params))

    def update(self):
        """Synchronize the cache with the server"""
        # Do this by checking the Recent Changes feed and removing changed
        # stuff from the cache; it'll be downloaded again if requested.
        def get_cont_changes(**kwargs):
            feed = self.apirequest(action='query', list='recentchanges',
                    rcprop='title|ids|sizes|flags|user', **kwargs)
            cont = feed['query-continue']['recentchanges']
            changes = feed['query']['recentchanges']
            return cont, changes
        cont, changes = get_cont_changes()
        last_revid = None
        if not self.dbinfo.last_revision:
            self.invalidate_cache()
            for change in changes:
                if change['revid']:
                    last_revid = int(changes[0]['revid'])
                    break
        else:
            purged = set()
            for x in range(5000):
                if not changes:
                    cont, changes = get_cont_changes(rclimit=100, **cont)
                if changes[0]['revid'] == self.dbinfo.last_revision:
                    break
                title = changes[0]['title']
                if title not in purged:
                    print u'Purging {0} (edit by {1})'.format(title,
                            changes[0]['user'])
                    self.invalidate_pages([title])
                    purged.add(title)
                del changes[0]
                if last_revid is None and changes[0]['revid']:
                    last_revid = int(changes[0]['revid'])
            else:
                print 'Too many recent changes; invalidating cache entirely'
                self.invalidate_cache()
        if last_revid:
            self.dbinfo.last_revision = last_revid
        self.dbinfo.last_update = datetime.datetime.today()
        self.session.commit()
        print 'Wiki cache is at revision', self.dbinfo.last_revision

    def invalidate_cache(self):
        """Invalidate the cache

        This marks all articles for re-downloading when requested.
        Note that articles with a current revision ID will not be re-downloaded
        entirely, only their metadata will be queried.
        (To clear the cache entirely, truncate the articles table.)
        """
        self.query().update({'up_to_date': False})
        self.session.commit()

    def invalidate_pages(self, pagenames):
        """Invalidate the specified articles from the cache

        They will be downloaded again if requested.

        This function, or invalidate_cache(), is always called when pages are
        invalidated, so subclasses may extend them to get notifications.
        """

        self.session.rollback()
        self.query().filter(Article.name.in_(pagenames)).update(
                {'up_to_date': False}, synchronize_session=False)
        self.session.commit()
        self.session.expire_all()

    def fetch_pages(self, pagenames):
        """Fetch the given pages from the server, if needed

        This function is called automatically when a page is requested, but
        it's more efficient (and lighter on the server) to call it before
        lots of pages are needed.
        """

        pages_by_name = {}

        pages_to_fetch = set()
        for pagename in pagenames:
            obj = self.article_object(pagename)
            if not obj.up_to_date:
                pages_to_fetch.add(obj)
                pages_by_name[pagename] = obj

        def chunks_with_name_limit(objs, n):
            result = []
            for obj in objs:
                if result and (len(result) > n or
                        sum(len(r.name) for r in result) +
                        len(obj.name) > 400):
                    yield result
                    result = []
                result.append(obj)
            if result:
                yield result

        new_pages = []

        for articles in chunks_with_name_limit(sorted(pages_to_fetch), 50):
            result = self.apirequest(action='query', info='lastrevid',
                    prop='revisions',
                    titles='|'.join(a.name for a in articles))
            assert 'normalized' not in result['query'], (
                    result['query']['normalized'])
            for page_info in result['query'].get('pages', []):
                page = pages_by_name[page_info['title']]
                if 'missing' in page_info:
                        page.missing = True
                        page.up_to_date = True
                        page.revision = 0
                        page.contents = None
                        self.session.add(page)
                else:
                    if page_info['revisions'][0]['revid'] != page.revision:
                        new_pages.append(page)
                    else:
                        page.up_to_date = True

        for articles in chunks_with_name_limit(sorted(new_pages), 10):
            dump = self.apirequest_raw(action='query',
                    export='1', exportnowrap='1',
                    titles='|'.join(a.name for a in articles))
            tree = ElementTree.parse(dump)
            for elem in tree.getroot():
                tag = elem.tag
                if tag.endswith('}siteinfo'):
                    continue
                elif tag.endswith('}page'):
                    revision, = (e for e in elem if e.tag.endswith('}revision'))
                    pagename, = (e for e in elem if e.tag.endswith('}title'))
                    text, = (e for e in revision if e.tag.endswith('}text'))
                    revid, = (e for e in revision if e.tag.endswith('}id'))
                    page = pages_by_name[pagename.text]
                    page.missing = False
                    page.up_to_date = True
                    page.revision = int(revid.text)
                    page.contents = text.text
                    self.session.add(page)
                else:
                    raise ValueError(tag)
        self.session.commit()

    def is_up_to_date(self, pagename):
        """Tests if the article is currently cached & up-to-date."""
        return self.article_object(pagename).up_to_date

    def __getitem__(self, pagename):
        self.fetch_pages([pagename])
        obj = self.article_object(pagename)
        assert obj.up_to_date
        if obj.contents is None:
            raise KeyError(pagename)
        else:
            return obj.contents
