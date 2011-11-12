#Encoding: UTF-8
from __future__ import unicode_literals

import sys
import re
import os
import stat
from textwrap import dedent

from pokedex.db import connect, tables, markdown
from lxml import etree
import termcolor
from diff_match_patch import diff_match_patch

from pokemwdb.wikicache import WikiCache
from pokemwdb import wikiparse

session = connect()
wiki = WikiCache('http://wiki.pokemon-online.eu/api.php?')

differ = diff_match_patch()
def make_diff(a, b):
    diff = differ.diff_main(a, b)
    differ.diff_cleanupSemantic(diff)
    return diff

def wiki_colorizer(color):
    def colorizer(text):
        return '<b style="color:%s;">%s</b>' % (color, text)
    return colorizer

def term_colorizer(color):
    def colorizer(text):
        return termcolor.colored(text, color)
    return colorizer

term_colorizers = term_colorizer('cyan'), term_colorizer('yellow')
wiki_colorizers = wiki_colorizer('#b2884a'), wiki_colorizer('#2795ae')

def print_diff(diff, file=None, colorizers=term_colorizers):
    if file is None:
        file = sys.stdout
    for side, text in diff:
        if side != 0:
            text = text.replace(' ', '·').replace('\n', '↵\n')
            text = colorizers[side == 1](text)
        file.write(text.encode('utf-8'))
    file.write('\n')

def print_wiki_diff(diff, file=None):
    def generator():
        def entity_encode(char):
            return '&#%s;' % ord(char.group())
        yield 0, ' '
        for side, text in diff:
            text = re.sub(r'[^a-zA-Z0-9 \n]', entity_encode, text)
            text = text.replace('\n', '\n<br>')
            yield side, text
    print_diff(generator(), file, wiki_colorizers)

def named_sections(node):
    if len(node) == 1 and isinstance(node, list):
        node = node[0]
    for subnode in node:
        if isinstance(subnode, wikiparse.Section) and subnode.header:
            yield subnode

class AllLinkExtension(markdown.PokedexLinkExtension):
    def object_url(self, category, obj):
        return obj.name

    def identifier_url(self, category, identifier):
        return identifier

all_link_extension = AllLinkExtension(session)

def normalize_article_name(name):
    if name.lower() in ('hp', 'pp'):
        return name.upper()
    name = name.replace('-', ' ')
    return name[0].upper() + name[1:]

def etree_to_wikitext(elem, num=0):
    text = elem.text or ''
    content = ''.join(etree_to_wikitext(e, num) for num, e in enumerate(elem))
    tail = elem.tail or ''
    if elem.tag == 'div':
        return text + content + tail
    elif elem.tag == 'p':
        if num > 0:
            text = '*' + text
        return text + content + '\n' + tail.strip()
    elif elem.tag == 'a':
        href = normalize_article_name(elem.attrib['href'])
        content = text + content
        if normalize_article_name(content) == href:
            return '[[%s]]' % content + tail
        else:
            return '[[%s|%s]]' % (href, content) + tail
    elif elem.tag == 'table':
        return ('{| class="wikitable"\n' +
                ''.join(etree_to_wikitext(e) for e in elem) +
                '|}\n')
    elif elem.tag == 'tr':
        return '|-\n' + content
    elif elem.tag == 'th':
        return '! ' + text + content.strip() + '\n'
    elif elem.tag == 'td':
        return '| ' + text + content.strip() + '\n'
    if elem.tag in ('thead', 'tbody'):
        return text.strip() + content + tail.strip()
    else:
        raise ValueError(elem.tag)
        return '<font color="red">%s</font>' % elem.tag + tail

def analyze_move_effect(section, move):
    """Analyze a MediaWiki section containing a move effect

    Returns either None if the section matches the database, or a diff.
    """
    tree = etree.fromstring('<div>' + move.effect.as_html(all_link_extension) + '</div>')
    wikitext = etree_to_wikitext(tree)
    wikitext = wikitext.replace('.  ', '. ')
    wikitext = '== Effect ==\n' + wikitext
    wikitext = wikitext.strip()
    section_text = unicode(section).strip()
    if wikitext == section_text:
        return None
    else:
        return make_diff(wikitext, section_text)

def analyze_move(article, move):
    for section in named_sections(article):
        header_name = section.header.name.strip()
        if header_name == 'Effect':
            return analyze_move_effect(section, move)
            break
    else:
        #analyze_move_effect(article, move)
        pass

def main():
    for move in session.query(tables.Move):
        wiki.mark_needed_pages([move.name + ' (move)'])
        wiki.mark_needed_pages([move.name])

    with open('diffs.cat', 'w') as catfile, open('diffs.wiki', 'w') as wikifile:
        try:
            catfile_fileno = catfile.fileno()
            os.fchmod(catfile_fileno, os.fstat(catfile_fileno).st_mode | stat.S_IEXEC)
            catfile.write('#! /bin/cat\n\n')
        except Exception:
            print "Warning: couldn't make output file executable"

        wikifile.write(dedent('''
        This __NOTOC__ page shows differences between {veekun} and the {powiki},
        (along with bugs in the difference script).

        Generated by pokemwdb/powiki.py from https://github.com/encukou/pokemwdb.

        * If the wiki is obviously more wrong, improve it
        * If veekun is obviously more wrong, get in touch (or use the talk page here)
        * Discussions towards better common style and wording guidelines welcome

        ''').format(
                veekun=wiki_colorizers[0]('veekun'),
                powiki=wiki_colorizers[1]('PO wiki'),
            ))

        header_texts = dict()
        for move in sorted(session.query(tables.Move), key=lambda m: m.name):
            wikitext = wiki.get(move.name + ' (move)', follow_redirect=True)
            if wikitext is None:
                wikitext = wiki.get(move.name, follow_redirect=True)
            article = wikiparse.wikiparse(wikitext)
            diff = analyze_move(article, move)

            if diff:
                term_header = termcolor.colored('%s' % move.name, 'blue')
                print term_header
                catfile.write(term_header + '\n')
                template = "={0}=\n''[[{0}|{1}]] vs. [http://veekun.com/dex/moves/{2} {3}]''\n"
                wikifile.write(template.format(
                        move.name,
                        wiki_colorizers[1]('wiki'),
                        move.name.lower().replace(' ', '%20'),
                        wiki_colorizers[0]('veekun'),
                    ).encode('utf-8'))
                print_diff(diff)
                print_diff(diff, catfile)
                wikifile.write('<div style="font-family:monospace;">')
                print_wiki_diff(diff, wikifile)
                wikifile.write('</div>\n')
                print
            else:
                pass
                #print colored(move.name, 'blue') + ': OK'

main()
