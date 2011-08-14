#! /usr/bin/env python
# Encoding: UTF-8
from __future__ import unicode_literals

import re
import textwrap
import collections

from pokemwdb.wikicache import WikiCache

### Helpers

def re_partition(re, string):
    try:
        pre, sep, post = re.split(string, 1)
        return pre, sep, post
    except ValueError:
        return string, '', ''

def make_wikiname(string):
    string = unicode(string).strip()
    string = string[0].upper() + string[1:]
    return string

### Visitors

class Visitor(object):
    def visit(self, node):
        self.dispatch(node)
        node.visit(self.visit)

    def dispatch(self, node):
        self.visit_any(node)
        try:
            func = getattr(self, 'visit_' + type(node).__name__)
        except AttributeError:
            pass
        else:
            func(node)

    def visit_any(self, node):
        pass

class BreadthFirstVisitor(Visitor):
    def visit(self, node):
        nodes_left = collections.deque([node])
        while nodes_left:
            node = nodes_left.popleft()
            self.dispatch(node)
            node.visit(nodes_left.append)

def find(node, type=None, predicate=lambda node: True, find_all=False):
    class Find(BreadthFirstVisitor):
        def __init__(self):
            if type:
                self.predicate = lambda node: (isinstance(node, type) and
                        predicate(node))
            else:
                self.predicate = predicate
            self.results = []

        def visit_any(self, node):
            if self.predicate(node):
                self.results.append(node)
                if not find_all:
                    self.visit = lambda node: None

    find = Find()
    find.visit(node)
    if find_all:
        return find.results
    else:
        try:
            return find.results[0]
        except IndexError:
            return None

### Nodes

class Content(list):
    def __unicode__(self):
        return ''.join(unicode(x) for x in self)

    def visit(self, visitor):
        for item in self:
            visitor(item)

    def dump(self, indent_level=0):
        print '  ' * indent_level + ':'
        for item in self:
            item.dump(indent_level + 1)

class Section(Content):
    def dump(self, indent_level=0):
        print '  ' * indent_level + '~'
        for item in self:
            item.dump(indent_level + 1)

class String(unicode):
    def visit(self, visitor):
        pass

    def dump(self, indent_level=0):
        print '  ' * indent_level + "'" + self.replace('\n', r'\n') + "'"

class Template(object):
    def __init__(self, name, params):
        self.name = name
        self.params = params

    @property
    def string_name(self):
        return make_wikiname(unicode(self.name))

    @property
    def normalized_params(self):
        number = 1
        normalized = {}
        for param in self.params:
            if param.name:
                normalized[unicode(param.name).strip()] = unicode(param.value
                        ).strip()
            else:
                normalized[unicode(number)] = unicode(param.value).strip()
                number += 1
        return normalized

    def __unicode__(self):
        return "{{" + unicode(self.name) + ' | ' + ' | '.join(unicode(x) for x in self.params) + "}}"

    def visit(self, visitor):
        for param in self.params:
            visitor(param)

    def dump(self, indent_level=0):
        print '  ' * indent_level + '{{'
        self.name.dump(indent_level + 1)
        for param in self.params:
            print '  ' * indent_level + '|'
            param.dump(indent_level + 1)

class TemplateArgument(object):
    def __init__(self, name, value):
        self.name = name
        self.value = value

    def __unicode__(self):
        if self.name:
            return unicode(self.name) + '=' + unicode(self.value)
        else:
            return unicode(self.value)

    def visit(self, visitor):
        if self.name:
            visitor(self.name)
        visitor(self.value)

    def dump(self, indent_level=0):
        if self.name:
            self.name.dump(indent_level)
            print '  ' * (indent_level - 1) + '='
        self.value.dump(indent_level)

class Header(object):
    def __init__(self, level, name):
        self.name = name
        self.level = level

    def __unicode__(self):
        return '=' * self.level + unicode(self.name) + '=' * self.level

    def visit(self, visitor):
        visitor(self.name)

    def dump(self, indent_level=0):
        print '  ' * indent_level + '=' * self.level
        self.name.dump(indent_level + 1)

### Parsing

token_re = re.compile(r'({{|\||}}|=)')

def wikiparse(string):
    tokens = token_re.split(string)
    tree = parse_templates(tokens)
    #tree = expand_templates(tree)
    #tree = parse_tables(tree)
    tree = do_structure(tree)
    # Inline markup
    # Internal links
    # External links
    return tree

def parse_templates(tokens, end=[]):
    contents = Content()
    while tokens:
        if tokens[0] == '{{':
            del tokens[0]
            contents.append(parse_template(tokens))
        elif tokens[0] in end:
            return contents
        else:
            if contents and isinstance(contents[-1], String):
                contents[-1] = String(contents[-1] + tokens[0])
            else:
                contents.append(String(tokens[0]))
            del tokens[0]
    return contents

def parse_template(tokens):
    # tokens is guaranteed to have '}}' in it
    name = parse_templates(tokens, end=['}}', '|'])
    params = parse_template_params(tokens)
    if params is None:
        # Oops, it wasn't a template
        name.insert(0, String('{{'))
        name.extend(parse_templates(tokens))
        return name
    else:
        return Template(name, params)

def parse_template_params(tokens):
    args = []
    tokens_saved = list(tokens)
    while tokens:
        if tokens[0] == '}}':
            del tokens[0]
            return args
        elif tokens[0] == '|':
            del tokens[0]
            args.append(parse_template_param(tokens))
        else:
            raise ValueError(tokens[0], tokens)
    # No end of template! Backtrace.
    print 'WIKITEXT PARSE WARNING: Bad end of template!', tokens_saved[:50]
    tokens[:] = tokens_saved
    return None

def parse_template_param(tokens):
    part1 = parse_templates(tokens, end=['}}', '|', '='])
    if tokens and tokens[0] == '=':
        del tokens[0]
        part2 = parse_templates(tokens, end=['}}', '|'])
        return TemplateArgument(part1, part2)
    else:
        return TemplateArgument(None, part1)

heading_re = re.compile(r'^(=+)(.+)\1(\s*)$', re.MULTILINE)

def do_structure(tree):
    replaced = Content()
    # only do headings at the top level, not in templates etc.
    for item in tree:
        if isinstance(item, String):
            replaced += parse_headings(item)
        else:
            replaced.append(item)
    root = Content()
    first_section = Section()
    section_stack = [root, first_section]
    root.append(first_section)
    for item in replaced:
        if isinstance(item, Header):
            while item.level < len(section_stack):
                section_stack.pop()
            while item.level >= len(section_stack):
                section_stack.append(Section())
                section_stack[-2].append(section_stack[-1])
        section_stack[-1].append(item)
    return root

def parse_headings(string):
    split = heading_re.split(string)
    result = Content([String(split[0])])
    del split[0]
    while split:
        result.append(Header(len(split[0]), String(split[1])))
        result.append(String(split[2] + split[3]))
        del split[:4]
    return result
