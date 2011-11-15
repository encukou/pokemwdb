import os
import datetime
import urllib
import time
import collections
import functools
import re

from sqlalchemy.ext.declarative import declarative_base, DeclarativeMeta
from sqlalchemy import Column, ForeignKey, MetaData, PrimaryKeyConstraint, Table, UniqueConstraint
from sqlalchemy.types import Unicode, Integer, Boolean, DateTime, PickleType
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, relationship
import sqlalchemy.exc

try:
    import xml.etree.cElementTree as ElementTree
except ImportError:
    import xml.etree.ElementTree as ElementTree
import yaml

metadata = MetaData()
TableBase = declarative_base(metadata=metadata)

class Wiki(TableBase):
    __tablename__ = 'wikis'
    url_base = Column(Unicode, nullable=False, primary_key=True, info=dict(
        doc="MediaWiki API URL base, including the '?', e.g. 'http://en.wikipedia.org/w/api.php?'"))
    synced = Column(Boolean, nullable=True, info=dict(
        doc="If True, the cache is synced to the server."))
    sync_timestamp = Column(PickleType, nullable=False, info=dict(
        doc="timestamp for the next sync. (If None, cache will be invalidated.)"))
    last_update = Column(DateTime, nullable=True, info=dict(
        doc="Time of the last update."))

class Page(TableBase):
    __tablename__ = 'articles'
    wiki_id = Column(Unicode, ForeignKey('wikis.url_base'), primary_key=True, nullable=False, info=dict(
        doc="ID of the Wiki this artile is part of"))
    title = Column(Unicode, primary_key=True, nullable=False, info=dict(
        doc="Title of the article"))
    contents = Column(Unicode, nullable=True, info=dict(
        doc="Textual contents of the article. NULL if there's no such article."))
    revision = Column(Integer, nullable=False, info=dict(
        doc="RevID of the article that `contents` reflect."))
    up_to_date = Column(Boolean, nullable=False, info=dict(
        doc="True if `revision` is provably the last revision of this article as of wiki.sync_timestamp"))

Page.wiki = relationship(Wiki)

import collections
import functools

def lru_cache(maxsize=100):
    '''Least-recently-used cache decorator.

    Arguments to the cached function must be hashable.
    Cache performance statistics stored in f.hits and f.misses.
    http://en.wikipedia.org/wiki/Cache_algorithms#Least_Recently_Used

    '''
    def decorating_function(user_function):
        cache = collections.OrderedDict()    # order: least recent to most recent

        @functools.wraps(user_function)
        def wrapper(*args, **kwds):
            key = args
            if kwds:
                key += tuple(sorted(kwds.items()))
            try:
                result = cache.pop(key)
                wrapper.hits += 1
            except KeyError:
                result = user_function(*args, **kwds)
                wrapper.misses += 1
                if len(cache) >= maxsize:
                    cache.popitem(0)    # purge least recently used cache entry
            cache[key] = result         # record recent use of this key
            return result
        wrapper.hits = wrapper.misses = 0
        wrapper.cache = cache
        return wrapper
    return decorating_function

class WikiCache(object):
    """A cache of a MediaWiki

    :param url_base: Base URL of the MediaWiki API, including a '?',
        e.g. 'http://en.wikipedia.org/w/api.php?'
    :param db_path: Path to a SQLite file holding the cache, or SQLAlchemy
        database URL. If not given, a file next to the wikicache module will be
        used.
    :param update: If true (default), the cache will update() itself to reflect
        the current state of the remote wiki, if it wasn't updated in a while.
    :param sync: If true (default), the cache will unconditionally sync itself
        to the remote wiki.
    :param limit: The cache will not make more than one request each `limit`
        seconds.
    """
    def __init__(self, url_base, db_url=None, update=True, sync=False, limit=5):
        if db_url is None:
            db_url = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                'caches.sqlite')

        if '://' not in db_url:
            db_url = os.path.abspath(db_url)
            db_url = 'sqlite:///' + db_url

        engine = create_engine(db_url)
        sm = sessionmaker(bind=engine)
        self.session = sm()

        self.url_base = url_base
        self.limit = limit
        self._needed_metadata = set()
        self._needed_pages = set()

        self._page_object = lru_cache(100)(self._page_object)

        query = self.session.query(Wiki).filter_by(url_base=url_base)
        try:
            self.wiki = query.one()
        except (sqlalchemy.exc.OperationalError, sqlalchemy.orm.exc.NoResultFound):
            metadata.create_all(engine)
            self.wiki = Wiki()
            self.wiki.url_base = url_base
            self.wiki.sync_timestamp = None
            self.session.add(self.wiki)
            self.update()
        else:
            if sync:
                self.update()
            elif update:
                hour_ago = datetime.datetime.today() - datetime.timedelta(minutes=10)
                if not self.wiki.last_update or self.wiki.last_update < hour_ago:
                    self.update()
                else:
                    self.log('Skipping update')

    def log(self, string):
        print string

    def _page_query(self):
        return self.session.query(Page)

    def _page_object(self, title):
        """Get an object for the page 'title', *w/o* adding it to the session
        """
        obj = self._page_query().get((self.url_base, title))
        if obj:
            return obj
        else:
            obj = Page()
            obj.wiki = self.wiki
            obj.title = title
            obj.revision = 0
            obj.up_to_date = False
            return obj

    @property
    def _sleep_seconds(self):
        """Number of seconds to sleep until next request"""
        now = lambda: datetime.datetime.today()
        try:
            next_time = self._next_request_time
        except AttributeError:
            return 0
        else:
            sleep_seconds = (next_time - now()).total_seconds()
            if sleep_seconds > 0:
                return sleep_seconds
            else:
                return 0

    def _apirequest_raw(self, **params):
        """Raw MW API request; returns filelike object"""

        sleep_seconds = self._sleep_seconds
        if sleep_seconds > 0:
            self.log('Sleeping %ss' % sleep_seconds)
            time.sleep(sleep_seconds)

        try:
            enc = lambda s: unicode(s).encode('utf-8')
            params = [(enc(k), enc(v)) for k, v in params.items()]
            url = self.url_base + urllib.urlencode(params)
            self.log('GET %s' % url)
            result = urllib.urlopen(url)
            return result
        finally:
            self._next_request_time = (datetime.datetime.today() +
                    datetime.timedelta(seconds=self.limit))

    def apirequest(self, **params):
        """MW API request; returns result dict"""
        params['format'] = 'yaml'
        return yaml.load(self._apirequest_raw(**params))

    def update(self):
        """Fetch a batch of page changes from the server"""
        if self.wiki.sync_timestamp is None:
            feed = self.apirequest(action='query', list='recentchanges',
                    rcprop='timestamp', rclimit=1)
            last_change = feed['query']['recentchanges'][0]
            self.wiki.sync_timestamp = last_change['timestamp']
            self.invalidate_cache()
            self.synced = True
        else:
            feed = self.apirequest(action='query', list='recentchanges',
                    rcprop='title|user|timestamp', rclimit=100,
                    rcend=self.wiki.sync_timestamp
                )
            sync_timestamp = feed['query']['recentchanges'][0]['timestamp']
            while feed:
                invalidated = set()
                changes = feed['query']['recentchanges']
                for change in changes:
                    title = change['title']
                    if title not in invalidated:
                        self.log(u'Change to {0} by {1}'.format(title,
                                change['user']))
                        obj = self._page_object(title)
                        obj.up_to_date = False
                        invalidated.add(title)
                try:
                    feed = self.apirequest(action='query', list='recentchanges',
                            rcprop='title|user|timestamp', rclimit=100,
                            rcend=self.wiki.sync_timestamp,
                            **feed['query-continue']['recentchanges']
                        )
                except KeyError:
                    feed = None
                    self.wiki.sync_timestamp = sync_timestamp
                    self.wiki.synced = True
                else:
                    self.wiki.synced = False
        self.wiki.last_update = datetime.datetime.today()
        self.session.commit()

    def invalidate_cache(self):
        """Invalidate the entire cache

        This marks all articles for re-downloading when requested.
        Note that articles with a current revision ID will not be re-downloaded
        entirely, only their metadata will be queried.
        (To clear the cache entirely, truncate the articles table.)
        """
        self._page_query().update({'up_to_date': False})
        self.session.commit()

    def mark_needed_pages(self, titles):
        """Inform the cache that pages with `titles` will be needed soon

        Calling this (even multiple times) before requesting pages can speed
        things up and ease the load on the server.
        """
        needed_titles = set(titles)
        needed_titles.difference_update(t for t, in self._page_object.cache)
        if len(needed_titles) > 2:
            objects = self._page_query().filter(Page.title.in_(titles)).all()
        else:
            objects = (self._page_object(t) for t in titles)
        for obj in objects:
            self.session.add(obj)
            if not obj.up_to_date and obj not in self._needed_pages:
                self._needed_metadata.add(obj)
        self.fetch_pages(force=False)

    def _get_chunk(self, source, limit=20, title_limit=700):
        """Get some pages from a set

        Limit by number of pages (limit) and total length of titles
        (title_limit).
        """
        chunk = set()
        length = 0
        source = set(source)
        while source:
            item = source.pop()
            if len(chunk) >= limit or length + len(item.title) > title_limit:
                return chunk, True
            else:
                chunk.add(item)
                length += len(item.title)
        return chunk, False

    def _fetch_metadata(self, force=True):
        """Fetch needed page metadata from the server.

        :param force: If true (default), all needed metadata will be fetched.
            Otherwise, some can be left over.
        """
        while True:
            chunk, needed = self._get_chunk(self._needed_metadata, limit=50)
            if not chunk:
                return
            if not needed and force:
                # Need to get pages anyway, so include some outdated ones
                query = self.session.query(Page)
                query = query.filter(Page.wiki == self.wiki)
                query = query.filter(Page.up_to_date == False)
                wanted = list(self._needed_metadata) + query[:50]
                chunk, needed = self._get_chunk(wanted, limit=50)
            if needed or force:
                result = self.apirequest(action='query',
                        info='lastrevid', prop='revisions', # XXX: will be unnecessary in modern MW
                        titles='|'.join(p.title for p in chunk))
                assert 'normalized' not in result['query'], (
                        result['query']['normalized'])  # XXX: normalization
                pages_by_title = dict((p.title, p) for p in chunk)
                for page_info in result['query'].get('pages', []):
                    page = pages_by_title[page_info['title']]
                    self.session.add(page)
                    if 'missing' in page_info:
                            page.up_to_date = True
                            page.revision = 0
                            page.contents = None
                    else:
                        revid = page_info['revisions'][0]['revid']
                        # revid = page_info['lastrevid']  # for the modern MW
                        if revid != page.revision:
                            self._needed_pages.add(page)
                        else:
                            page.up_to_date = True
                self._needed_metadata -= chunk
                self.session.commit()
            else:
                return

    def fetch_pages(self, titles=(), force=True):
        """Fetch needed pages from the server.

        :param force: If true (default), pages will be fetched.
            Otherwise, the pages might be fetched, or may be left for later.
        """
        if titles:
            self.mark_needed_pages(titles)
        self._fetch_metadata(force=force)
        while True:
            chunk, needed = self._get_chunk(self._needed_pages)
            if not chunk:
                return
            elif needed or force:
                pages_by_title = dict((p.title, p) for p in chunk)
                dump = self._apirequest_raw(action='query',
                        export='1', exportnowrap='1',
                        titles='|'.join(p.title for p in chunk))
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
                        page = pages_by_title[pagename.text]
                        page.up_to_date = True
                        page.revision = int(revid.text)
                        page.contents = text.text
                        self.session.add(page)
                    else:
                        print elem, list(elem)
                        raise ValueError(tag)
                self._needed_pages -= chunk
                self.session.commit()
            else:
                return

    def is_up_to_date(self, title):
        """Test if the article is currently cached & up-to-date."""
        return self._page_object(title).up_to_date

    def __getitem__(self, title):
        """Return the content of a page, if it exists, or raise KeyError
        """
        text = self.get(title)
        if text is None:
            raise KeyError(title)
        else:
            return text

    def get(self, title, default=None, follow_redirect=False):
        if follow_redirect:
            try:
                return self[self.redirect_target(title)]
            except KeyError:
                pass

        if not title:
            return default
        obj = self._page_object(title)
        if not obj.up_to_date:
            self.fetch_pages([title])
            assert obj.up_to_date
        if obj.contents is None:
            return default
        else:
            return obj.contents

    def redirect_target(self, title):
        """Get a target redirect

        If the page at `title` is a redirect, return what it's pointing to,
        otherwise return `title` unchanged
        """
        self.fetch_pages([title])
        content = self.get(title)
        if content:
            redirect_match = re.match(r'#REDIRECT +\[\[([^\]]+)\]\]',
                    content)
            if redirect_match:
                return redirect_match.group(1)
        return title

    def get_cached_content(self, title):
        """Return cached, possibly old or empty, content of a page
        """
        obj = self._page_object(title)
        if obj.contents is None:
            return u''
        else:
            return obj.contents
