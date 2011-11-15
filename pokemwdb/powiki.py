#Encoding: UTF-8
from __future__ import unicode_literals

import sys
import re
import os
import stat
from textwrap import dedent

from pokedex.db import connect, tables, markdown, util
from lxml import etree
import termcolor
from diff_match_patch import diff_match_patch

from pokemwdb.wikicache import WikiCache
from pokemwdb import wikiparse

session = connect()
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

def combined_move_changelog(move):
    all_changes = move.changelog + move.move_effect.changelog
    all_changes.sort(key=lambda c: c.changed_in.id, reverse=True)
    all_changes = [c for c in all_changes
            if c.changed_in.generation_id >= move.generation.id]
    def generator():
        for prev, curr, next in zip([None] + all_changes, all_changes, all_changes[1:] + [None]):
            if prev and prev.changed_in == curr.changed_in:
                continue
            elif next and next.changed_in == curr.changed_in:
                yield CombinedChangelogEntry(curr, next)
            else:
                yield curr
    return list(generator())

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

def get_generation_heading(current, next, generation_introduced):
    current = last_in(current, version_groups[-1])
    if next:
        next = next.changed_in
    elif generation_introduced:
        next = generation_introduced.version_groups[0]
    else:
        next = current
    _index = version_groups.index
    included_version_groups = version_groups[_index(next):_index(current) + 1]
    entries = []
    while included_version_groups:
        version_group = included_version_groups[0]
        generation = version_group.generation
        generation_groups = generation.version_groups
        if all(vg in included_version_groups for vg in generation_groups):
            try:
                entries[-1][1] = generation.id
            except (IndexError, TypeError):
                entries.append([generation.id, generation.id])
            for vg in generation_groups:
                included_version_groups.remove(vg)
        else:
            for version in version_group.versions:
                entries.append(version.name)
            included_version_groups.remove(version_group)
    texts = []
    for entry in entries:
        if isinstance(entry, basestring):
            texts.append(entry)
        else:
            start, end = entry
            if start == end:
                texts.append('Generation {0}'.format(start))
            else:
                texts.append('Generation {0}-{1}'.format(*entry))
    return '=== %s ===' % ', '.join(texts)

def remove_refs(text):
    return re.sub(r'<ref>([^<]|<(?!/ref>))*</ref>', '', text)

def get_effect_diff(section, effect, changelog=[], generation_introduced=None):
    wikitexts = ['== Effect ==']
    if changelog:
        wikitexts.append(get_generation_heading(None, changelog[0], generation_introduced))
    else:
        wikitexts.append(get_generation_heading(None, None, generation_introduced))
    wikitexts.append(markdown_to_wikitext(effect))
    previous_change_next = zip(
            changelog,
            changelog[1:] + [None]
        )
    for change, next in previous_change_next:
        wikitexts.append('')
        wikitexts.append(get_generation_heading(change, next, generation_introduced))
        changes = []
        try:
            change.type
        except AttributeError:
            pass
        else:
            if change.type:
                changes.append('Is a %s-type move.' % change.type.name)
            if change.power:
                changes.append('Base Power is %s.' % change.power)
            if change.pp:
                changes.append('PP is %s.' % change.pp)
            if change.accuracy:
                changes.append('Accuracy is %s.' % change.accuracy)
            if change.effect_chance and not change.effect:
                changes.append('Effect chance is %s%%.' % change.effect_chance)
        if change.effect:
            changes.append(markdown_to_wikitext(change.effect))
        wikitexts.append(' '.join(changes))
    section_text = unicode(section)
    section_text = remove_refs(section_text)
    section_text = section_text.replace('{{movestub | }}', '')
    section_text = section_text.replace('{{imported | move}}', '')
    section_text = section_text.replace('[[Category:Moves]]', '')
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
                combined_move_changelog(move), move.generation)
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

        for move in sorted(session.query(tables.Move), key=lambda m: m.name):
            wikitext = get_wikitext(move.name, 'move')
            article = wikiparse.wikiparse(wikitext)
            diff = analyze_move(article, move)
            write_diff(diff, 'moves', move.name)

        for ability in sorted(session.query(tables.Ability), key=lambda m: m.name):
            wikitext = get_wikitext(ability.name, 'ability')
            article = wikiparse.wikiparse(wikitext)
            diff = analyze_ability(article, ability)
            write_diff(diff, 'abilities', ability.name)

        for item in sorted(session.query(tables.Item), key=lambda m: m.name):
            wikitext = get_wikitext(item.name, 'item')
            article = wikiparse.wikiparse(wikitext)
            diff = analyze_item(article, item)
            write_diff(diff, 'items', item.name)

        wikifile.write('\n')
        if good_articles:
            wikifile.write('\n=Victory! No differences detected=\n' +
                    ', '.join('%s' % n for n in sorted(good_articles)))
        if bad_articles:
            wikifile.write('\n=Pages with no Effect section=\n' +
                    ', '.join('[[%s]]' % n for n in sorted(bad_articles)))

main()
