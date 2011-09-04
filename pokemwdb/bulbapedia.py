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
    disptype = ignored()

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

    def n(self, v): return self.move.id if self.move.id < 10000 else 1000

    def name(self, v): return self.move.name

    def jname(self, v):
        return self.move.name_map[self.dbget(tables.Language, 'ja')]

    jtrans = ignored()
    jtranslit = ignored()

    @missing_on(IndexError)
    def desc(self, v): return game_text(self.move.flavor_text[-1].flavor_text)

    def type(self, v): return self.move.type.name

    def _changelog(attrname):
        gens = '0 I II III IV V'.split()
        def wrapper(func):
            def get(self, v):
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
                            geninfo = gens[high]
                        else:
                            geninfo = '%s to %s' % (gens[low], gens[high])
                        value = func(new_value)
                        if isinstance(value, tuple):
                            value = value[0]
                        low = vg.generation_id
                        changes.append('%s in Generation %s' % (value, geninfo))
                    if vg:
                        high = vg.generation_id
                value = func(getattr(self.move, attrname))
                if changes:
                    if isinstance(value, tuple):
                        value = value[0]
                    return '{{tt | %s | %s}}' % (value, ', '.join(changes))
                else:
                    return value
            return get
        return wrapper

    @_changelog('pp')
    def basepp(pp): return pp or mdash
    def maxpp(self, v): return self.move.pp * 8 // 5 if self.move.pp else mdash

    @_changelog('accuracy')
    def accuracy(accuracy):
        if accuracy in (0, 100, None):
            return (accuracy, ) + mdash
        else:
            return accuracy

    def priority(self, v):
        if not self.move.priority:
            return ('' or None)
        elif self.move.priority > 0:
            return '+%s' % self.move.priority
        else:
            return self.move.priority

    @_changelog('power')
    def power(power):
        if power == 1:
            return mdash + ('Varies', )
        else:
            return power or mdash


    def category(self, v):
        try:
            return self.move.contest_type.name
        except AttributeError:
            if self.move.type.identifier == 'shadow':
                return 'Shadow'

    @missing_on(AttributeError, (None, 0))
    def appeal(self, v):
        if self.move.generation_id <= 3:
            return self.move.contest_effect.appeal
        elif self.move.generation_id <= 4:
            return self.move.super_contest_effect.appeal

    @missing_on(AttributeError, (None, 0))
    def jam(self, v): return self.move.contest_effect.jam

    @missing_on(AttributeError)
    def appealsc(self, v): return self.move.super_contest_effect.appeal

    def _flag(self, identifier, true_val=True):
        if (identifier in self.flags) == true_val:
            return 'yes'
        else:
            return ('no', None)

    def touches(self, v): return self._flag('contact')
    # charge
    def recharge(self, v): return self._flag('recharge')
    def protect(self, v): return self._flag('protect')
    def magiccoat(self, v): return self._flag('reflectable')
    def snatch(self, v): return self._flag('snatch')
    def mirrormove(self, v): return self._flag('mirror')
    def punch(self, v): return self._flag('punch')
    def sound(self, v): return self._flag('sound')
    # defrost
    # distance [handled in `target` below]
    # heal
    #def ignoresub(self, v): return self._flag('authentic', true_val=False)

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
    def mths(self, v): return 'yes' if 'heartgold' in self.tutors else ('no', None)
    def mtbw(self, v): return 'yes' if 'black' in self.tutors else ('no', None)

    def na(self, v):
        if self.machines or self.tutors:
            return 'yes'
        else:
            return ('no', None)

    mtxd = ignored()  # XXX: XD tutors not yet in DB
    na = ignored()  # XXX: XD tutors not yet in DB

    kingsrock = ignored()  # XXX
    brightpowder = ignored()  # XXX
    flag7 = ignored()
    flag8 = ignored()

    def gen(self, v): return '0 I II III IV V'.split()[self.move.generation_id]

    def damagecategory(self, v):
        return {
                'physical': 'Physical',
                'special': 'Special',
                'non-damaging': 'Status',
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

    cdesc = ignored()  # XXX
    scdesc = ignored()  # XXX
    bdesc = ignored()  # XXX

    field = ignored()  # XXX

    pokefordex = ignored()
    footnotes = ignored()
    gameimage = ignored()
    gameimage2 = ignored()
    gameimagewidth = ignored()

    spm = ignored()  # XXX: What's this?


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

class MoveChecker(ArticleChecker):
    def __init__(self, checker, move):
        ArticleChecker.__init__(self, checker, move.name + ' (move)')
        self.move = move

class CheckMoveInfobox(MoveChecker):
    name = 'infobox'

    def check(self):
        template = self.find_template('MoveInfobox')
        return MoveInfobox(self, template, move=self.move).check()

class BulbapediaChecker(WikiChecker):
    base_url = 'http://bulbapedia.bulbagarden.net/w/api.php?'
    path = 'data/bp'

    def __init__(self):
        WikiChecker.__init__(self)
        self.session = connect()

    def checkers(self):
        for species in self.session.query(tables.PokemonSpecies).order_by(tables.PokemonSpecies.id):
            pass
            yield CheckPokemonNavigation(self, species)
            yield CheckPokemonInfobox(self, species)
        for move in self.session.query(tables.Move).join(tables.Move.names_local).order_by(tables.Move.names_table.name):
            pass
            yield CheckMoveInfobox(self, move)

if __name__ == '__main__':
    BulbapediaChecker().check()
