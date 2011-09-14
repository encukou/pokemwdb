#! /usr/bin/env python
# Encoding: UTF-8

from __future__ import unicode_literals

import os
import sys
import textwrap
import itertools
import re

from pokemwdb.wikicache import WikiCache
from pokemwdb import wikiparse

def find_template(article, name, *args, **kwargs):
    return wikiparse.find(article, wikiparse.Template,
                    lambda t: t.string_name == name, *args, **kwargs)

safe_re = re.compile("^[\w\s'#]*$")

class Error(object):
    def __init__(self, *args, **kwargs):
        assert len(self.argnames) == len(args)
        self.args = []
        for i, arg in enumerate(args):
            if not safe_re.match(arg):
                arg = '<nowiki>%s</nowiki>' % arg
            if '=' in arg:
                arg = '%s=%s' % (i + 1, arg)
            self.args.append(arg)
        self.type = type
        self.pagename = kwargs.pop('pagename', '')
        self.contexts = kwargs.pop('pagename', [])

    def str_format(self):
        return (
                '{{User:En-Cu-Kou/T|' + self.template_name +
                '| %s | %s | ' % (self.pagename, ' '.join(self.contexts)) +
                ' | '.join(self.args) +
                ' }}'
            )

    @property
    def sort_key(self):
        return '?', self.pagename

class TemplateParameterError(Error):
    @property
    def sort_key(self):
        if self.args[0].endswith('notes'):
            argkey = self.args[0][:-5]
        else:
            argkey = self.args[0]
        if argkey in 'maxpp basepp'.split():
            argkey = 'pp'
        return 'tmpl', argkey, self.pagename

class WrongTemplateParameter(TemplateParameterError):
    argnames = 'arg right wrong'.split()
    template_name = 'diff'

class ExtraTemplateParameter(TemplateParameterError):
    argnames = 'arg value'.split()
    template_name = 'extr'

class MissingTemplateParameter(TemplateParameterError):
    argnames = 'arg value'.split()
    template_name = 'miss'

class DuplicateTemplateParameter(TemplateParameterError):
    argnames = 'arg value'.split()
    template_name = 'dupl'

class MissingArticle(Error):
    argnames = []
    template_name = 'nopage'

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
                errors.append(ExtraTemplateParameter(
                        param_name, unicode(t_param.value).strip()))
            else:
                param_value = unicode(t_param.value).strip()
                errors.extend(self._check_param(m_param, param_value))
                try:
                    unused_params.remove(param_name)
                except KeyError:
                    errors.append(DuplicateTemplateParameter(param_name, param_value))
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
                yield WrongTemplateParameter(m_param.name, expected_shown, t_value)
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
                    yield ExtraTemplateParameter(m_param.name, t_value)
                elif t_value is None:
                    yield MissingTemplateParameter(m_param.name, expected_shown)
                else:
                    yield WrongTemplateParameter(m_param.name, expected_shown, t_value)

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

    def find_template(self, name, section=None, *args, **kwargs):
        if not section:
            section = self.article
        return find_template(section, name, *args, **kwargs)

    def __call__(self):
        msg = '[[%s]]...\r' % self.article_name
        sys.stdout.write(msg + '\r')
        sys.stdout.flush()
        def make_mine(error):
            error.pagename = self.article_name
            error.contexts.append(self.name)
        if self.article is None:
            error = MissingArticle(self.article_name)
            print error
            make_mine(error)
            yield error
        else:
            for error in self.check():
                make_mine(error)
                yield error
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

        def _run_one(checker, number):
            new_errors = list(checker())
            for error in new_errors:
                error.checker_number = number
                print error.str_format()
            errors.extend(new_errors)

        def _run():
            print 'Running %s checkers with %s needed articles' % (
                    len(checkers), len(needed_articles))
            self.cache.fetch_pages(needed_articles)
            for checker, number in checkers:
                _run_one(checker, number)
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
                checkers.append((checker, i))
            else:
                _run_one(checker, i)
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
            {{User:En-Cu-Kou/T|head|||

                | site = %s
                | wiki revision = %s (%s)
                |

            This report shows:
            * Errors and ommissions in the checking script
            * Errors in the database
            * Errors on the wiki
            It's up to humans to decide which is which.
            }}

            ''' % (base_url, self.cache.dbinfo.last_revision,
                    self.cache.dbinfo.last_update)))
            ignored = []
            for error in sorted(errors, key=lambda e: (e.sort_key, e.checker_number, e.args)):
                str_formatted = error.str_format()
                if str_formatted.replace('\n', r'\n') in expected:
                    ignored.append(str_formatted)
                else:
                    error_file.write('* ')
                    error_file.write(str_formatted.encode('utf-8'))
                    error_file.write('\n')
            error_file.write('\n')
            error_file.write('{{User:En-Cu-Kou/T|total||| num = %s }}\n' %
                    (len(errors) - len(ignored)))
            if ignored:
                error_file.write('{{User:En-Cu-Kou/T|ignored||| num = %s }}\n' %
                        len(ignored))

        print '%s mismatches written to file' % (len(errors) - len(ignored))
        print '%s expected mismatches ignored' % len(ignored)

    def error(self, message):
        self.errors.append(message)
        print message
