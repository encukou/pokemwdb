#Encoding: UTF-8
from __future__ import unicode_literals

import sys
import re
import os
import stat
from textwrap import dedent
from collections import defaultdict, OrderedDict

from sqlalchemy.orm import joinedload

from pokedex.db import connect, tables, markdown, util
from lxml import etree
import termcolor
from diff_match_patch import diff_match_patch

from pokemwdb.wikicache import WikiCache
from pokemwdb import wikiparse


#stdout = sys.stdout
#import traceback
#class F(object):
    #def write(self, s):
        #stdout.write('---\n')
        #stdout.write(s)
        #stdout.write(''.join(traceback.format_stack()))
        #stdout.write('---\n\n')
#sys.stdout = F()
#session = connect(engine_args=dict(echo=True))

session = connect() #engine_args=dict(echo=True))
wiki = WikiCache('http://wiki.pokemon-online.eu/api.php?')

version_groups = session.query(tables.VersionGroup).order_by(
        tables.VersionGroup.generation_id,
        tables.VersionGroup.id,
    ).all()

differ = diff_match_patch()
def make_diff(a, b):
    diff = differ.diff_main(a, b)
    differ.diff_cleanupSemantic(diff)
    return diff

def wiki_colorizer(light, dark, name):
    def colorizer(text):
        template = '<b style="background-color:#{light};outline:1px solid #{dark}" class="diff-{name}">{text}</b>'
        return template.format(light=light, dark=dark, text=text, name=name)
    return colorizer

def term_colorizer(color):
    def colorizer(text):
        return termcolor.colored(text, color)
    return colorizer

term_colorizers = term_colorizer('cyan'), term_colorizer('yellow')
wiki_colorizers = (
        wiki_colorizer('9de6ec', '2795ae', 'wiki'),
        wiki_colorizer('d7b078', 'b2884a', 'vee'),
    )

def print_diff(diff, file=None, colorizers=term_colorizers):
    if file is None:
        file = sys.stdout
    for side, text in diff:
        if side != 0:
            text = text.replace('\n', '↵\n')
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
            yield side, text
    print_diff(generator(), file, wiki_colorizers)

def named_sections(node):
    if len(node) == 1 and isinstance(node, list):
        node = node[0]
    for subnode in node:
        if isinstance(subnode, wikiparse.Section) and subnode.header:
            yield subnode

class LinkExtension(markdown.PokedexLinkExtension):
    def normalized_wiki_title(self, title, category):
        return normalize_article_name(self.correct_wiki_title(title, category))

    def correct_wiki_title(self, title, category):
        title = {
                # Exceptions
                'special-attack': 'Special Attack',
                'special-defense': 'Special Defense',
            }.get(title, title)
        full_title = '%s (%s)' % (title, category)
        try:
            full_page = wiki[normalize_article_name(full_title)]
        except KeyError:
            return title
        if wiki.redirect_target(full_title) == title:
            return title
        elif wiki.redirect_target(title) == full_title:
            return title
        else:
            return full_title

    def object_url(self, category, obj):
        return self.normalized_wiki_title(obj.name, category)

    def identifier_url(self, category, identifier):
        return self.normalized_wiki_title(identifier, category)

link_extension = LinkExtension(session)

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
        return text + content + '\n\n' + tail.strip()
    elif elem.tag == 'a':
        href = normalize_article_name(elem.attrib['href'])
        content = text + content
        if normalize_article_name(content) == href:
            return '[[%s]]' % content + tail
        elif normalize_article_name(content) == href + 's':
            return '[[%s]]s' % content[:-1] + tail
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
    elif elem.tag == 'li':
        return '* ' + text + content + tail
    if elem.tag in ('thead', 'tbody', 'ul'):
        return text.strip() + content + tail.strip()
    if elem.tag == 'code':
        return '<code>' + text.strip() + content + '</code>' + tail.strip()
    else:
        # XXX
        return '⚠ veekun→wiki script bug: unknown element %s ⚠' % elem.tag + tail
        raise ValueError(elem.tag)

class CombinedChangelogEntry(object):
    def __init__(self, move_change, effect_change):
        self.move_change = move_change
        self.effect_change = effect_change

    def __getattr__(self, attr):
        try:
            return getattr(self.effect_change, attr)
        except AttributeError:
            return getattr(self.move_change, attr)

def markdown_to_wikitext(effect):
    tree = etree.fromstring('<div>' + effect.as_html(link_extension) + '</div>')
    wikitext = etree_to_wikitext(tree)
    wikitext = wikitext.replace('.  ', '. ')
    wikitext = wikitext.strip()
    return wikitext

def last_in(change, default):
    if change is None:
        return default
    else:
        return version_groups[version_groups.index(change.changed_in) - 1]

def get_move_changelog(move):
    changelog = OrderedDict()
    current_changes = current_versions = None
    unchanged = True
    for version in sorted(move.versions, key=lambda v: v.version_group.order, reverse=True):
        vg = version.version_group
        changes = OrderedDict()
        for attr in 'type power accuracy pp effect_chance'.split():
            if getattr(version, attr) != getattr(move, attr):
                changes[attr] = getattr(version, attr)
        if version.effect_id != move.effect_id:
            changes['effect'] = markdown_to_wikitext(version.effect)
        for change in move.move_effect.changelog:
            if vg.order < change.changed_in.order:
                changes['effect_change'] = markdown_to_wikitext(change.effect)
        if changes:
            unchanged = False
        if unchanged:
            changes['effect'] = markdown_to_wikitext(move.effect)
        changelog[vg] = changes
    return changelog

def format_changelog(changelog):
    by_generation = defaultdict(list)
    for vg, changes in changelog.items():
        by_generation[vg.generation_id].append((vg, changes))
    generation_texts = {}
    # Group by generations; handle intra-generation changes
    for generation, version_changes in sorted(by_generation.items(), reverse=True):
        first_change = version_changes[0][1]
        if all(c == first_change for v, c in version_changes):
            generation_texts[generation] = format_change(first_change)
        else:
            generation_texts[generation] = '⚠ Subgenerations not done yet ⚠'  # XXX
    # Merge identical generations
    grouped = []
    current_text = current_generations = None
    for generation, text in sorted(generation_texts.items(), reverse=True):
        if text == current_text:
            current_generations.append(generation)
        else:
            current_generations = [generation]
            current_text = text
            grouped.append((current_generations, current_text))
    # Build result
    result = []
    for generations, text in grouped:
        if len(generations) > 1:
            result.append('=== Generation {0}-{1} ==='.format(
                    generations[-1], generations[0]))
        else:
            result.append('=== Generation {0} ==='.format(generations[0]))
        result.append(text + '\n')
    return '\n'.join(result).strip()

def format_change(change):
    result = []
    for kind, value in change.items():
        if kind == 'type':
            result.append('Is a %s-type move.' % value.name)
        elif kind == 'power':
            result.append('Base Power is %s.' % value)
        elif kind == 'pp':
            result.append('PP is %s.' % value)
        elif kind == 'accuracy':
            result.append('Accuracy is %s.' % value)
        elif kind == 'effect_chance':
            if 'effect' not in change:
                result.append('Effect chance is %s%%.' % value)
        elif kind == 'effect':
            result.append(value)
        elif kind == 'effect_change':
            result.append(value)  # XXX: get rid of this
        else:
            raise ValueError(kind)
    return ' '.join(result)

def remove_refs(text):
    return re.sub(r'<ref>([^<]|<(?!/ref>))*</ref>', '', text)

def get_effect_diff(section, effect, changelog={}, generation_introduced=None):
    wikitexts = ['== Effect ==']
    wikitexts.append(format_changelog(changelog))
    section_text = unicode(section)
    section_text = remove_refs(section_text)
    section_text = re.sub(r'\[\[Category:[A-Za-z ]*\]\]', '', section_text)
    section_text = re.sub(r'\{\{(movestub|StubItem|StubAbility) \| \}\}', '', section_text)
    section_text = re.sub(r'\{\{[Ii]mported *\| *[A-Za-z]*\}\}', '', section_text)
    section_text = re.sub(r' *\{\{verify[^}]*\}\}\n?', '', section_text)
    section_text = section_text.strip()
    wikitext = '\n'.join(wikitexts)
    if wikitext == section_text:
        return None
    else:
        return make_diff(section_text, wikitext)

def analyze_move(article, move):
    for section in named_sections(article):
        header_name = section.header.name.strip()
        if header_name == 'Effect':
            return get_effect_diff(section, move.effect,
                get_move_changelog(move), move.generation)
    else:
        return False

def analyze_ability(article, ability):
    for section in named_sections(article):
        header_name = section.header.name.strip()
        if header_name == 'Effect':
            return get_effect_diff(section, ability.effect)
    else:
        return False

def analyze_item(article, item):
    for section in named_sections(article):
        header_name = section.header.name.strip()
        if header_name == 'Effect':
            return get_effect_diff(section, item.effect)
    else:
        return False

def get_wikitext(name, page_type):
    wikitext = wiki.get('%s (%s)' % (name, page_type), follow_redirect=True)
    if wikitext is None:
        wikitext = wiki.get(name, follow_redirect=True)
    return wikitext

def main():
    for move in session.query(tables.Move):
        wiki.mark_needed_pages([move.name + ' (move)'])
        wiki.mark_needed_pages([move.name])

    for ability in session.query(tables.Ability):
        wiki.mark_needed_pages([ability.name + ' (ability)'])
        wiki.mark_needed_pages([ability.name])

    for item in session.query(tables.Item):
        wiki.mark_needed_pages([item.name + ' (item)'])
        wiki.mark_needed_pages([item.name])

    with open('diffs.cat', 'w') as catfile, open('diffs.wiki', 'w') as wikifile:
        try:
            catfile_fileno = catfile.fileno()
            os.fchmod(catfile_fileno, os.fstat(catfile_fileno).st_mode | stat.S_IEXEC)
            catfile.write('#! /bin/cat\n\n')
        except Exception:
            print "Warning: couldn't make output file executable"

        wikifile.write(dedent("""
        This __NOTOC__ page shows '''some''' differences between {veekun} and the {powiki}.
        (It also shows bugs in the script that made the page.)

        Generated by pokemwdb/powiki.py from https://github.com/encukou/pokemwdb.

        Wanna use this page?
        * Check if the difference is still there – this page doesn't get updated often.
        * If the wiki is obviously more wrong, improve it. Then just remove the section here (edit link in section header, delete text, save).
        * If veekun is obviously more wrong, check that the wiki has references, and get in touch (e.g. use the talk page here).
        * Discussions toward better common style and wording guidelines are welcome.

        """).format(
                veekun=wiki_colorizers[1]('veekun'),
                powiki=wiki_colorizers[0]('wiki'),
            ).encode('utf-8'))

        header_texts = dict()
        good_articles = set()
        bad_articles = set()
        def yield_wikifiles():
            for i in range(50):
                yield wikifile
            wikifile.write('\n=Truncated=')
            wikifile.write('\nThere are too many differences to list them all.')
            class FakeFile(object):
                def write(self, s): pass
            fake_file = FakeFile()
            while True:
                yield fake_file
        yield_wikifile = yield_wikifiles().next

        def write_diff(diff, veekun_section, name):
            if diff:
                term_header = termcolor.colored(name.encode('utf-8'), 'blue')
                print term_header
                catfile.write(term_header + b'\n')
                print_diff(diff)
                print_diff(diff, catfile)
                template = '={0}=\n' + re.sub(r'\s+', ' ', """
                <div style="float:right;border:1px solid #eee;padding:1ex;white-space:pre;" class="plainlinks">[[{0}|{1}]]
                ([{{{{fullurl:{0}|action=edit}}}} edit] ◦
                [[Talk:{0}|talk]] ◦
                [{{{{fullurl:{0}|action=history}}}} history]) ◦
                [http://veekun.com/dex/{4}/{2}#effect {3}]
                </div>
                """)
                w_file = yield_wikifile()
                w_file.write(template.format(
                        name,
                        wiki_colorizers[0]('wiki'),
                        name.lower().replace(' ', '%20'),
                        wiki_colorizers[1]('veekun'),
                        veekun_section,
                    ).encode('utf-8'))
                w_file.write('<div style="font-family:monospace;white-space:pre;white-space:pre-wrap;">')
                print_wiki_diff(diff, w_file)
                w_file.write('</div><br style="clear:both;">\n')
                print
            elif diff is False:
                bad_articles.add(name)
            else:
                good_articles.add(name)

        q = session.query(tables.Move)
        q = q.options(joinedload('versions'))
        #q = q.filter_by(identifier='acid-armor')
        for move in sorted(q, key=lambda m: m.name):
            wikitext = get_wikitext(move.name, 'move')
            article = wikiparse.wikiparse(wikitext)
            diff = analyze_move(article, move)
            write_diff(diff, 'moves', move.name)

        for ability in sorted(session.query(tables.Ability), key=lambda m: m.name):
            wikitext = get_wikitext(ability.name, 'ability')
            article = wikiparse.wikiparse(wikitext)
            diff = analyze_ability(article, ability)
            write_diff(diff, 'abilities', ability.name)

        '''
        for item in sorted(session.query(tables.Item), key=lambda m: m.name):
            wikitext = get_wikitext(item.name, 'item')
            article = wikiparse.wikiparse(wikitext)
            diff = analyze_item(article, item)
            write_diff(diff, 'items', item.name)
        '''

        wikifile.write('\n')
        if good_articles:
            wikifile.write(('\n=Victory! No differences detected=\n' +
                    ', '.join('%s' % n for n in sorted(good_articles))).encode('utf-8'))
        if bad_articles:
            wikifile.write(('\n=Pages with no Effect section=\n' +
                    ', '.join('[[%s]]' % n for n in sorted(bad_articles))).encode('utf-8'))

main()
