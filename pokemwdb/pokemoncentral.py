#! /usr/bin/env python
# Encoding: UTF-8

from __future__ import unicode_literals

from pokedex.db import connect, tables
import re

from pokemwdb.wikicache import WikiCache
from pokemwdb.wikichecker import (WikiChecker, ArticleChecker,
        TemplateTemplate, normalize, missing_on, param_name, ignored, checker)
from pokemwdb import wikiparse

def _coleot(value):
    return {'Coleottero': ('Coleot', 'Coleottero')}.get(value, value)  # XXX

def group_digits(num):
    num = unicode(num)
    chunks = []
    while num:
        num, lastpart = num[:-3], num[-3:]
        chunks.append(lastpart)
    return '.'.join(reversed(chunks))

def eufloat(num):
    return unicode(float(unicode(num).replace(',', '.'))).replace('.', ',')

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
    def prec(self, v): return self.prev.name
    def numprec(self, v): return format(self.prev.id, '03')

    @normalize(wikiparse.make_wikiname)
    def succ(self, v): return self.next.name
    def numsucc(self, v): return format(self.next.id, '03')

    @normalize(wikiparse.make_wikiname)
    def tipo(self, v): return _coleot(self.default_pokemon.types[0].name)
    @normalize(wikiparse.make_wikiname)
    @missing_on(IndexError)
    def tipo2(self, v):
        return _coleot(self.default_pokemon.types[1].name)

class PokemonInfobox(TemplateTemplate):
    def _init(self):
        self.dexnums = dict((dn.pokedex.identifier, dn.pokedex_number) for dn
                in self.species.dex_numbers)

    def nome(self, v): return self.species.name

    def nomejap(self, v):
        return self.species.name_map[self.dbget(tables.Language, 'ja')]

    @checker
    def romaji(self, v, expected):
        if self.species.generation_id == 5:
            return
        try:
            val = self.species.name_map[self.dbget(tables.Language, 'roomaji')]
        except KeyError:
            return
        if val != expected:
            yield 'Japanese TM name mismatch: expected %s, got %s' % (expected,
                    val)


    size = ignored()
    image = ignored()
    didascalia = ignored()


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


    def ntipi(self, v): return len(self.species.default_pokemon.types)
    def tipo1(self, v): return self.species.default_pokemon.types[0].name

    @missing_on(IndexError, ('', None))
    def tipo2(self, v): return self.species.default_pokemon.types[1].name


    specie = ignored() # XXX return self.species.genus


    @param_name('height-ftin')
    def height_ftin(self, v): return '''{0}'{1:02}"'''.format(*divmod(
            int(round(self.species.default_pokemon.height * 3.937)), 12))

    @param_name('height-m')
    @normalize(eufloat)  # XXX
    def height_m(self, v): return unicode(
            self.species.default_pokemon.height / 10.).replace('.', ',')

    @param_name('peso-lbs')
    @normalize(eufloat)  # XXX
    def weight_lbs(self, v): return unicode(int(round(
            self.species.default_pokemon.weight * 2.20462262)) / 10.
            ).replace('.', ',')

    @param_name('peso-kg')
    @normalize(eufloat)  # XXX
    def weight_kg(self, v): return unicode(
            self.species.default_pokemon.weight / 10.).replace('.', ',')


    @param_name('nabilità')
    def abilityn(self, v): return len(self.species.default_pokemon.abilities)

    @param_name('abilità1')
    def ability1(self, v): return self.species.default_pokemon.abilities[0].name

    @param_name('abilità2')
    @missing_on(IndexError, ('', None))  # XXX
    def ability2(self, v): return self.species.default_pokemon.abilities[1].name

    @param_name('abilitàd')
    @missing_on(AttributeError)
    def abilityd(self, v):
        poke = self.species.default_pokemon
        if poke.dream_ability in poke.abilities:
            return None
        else:
            return self.species.default_pokemon.dream_ability.name


    def _egggroup(num):
        return ignored()  # XXX: Not translated in veekun

        def _eggroup_check(self, v):
            try:
                val = self.species.egg_groups[num].name
            except IndexError:
                return ('', None)
            else:
                return {
                    }.get(val, val)
        return _eggroup_check

    gruppouovo1 = _egggroup(0)
    gruppouovo2 = _egggroup(1)

    def ngruppiuovo(self, v):
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

    espceduta = ignored()  # XXX (expyield)
    def lv100exp(self, v): return group_digits(
            self.species.growth_rate.max_experience)

    def codsesso(self, v):
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

    def tassocattura(self, v): return self.species.capture_rate
    def body(self, v): return format(self.species.shape_id, '02')
    def colore(self, v): return self.species.color.name
    def generazione(self, v): return self.species.generation_id

    pokefordex = ignored()
    footnotes = ignored()

    def cicliuovo(self, v): return self.species.hatch_counter

    odex = ignored()
    fdex = ignored()
    adex = ignored()
    opdex = ignored()

    params = {'1': ignored()}  # XXX

class PokemonChecker(ArticleChecker):
    def __init__(self, checker, species):
        ArticleChecker.__init__(self, checker, species.name)
        self.species = species

class CheckPokemonNavigation(PokemonChecker):
    name = 'prev/next navigation'

    def check(self):
        for i, template in enumerate(self.find_template('PokémonPrecedenteSuccessivo', find_all=True)):
            for error in PokemonPrevNextHead(self, template, species=self.species).check():
                yield '[%s] %s' % ('header footer'.split()[i], error)

class CheckPokemonInfobox(PokemonChecker):
    name = 'infobox'

    def check(self):
        template = self.find_template('PokémonInfo')
        if template is None:
            return ['Infobox not found at all!']
        return PokemonInfobox(self, template, species=self.species).check()

class PCChecker(WikiChecker):
    base_url = 'http://wiki.pokemoncentral.it/api.php?'
    path = 'data/pokecentral'

    def __init__(self):
        WikiChecker.__init__(self)
        self.cache.seconds_per_request = 15
        self.session = connect()
        self.session.default_language_id = self.session.query(
                tables.Language).filter_by(identifier='it').one().id

    def checkers(self):
        for species in self.session.query(tables.PokemonSpecies):
            yield CheckPokemonNavigation(self, species)
            yield CheckPokemonInfobox(self, species)

if __name__ == '__main__':
    PCChecker().check()
