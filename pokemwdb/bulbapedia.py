#! /usr/bin/env python
# Encoding: UTF-8

from __future__ import unicode_literals

from pokedex.db import connect, tables
import re

from pokemwdb.wikicache import WikiCache
from pokemwdb.wikichecker import (WikiChecker, ArticleChecker,
        TemplateTemplate, normalize, missing_on, param_name, ignored, checker)
from pokemwdb import wikiparse

class PokemonPrevNextHead(TemplateTemplate):
    def _init(self):
        self.prev = self.dbget_id(tables.PokemonSpecies, self.species.id - 1)
        if self.prev is None:
            self.prev = self.dbget(tables.PokemonSpecies, 'genesect')
        self.next = self.dbget_id(tables.PokemonSpecies, self.species.id + 1)
        if self.next is None:
            self.next = self.dbget(tables.PokemonSpecies, 'bulbasaur')
        self.default_pokemon = self.species.default_pokemon

    @normalize(wikiparse.make_wikiname)
    def prev(self, v): return self.prev.name
    def prevnum(self, v): return format(self.prev.id, '03')

    @normalize(wikiparse.make_wikiname)
    def next(self, v): return self.next.name
    def nextnum(self, v): return format(self.next.id, '03')

    @normalize(wikiparse.make_wikiname)
    def type(self, v): return self.default_pokemon.types[0].name
    @normalize(wikiparse.make_wikiname)
    @missing_on(IndexError)
    def type2(self, v):
        return self.default_pokemon.types[1].name

    def species(self, v):
        if self.name == 'PokémonPrevNextHead':
            return self.species.name
        else:
            return None

    params = {'1': ignored()}  # XXX

def group_digits(num):
    num = unicode(num)
    chunks = []
    while num:
        num, lastpart = num[:-3], num[-3:]
        chunks.append(lastpart)
    return ','.join(reversed(chunks))

def remove_simple_html_comment(string):
    return re.sub('\s*<!--[^-]*-->\s*', '', string)

class PokemonInfobox(TemplateTemplate):
    def _init(self):
        self.dexnums = dict((dn.pokedex.identifier, dn.pokedex_number) for dn
                in self.species.dex_numbers)

    def name(self, v): return self.species.name

    def jname(self, v):
        return self.species.name_map[self.dbget(tables.Language, 'ja')]

    @checker
    def tmname(self, v, expected):
        if self.species.generation_id == 5:
            return  # XXX
        try:
            val = self.species.name_map[self.dbget(tables.Language, 'roomaji')]
        except KeyError:
            return
        if val != expected:
            yield 'Japanese TM name mismatch: expected %s, got %s' % (expected,
                    val)


    art = ignored()
    image = ignored()
    caption = ignored()


    def _hdex_normalizer(value):
        try:
            if int(value) > 202:
                return None
            else:
                return value
        except TypeError:
            return value

    def ndex(self, v): return format(self.species.id, '03')

    @missing_on(KeyError)
    def jdex(self, v): return format(self.dexnums['updated-johto'], '03')

    @missing_on(KeyError)
    def oldjdex(self, v):
        if self.dexnums['original-johto'] == self.dexnums['updated-johto']:
            return None
        else:
            return format(self.dexnums['original-johto'], '03')

    @normalize(_hdex_normalizer)
    @missing_on(KeyError)
    def hdex(self, v): return format(self.dexnums['hoenn'], '03')

    @missing_on(KeyError)
    def sdex(self, v): return format(self.dexnums['extended-sinnoh'], '03')

    @missing_on(KeyError)
    def udex(self, v): return format(self.dexnums['unova'], '03')

    fbrow = ignored()
    abrow = ignored()
    obrow = ignored()
    opbrow = ignored()


    def typen(self, v): return len(self.species.default_pokemon.types)
    def type1(self, v): return self.species.default_pokemon.types[0].name

    @missing_on(IndexError, ('', None))
    def type2(self, v): return self.species.default_pokemon.types[1].name


    @normalize(remove_simple_html_comment)
    def species(self, v): return self.species.genus


    @param_name('height-ftin')
    @normalize(lambda s: s.replace('′', "'").replace('″', '"').replace(' ', ''))  # XXX
    def height_ftin(self, v): return '''{0}'{1:02}"'''.format(*divmod(
            int(round(self.species.default_pokemon.height * 3.937)), 12))

    @param_name('height-m')
    @normalize(lambda n: float(n))  # XXX
    def height_m(self, v): return self.species.default_pokemon.height / 10.

    @param_name('weight-lbs')
    @normalize(lambda n: float(n))  # XXX
    def weight_lbs(self, v): return int(round(
            self.species.default_pokemon.weight * 2.20462262)) / 10.

    @param_name('weight-kg')
    @normalize(lambda n: float(n))  # XXX
    def weight_kg(self, v): return self.species.default_pokemon.weight / 10.


    def abilityn(self, v): return len(self.species.default_pokemon.abilities)
    def ability1(self, v): return self.species.default_pokemon.abilities[0].name

    @missing_on(IndexError, ('', None))  # XXX
    def ability2(self, v): return self.species.default_pokemon.abilities[1].name

    @missing_on(AttributeError)
    def abilityd(self, v):
        poke = self.species.default_pokemon
        if poke.dream_ability in poke.abilities:
            return None
        else:
            return self.species.default_pokemon.dream_ability.name


    def _egggroup(num):
        def _eggroup_check(self, v):
            try:
                val = self.species.egg_groups[num].name
            except IndexError:
                return ('', None)
            else:
                return {
                        'Ground': 'Field',
                        'Plant': 'Grass',
                        'No Eggs': 'Undiscovered',
                        'Humanshape': 'Human-Like',
                        'Indeterminate': 'Amorphous',
                    }.get(val, val)
        return _eggroup_check

    egggroup1 = _egggroup(0)
    egggroup2 = _egggroup(1)

    def egggroupn(self, v):
        if self.species.egg_groups[0].identifier == 'no-eggs':
            return (0, 1)  # XXX
        else:
            return len(self.species.egg_groups)


    def _stat(stat_name):
        def _stat_check(self, v):
            val = self.species.default_pokemon.stat(stat_name).effort
            if val:
                return val
            else:
                return None
        return _stat_check

    evhp = _stat('hp')
    evat = _stat('attack')
    evde = _stat('defense')
    evsa = _stat('special-attack')
    evsd = _stat('special-defense')
    evsp = _stat('speed')

    expyield = ignored()  # XXX
    def lv100exp(self, v): return group_digits(
            self.species.growth_rate.max_experience)

    def gendercode(self, v):
        return {
                -1: 255,
                0: 0,
                1: 31,
                2: 63,
                #3: 
                4: 127,
                #5: 
                6: 191,
                7: 223,
                8: 254,
            }[self.species.gender_rate]

    def catchrate(self, v): return self.species.capture_rate
    def body(self, v): return format(self.species.shape_id, '02')
    def color(self, v): return self.species.color.name
    def generation(self, v): return self.species.generation_id

    pokefordex = ignored()
    footnotes = ignored()

    # Old/undocumented params
    def eggcycles(self, v): return self.species.hatch_counter
    pron = ignored()
    size = ignored()

    odex = ignored()
    fdex = ignored()
    adex = ignored()
    opdex = ignored()

    params = {'1': ignored()}  # XXX

class PokemonChecker(ArticleChecker):
    def __init__(self, checker, species):
        ArticleChecker.__init__(self, checker, species.name + ' (Pokémon)')
        self.species = species

class CheckPokemonNavigation(PokemonChecker):
    name = 'prev/next header'

    def check(self):
        template = self.find_template('PokémonPrevNextHead')
        if not template:
            template = self.find_template('PokémonPrevNext')
        return PokemonPrevNextHead(self, template, species=self.species).check()

class CheckPokemonInfobox(PokemonChecker):
    name = 'infobox'

    def check(self):
        template = self.find_template('PokémonInfobox')
        return PokemonInfobox(self, template, species=self.species).check()

class BulbapediaChecker(WikiChecker):
    base_url = 'http://bulbapedia.bulbagarden.net/w/api.php?'
    path = 'data/bp'

    def __init__(self):
        WikiChecker.__init__(self)
        self.session = connect()

    def checkers(self):
        for species in self.session.query(tables.PokemonSpecies):
            yield CheckPokemonNavigation(self, species)
            yield CheckPokemonInfobox(self, species)

if __name__ == '__main__':
    BulbapediaChecker().check()
