#! /usr/bin/env python
# Encoding: UTF-8

from __future__ import unicode_literals

from pokedex.db import connect, tables
import re

from pokemwdb.wikicache import WikiCache
from pokemwdb.wikichecker import (WikiChecker, ArticleChecker,
        TemplateTemplate, normalize, missing_on, param_name, ignored, checker,
        WrongTemplateParameter)
from pokemwdb import wikiparse

session = connect()
en = session.query(tables.Language).filter_by(identifier='en').one()

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
    def prec(self, v): return self.prev.name_map[en]
    def numprec(self, v): return format(self.prev.id, '03')

    @normalize(wikiparse.make_wikiname)
    def succ(self, v): return self.next.name_map[en]
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

    def nome(self, v): return self.species.name_map[en]

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
            yield WrongTemplateParameter('romaji', expected, val)


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
    def udex(self, v): return format(self.dexnums['original-unova'], '03')

    @missing_on(KeyError)
    def u2dex(self, v): return format(self.dexnums['updated-unova'], '03')

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

def game_text(text):
    return text.replace('\n', ' ')

mdash = ('—', '&mdash;', 'N/A')

class MoveInfobox(TemplateTemplate):
    def _init(self):
        self.flags = set(f.identifier for f in self.move.flags)

        self.machines = dict((m.version_group.generation_id, m.machine_number)
                for m in self.checker.checker.session.query(tables.Machine)
                        .filter_by(move_id=self.move.id))

        self.tutors = set(pm.version_group.versions[0].identifier for pm in
                self.move.pokemon_moves if pm.method.identifier == 'tutor')

    def name(self, v): return self.move.name

    def jname(self, v):
        return self.move.name_map[self.dbget(tables.Language, 'ja')]

    def engname(self, v):
        return self.move.name_map[self.dbget(tables.Language, 'en')]

    jtrans = ignored()
    engtname = ignored()

    def n(self, v): return self.move.id if self.move.id < 10000 else 1000

    @missing_on(AttributeError)
    def tipo(self, v): return self.move.type.name

    desc = ignored()

    def _changelog(func, attrname=None):
        gens = '0 prima seconda terza quarta quinta'.split()
        param_name(func.__name__ + 'notes')
        attrname = attrname or func.__name__
        def wrapper(self, v):
            history = dict((c.changed_in, getattr(c, attrname)) for
                    c in self.move.changelog)
            low = high = self.move.generation_id
            changes = []
            for vg in list(self.checker.checker.session.query(tables.VersionGroup)) + [None]:
                try:
                    new_value = history[vg]
                except KeyError:
                    new_value = None
                if new_value is None:
                    pass
                else:
                    if low == high:
                        geninfo = 'nella %s' % gens[high]
                    else:
                        geninfo = 'dalla %s alla %s' % (gens[low], gens[high])
                    value = func(None, None, new_value)
                    if isinstance(value, tuple):
                        value = value[0]
                    low = vg.generation_id
                    changes.append('%s %s generazione' % (value, geninfo))
                if vg:
                    high = vg.generation_id
            if changes:
                return ', '.join(changes)
            else:
                return None
        return wrapper

    def basepp(self, v, _pp=None):
        if _pp is None:
            _pp = self.move.pp
        return _pp or mdash
    ppnotes = _changelog(basepp, attrname='pp')

    #def maxpp(self, v): return self.move.pp * 8 // 5 if self.move.pp else mdash
    maxppnotes = _changelog(lambda s, v, pp: pp * 8 // 5, attrname='pp')

    def accuracy(self, v, _accuracy=None):
        if _accuracy is None:
            _accuracy = self.move.accuracy
        if _accuracy in (0, 100, None):
            return (_accuracy, ) + mdash
        else:
            return _accuracy
    accuracynotes = _changelog(accuracy)

    def power(self, v, _power=None):
        if _power is None:
            _power = self.move.power
        if _power == 1:
            return mdash + ('Variabile', )
        else:
            return _power or mdash
    powernotes = _changelog(power)

    def priority(self, v):
        if not self.move.priority:
            return ('' or None)
        elif self.move.priority > 0:
            return '+%s' % self.move.priority
        else:
            return self.move.priority

    def _flag(self, identifier, true_val=True):
        if (identifier in self.flags) == true_val:
            return 'yes'
        else:
            return ('no', None)

    def category(self, v):
        try:
            return self.move.contest_type.name
        except AttributeError:
            if self.move.type.identifier == 'shadow':
                return 'Shadow'
    category = ignored()  # XXX

    @missing_on(AttributeError, (None, 0))
    def appeal(self, v):
        if self.move.generation_id <= 3:
            return self.move.contest_effect.appeal or (None, 0)

    @missing_on(AttributeError, (None, 0))
    def jam(self, v): return self.move.contest_effect.jam

    @missing_on(AttributeError)
    def appealsc(self, v): return self.move.super_contest_effect.appeal or (None, 0)

    def touches(self, v): return self._flag('contact')
    # charge
    def recharge(self, v): return self._flag('recharge')
    def protect(self, v): return self._flag('protect')
    def magiccoat(self, v): return self._flag('reflectable')
    def snatch(self, v): return self._flag('snatch')
    def mirrormove(self, v): return self._flag('mirror')
    #def punch(self, v): return self._flag('punch')
    def sound(self, v): return self._flag('sound')
    # defrost
    # distance [handled in `target` below]
    # heal
    #def ignoresub(self, v): return self._flag('authentic', true_val=False)

    kingsrock = ignored()  # XXX
    brightpowder = ignored()  # XXX
    flag7 = ignored()
    flag8 = ignored()

    burn = ignored()
    freeze = ignored()
    paralysis = ignored()
    sleep = ignored()
    confusion = ignored()
    flinch = ignored()
    poison = ignored()

    def _machine(gen, hm=False):
        def tm(self, v):
            if gen in self.machines:
                if not hm and self.machines[gen] < 100:
                    return 'yes'
                if hm and self.machines[gen] > 100:
                    return 'yes'

        def tm_num(self, v):
            if tm(self, v):
                return format(self.machines[gen] % 100, '02')

        if hm:
            tm.name = 'hm%s' % gen
            tm_num.name = 'hm#%s' % gen
        else:
            tm.name = 'tm%s' % gen
            tm_num.name = 'tm#%s' % gen

        return tm, tm_num

    tm1, tm_1 = _machine(1)
    tm2, tm_2 = _machine(2)
    tm3, tm_3 = _machine(3)
    tm4, tm_4 = _machine(4)
    tm5, tm_5 = _machine(5)
    hm1, hm_1 = _machine(1, True)
    hm2, hm_2 = _machine(2, True)
    hm3, hm_3 = _machine(3, True)
    hm4, hm_4 = _machine(4, True)
    hm5, hm_5 = _machine(5, True)

    def mtc(self, v): return 'yes' if 'crystal' in self.tutors else ('no', None)
    def mte(self, v): return 'yes' if 'emerald' in self.tutors else ('no', None)
    def mtfl(self, v): return 'yes' if 'firered' in self.tutors else ('no', None)
    def mtdp(self, v): return 'yes' if 'diamond' in self.tutors else ('no', None)
    def mtpt(self, v): return 'yes' if 'platinum' in self.tutors else ('no', None)
    #def mths(self, v): return 'yes' if 'heartgold' in self.tutors else ('no', None)
    mths = ignored()
    mtxd = ignored()
    def mtbw(self, v): return 'yes' if 'black' in self.tutors else ('no', None)

    def na(self, v):
        if self.machines or self.tutors:
            return 'yes'
        else:
            return ('no', None)
    na = ignored()  # XXX

    def gen(self, v): return '0 I II III IV V'.split()[self.move.generation_id]

    def damagecategory(self, v):
        return {
                'physical': 'Fisico',
                'special': 'Speciale',
                'non-damaging': 'Stato',
            }[self.move.damage_class.identifier]

    def target(self, v):
        return {
                'all-opponents':
                        'foe' if 'distance' in self.flags else 'adjacentfoes',
                'user': 'self',
                'selected-pokemon':
                        'any' if 'distance' in self.flags else 'anyadjacent',
                'random-opponent': 'foe',
                'users-field': 'team',
                'all-other-pokemon':
                        'all' if 'distance' in self.flags else 'alladjacent',
                'specific-move': 'any',
                'entire-field': 'all',
                'opponents-field': 'foes',
                'ally': 'ally',
                'user-or-ally': 'selfadjacentally',
            }[self.move.target.identifier]

    cdesc = ignored()
    scdesc = ignored()
    bdesc = ignored()
    field = ignored()

    pokefordex = ignored()
    footnotes = ignored()
    gameimage = ignored()

class PokemonChecker(ArticleChecker):
    def __init__(self, checker, species):
        ArticleChecker.__init__(self, checker, species.name_map[en])
        self.species = species

class CheckPokemonNavigation(PokemonChecker):
    name = 'prev/next navi'

    def check(self):
        for i, template in enumerate(self.find_template('PokémonPrecedenteSuccessivo', find_all=True)):
            for error in PokemonPrevNextHead(self, template, species=self.species).check():
                yield error

class CheckPokemonInfobox(PokemonChecker):
    name = 'infobox'

    def check(self):
        template = self.find_template('PokémonInfo')
        if template is None:
            return ['Infobox not found at all!']
        return PokemonInfobox(self, template, species=self.species).check()

class MoveChecker(ArticleChecker):
    def __init__(self, checker, move):
        name = {
                "Att. d'Ala": "Attacco d'Ala",
                "Sottomiss.": "Sottomissione",
                "Mov. Sismico": "Movimento Sismico",
                "Megassorbim.": "Megassorbimento",
                "Att. Rapido": "Attacco Rapido",
                "Teletraspor.": "Teletrasporto",
                "Ombra Nott.": "Ombra Notturna",
                "Autodistruz.": "Autodistruzione",
                "Att. Pioggia": "Attacco Pioggia",
                "Trasformaz.": "Trasformazione",
                "Destinobbl.": "Destinobbligato",
                "Gigassorbim.": "Gigassorbimento",
            }.get(move.name, move.name)
        ArticleChecker.__init__(self, checker, name + ' (mossa)')
        self.move = move

class CheckMoveInfobox(MoveChecker):
    name = 'infobox'

    def check(self):
        template = self.find_template('MossaInfobox')
        return MoveInfobox(self, template, move=self.move).check()

class PCChecker(WikiChecker):
    base_url = 'http://wiki.pokemoncentral.it/api.php?'
    path = 'data/pokecentral'

    def __init__(self):
        WikiChecker.__init__(self)
        self.cache.seconds_per_request = 15
        self.session = session#connect()
        self.session.default_language_id = self.session.query(
                tables.Language).filter_by(identifier='it').one().id

    def checkers(self):
        for species in self.session.query(tables.PokemonSpecies).order_by(tables.PokemonSpecies.id):
            yield CheckPokemonNavigation(self, species)
            yield CheckPokemonInfobox(self, species)
            pass
        for move in self.session.query(tables.Move).join(tables.Move.names_local).order_by(tables.Move.names_table.name):
            yield CheckMoveInfobox(self, move)
            pass

if __name__ == '__main__':
    PCChecker().check()
