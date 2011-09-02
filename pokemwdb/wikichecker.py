#! /usr/bin/env python
# Encoding: UTF-8

from __future__ import unicode_literals

import os
import sys
import textwrap
import itertools

from pokemwdb.wikicache import WikiCache
from pokemwdb import wikiparse

def find_template(article, name, *args, **kwargs):
    return wikiparse.find(article, wikiparse.Template,
                    lambda t: t.string_name == name, *args, **kwargs)

class _TTMeta(type):
    def __new__(cls, name, bases, attrs):
        if name != 'TemplateTemplate':
            newattrs = dict(params=attrs.pop('params', {}))
            for param_name, param in newattrs[b'params'].items():
                if not hasattr(param, 'name'):
                    param.name = param_name
            for attrname, attrvalue in attrs.iteritems():
                if (attrname.startswith('_') or not callable(attrvalue)):
                    newattrs[attrname] = attrvalue
                else:
                    try:
                        newattrs['params'][attrvalue.name] = attrvalue
                    except AttributeError:
                        attrvalue.name = attrname
                        newattrs['params'][attrname] = attrvalue
            attrs = newattrs

        return super(_TTMeta, cls).__new__(cls, name, bases, attrs)

class TemplateTemplate(object):
    __metaclass__ = _TTMeta

    def __init__(self, checker, template, **attrs):
        for attr, value in attrs.items():
            setattr(self, attr, value)
        self.checker = checker
        self.template = template
        self.name = template.string_name

        self._init()

    def _init(self):
        pass

    def check(self):
        errors = []
        unused_params = set(self.params)
        number = 1
        for t_param in self.template.params:
            if t_param.name:
                param_name = unicode(t_param.name).strip()
            else:
                param_name = unicode(number)
                number += 1
            try:
                m_param = self.params[param_name]
            except KeyError:
                errors.append('Unknown template parameter: %s=%s' % (
                        param_name, unicode(t_param.value).strip()))
            else:
                param_value = unicode(t_param.value).strip()
                errors.extend(self._check_param(m_param, param_value))
                try:
                    unused_params.remove(param_name)
                except KeyError:
                    errors.append('Duplicate template parameter: %s' %
                            (param_name))
        for param in unused_params:
            errors.extend(self._check_param(self.params[param], None))
        return errors

    def _check_param(self, m_param, t_value):
        checker = getattr(m_param, 'checker', None)
        if checker:
            for error in checker(self, None, t_value):
                yield error
        else:
            expected = m_param(self, None)
            if isinstance(expected, tuple):
                expected_shown = expected
            else:
                expected_shown = (expected, )
            expected_shown = ('missing' if e is None else e for e in expected_shown)
            expected_shown = (unicode(e).strip() for e in expected_shown)
            expected_shown = (e if e else 'empty' for e in expected_shown)
            expected_shown = ' or '.join(expected_shown)

            normalizer = getattr(m_param, 'normalizer', lambda x: x)
            try:
                t_value = normalizer(t_value)
            except Exception:
                msg = "Bad value for template parameter %s: %s (should be %s)"
                yield msg % (m_param.name, expected_shown, t_value)
                return

            if isinstance(expected, tuple):
                if t_value is None:
                    match = None in expected
                else:
                    match = unicode(t_value) in (unicode(x) for x in expected)
            else:
                match = unicode(expected) == unicode(t_value)

            if not match:
                if expected is None:
                    yield "Unexpected template parameter: %s=%s" % (
                                m_param.name, t_value)
                elif t_value is None:
                    msg = "Missing template parameter: %s (should be %s)"
                    yield msg % (m_param.name, expected_shown)
                else:
                    msg = "In template parameter %s: Expected '%s', got '%s'"
                    yield msg % (m_param.name, expected_shown, t_value)

    def dbget_id(self, table, id):
        return self.checker.checker.session.query(table).get(id)

    def dbget(self, table, identifier):
        return self.checker.checker.session.query(table
                ).filter_by(identifier=identifier).one()

def normalize(normalizer):
    def wrapper(checker):
        checker.normalizer = normalizer
        return checker
    return wrapper

def missing_on(exception, default=None):
    def wrapper(checker):
        def wrapped(self, v):
            try:
                return checker(self, v)
            except exception:
                return default
        return wrapped
    return wrapper

def param_name(name):
    def wrapper(checker):
        checker.name = name
        return checker
    return wrapper

def ignored():
    def dummy(self, v):
        return None
    dummy.checker = lambda self, v, value: []
    return dummy

def checker(checker):
    checker.checker = checker
    return checker

class ArticleChecker(object):
    def __init__(self, checker, article_name):
        self.checker = checker
        self.article_name = article_name
        self.needed_articles = [self.article_name]

    @property
    def article(self):
        try:
            return self._article
        except AttributeError:
            try:
                article = self.checker.cache[self.article_name]
            except KeyError:
                self._article = None
            else:
                self._article = wikiparse.wikiparse(article)
            return self._article

    def error(self, err):
        self.checker.error('[[%s]] %s: %s' % (self.article_name,
                self.name, err))

    def find_template(self, name, section=None, *args, **kwargs):
        if not section:
            section = self.article
        return find_template(section, name, *args, **kwargs)

    def __call__(self):
        msg = '[[%s]]...\r' % self.article_name
        sys.stdout.write(msg + '\r')
        sys.stdout.flush()
        if self.article is None:
            yield '[[%s]]: article missing' % (self.article_name)
        else:
            for error in self.check():
                yield '[[%s]] \1%s\2: \3%s\4' % (self.article_name, self.name, error)
        sys.stdout.write(' ' * len(msg) + '\r')
        sys.stdout.flush()

class WikiChecker(object):
    base_url = 'http://bulbapedia.bulbagarden.net/w/api.php?'
    path = 'data/bp'

    def __init__(self):
        self.cache = WikiCache(self.base_url, os.path.join(self.path, 'cache'))

    def check(self):
        errors = []
        checkers = []
        needed_articles = []
        needed_articles_set = set()

        def _run_one(checker):
            new_errors = list(checker())
            for error in new_errors:
                print error
            errors.extend(new_errors)

        def _run():
            print 'Running %s checkers with %s needed articles' % (
                    len(checkers), len(needed_articles))
            self.cache.fetch_pages(needed_articles)
            for checker in checkers:
                _run_one(checker)
            del checkers[:]
            del needed_articles[:]

        for checker, i in itertools.izip(self.checkers(), xrange(999999)):
            needs_articles = False
            for article in getattr(checker, 'needed_articles', []):
                if not self.cache.is_up_to_date(article):
                    needs_articles = True
                    if article not in needed_articles_set:
                        needed_articles_set.add(article)
                        needed_articles.append(article)
            if needs_articles:
                checkers.append(checker)
            else:
                _run_one(checker)
            if len(needed_articles) >= 20 or len(checkers) > 50:
                _run()
        _run()
        print '%s mismatches found' % len(errors)

        try:
            expected_file = open(os.path.join(self.path, 'expected'))
        except IOError:
            expected = set()
        else:
            expected = set(s.decode('utf-8').strip() for s in
                    expected_file.readlines())

        with open(os.path.join(self.path, 'mismatches'), 'w') as error_file:
            base_url, sep, b = self.base_url.rpartition('api.php?')
            if b:
                base_url = self.base_url
            error_file.write(textwrap.dedent('''
                Checking report for %s
                Wiki revision %s (%s)

            This report shows:
            * Errors and ommissions in the checking script
            * Errors in the database
            * Errors on the wiki
            It's up to humans to decide which is which.

            ''' % (base_url, self.cache.dbinfo.last_revision,
                    self.cache.dbinfo.last_update)))
            ignored = []
            for error in sorted(errors):
                wiki_error = (error
                        .replace('\1', '<tt>')
                        .replace('\2', '</tt>')
                        .replace('\3', '<nowiki>')
                        .replace('\4', '</nowiki>')
                    )
                for c in '\1\2\3\4':
                    error = error.replace(c, '')
                if error.strip() in expected:
                    ignored.append(error)
                else:
                    error_file.write('* ')
                    error_file.write(wiki_error.encode('utf-8'))
                    error_file.write('\n')
            error_file.write('\n')
            error_file.write('    %s mismatches found\n' %
                    (len(errors) - len(ignored)))
            if ignored:
                error_file.write('    %s expected mismatches ignored\n' %
                        len(ignored))

        print '%s mismatches written to file' % (len(errors) - len(ignored))
        print '%s expected mismatches ignored' % len(ignored)

    def error(self, message):
        self.errors.append(message)
        print message
