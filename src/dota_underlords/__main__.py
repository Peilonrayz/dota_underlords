from __future__ import annotations

import cmd
import collections
import copy
import dataclasses
import itertools
import json
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Set,
    Tuple,
    TypeVar,
    Union,
    cast,
)

from mm_json.public.dataclasses_json import Converter, dataclass_json

converter = Converter()


@dataclass_json
@dataclasses.dataclass
class Alliance:
    name: str
    level: int
    total: int
    effect: str
    heroes: List[str] = dataclasses.field(default_factory=set, repr=False)

    def __hash__(self):
        return hash(self.name)

    def __str__(self):
        return (
            f"{self.name} ("
            + "/".join(map(str, self.sizes))
            + ")"
            + "\n  "
            + self.effect
            + "\n  Heroes:"
            + "".join(
                f"\n    {hero.name}({hero.tier})"
                for hero in sorted(self.heroes, key=hero_sort)
            )
        )

    @property
    def sizes(self):
        return range(self.level, self.total + 1, self.level)


@dataclass_json
@dataclasses.dataclass
class Stats:
    health: int
    mana: int
    dps: int
    damage: Tuple[int, int]
    attack_rate: float
    move_speed: int
    attack_range: int
    magic_resist: int
    armour: int
    health_regen: int


@dataclass_json
@dataclasses.dataclass
class Hero:
    name: str
    tier: int
    ace: Optional[str]
    alliances: List[str]
    abilities: List[str]
    description: str
    stats: List[Stats]

    def __hash__(self):
        return hash(self.name)

    def __str__(self):
        return f"{self.name}({self.tier})\n" f"  Alliances:" + "".join(
            "\n    "
            + ("\b\b* " if self.ace == alliance else "")
            + alliance.name
            + " ("
            + "/".join(map(str, alliance.sizes))
            + ")"
            for alliance in self.alliances
        )


T = TypeVar("T")


def iter_or(iter: Iterator[T], default: T) -> Iterator[T]:
    sentinal = object()
    first = next(iter, sentinal)
    if first is sentinal:
        yield default
    else:
        yield cast(T, first)
        yield from iter


def team_add(amount: int):
    def inner(team: Team, alliance: Alliance) -> Team:
        return team.add(alliance, amount)

    return inner


def team_inc(team: Team, alliance: Alliance) -> Team:
    if alliance not in team.alliances:
        level = 1
    else:
        level = team.alliances[alliance].level + 1
    return team.add(alliance, level)


def team_max(team: Team, alliance: Alliance) -> Team:
    return team.add_max(alliance)


def hero_sort(hero: Hero) -> Tuple[int, str]:
    return hero.tier, hero.name


def _str_heroes(heroes: Union[Iterator[Hero], Iterable[Hero]]) -> str:
    return ", ".join(f"{h.name}({h.tier})" for h in sorted(heroes, key=hero_sort))


class TeamAlliance:
    alliance: Alliance
    level: int
    tas: TeamAlliances

    def __init__(self, alliance: Alliance, level: int, tas: TeamAlliances,) -> None:
        self.alliance = alliance
        self.level = level
        self.tas = tas

    def __str__(self) -> str:
        return (
            f"  {self.alliance.name} {self.level}"
            f"\n    Team, {self.t_size}"
            f" of {_str_heroes(self.t_heroes)}"
            f"\n    Mixed, {self.m_size}"
            f" of {_str_heroes(self.m_heroes)}"
            f"\n    Alliance, {self.a_size}"
            f" of {_str_heroes(self.a_heroes)}"
        )

    @classmethod
    def from_empty(cls, alliance: Alliance, tas: TeamAlliances) -> TeamAlliance:
        return cls(alliance, 0, tas)

    def copy(self, tas: TeamAlliances) -> TeamAlliance:
        return type(self)(self.alliance, self.level, tas)

    @property
    def p_size(self) -> int:
        return min(self.alliance.level * self.level, len(self.p_heroes))

    @property
    def t_size(self) -> int:
        return min(self.alliance.level * self.level, len(self.t_heroes))

    @property
    def m_size(self) -> int:
        return self.p_size - self.t_size

    @property
    def a_size(self) -> int:
        return self.alliance.level * self.level - self.p_size

    @property
    def total_size(self) -> int:
        return self.alliance.level * self.level

    @property
    def p_heroes(self) -> Set[Hero]:
        return self.alliance.heroes & self.tas.pool

    @property
    def t_heroes(self) -> Set[Hero]:
        return self.alliance.heroes & self.tas.team

    @property
    def m_heroes(self) -> Set[Hero]:
        return self.alliance.heroes & self.tas.mixed

    @property
    def a_heroes(self) -> Set[Hero]:
        return self.alliance.heroes - self.tas.pool

    def level_up_amount(self, level: int, t_size: int):
        n_size = level * self.alliance.level
        return max(0, n_size - len(self.p_heroes) - t_size)


class TeamAlliances(Dict[Alliance, TeamAlliance]):
    team: Set[Hero]
    mixed: Set[Hero]

    def __init__(self, *, team: Set[Hero], mixed: Set[Hero]) -> None:
        super().__init__()
        self.team = team
        self.mixed = mixed

    def __str__(self) -> str:
        return (
            f"  Team({len(self.team)}): {_str_heroes(self.team)}\n"
            f"  Mixed({len(self.mixed)}): {_str_heroes(self.mixed)}\n"
            + "\n".join(str(ta) for ta in self.values())
        )

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, TeamAlliances):
            return False
        return (
            self.team == other.team
            and self.mixed == other.mixed
            and self.keys() == other.keys()
        )

    def __missing__(self, alliance: Alliance) -> TeamAlliance:
        ret = TeamAlliance.from_empty(alliance, self)
        self[alliance] = ret
        return ret

    def copy(self) -> TeamAlliances:
        new = type(self)(team=set(self.team), mixed=set(self.mixed),)
        for key, value in self.items():
            new[key] = value.copy(new)
        return new

    def set(self, alliance: Alliance, level: int) -> None:
        self[alliance] = TeamAlliance(alliance, level, self)

    @property
    def size(self) -> int:
        return (
            len(self.team)
            + len(self.mixed)
            + sum(max(0, ta.a_size) for ta in self.values())
        )

    @property
    def pool(self) -> Set[Hero]:
        return self.team | self.mixed


class Team:
    size: int
    alliances: TeamAlliances
    limit: int

    def __init__(self, limit: int = 10) -> None:
        self.size = 0
        self.alliances = TeamAlliances(team=set(), mixed=set())
        self.limit = limit

    def __str__(self) -> str:
        return f"Team({self.size},{self.alliances.size}):\n" + str(self.alliances)

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Team):
            return False
        return (
            self.size == other.size
            and self.alliances == other.alliances
            and self.limit == other.limit
        )

    def _copy(self) -> Team:
        return type(self)(limit=self.limit)

    def copy(self) -> Team:
        new = self._copy()
        new.size = self.size
        new.alliances = self.alliances.copy()
        return new

    def _post_check(self, prev_tas: TeamAlliances) -> None:
        for ta in self.alliances.values():
            if len(ta.a_heroes) < ta.a_size:
                self.alliances = prev_tas
                raise ValueError(
                    f'Not enough alliance heroes for alliance {ta.alliance.name}. Need {ta.a_size}, but only {", ".join(h.name for h in ta.a_heroes)} available.'
                )
            if len(ta.m_heroes) < ta.m_size:
                self.alliances = prev_tas
                raise ValueError(
                    f'Not enough mixed heroes for alliance {ta.alliance.name}. Need {ta.m_size}, but only {", ".join(h.name for h in ta.m_heroes)} available.'
                )

    def _post_add_mixed(self) -> None:
        team: Set[Hero] = set()
        for ta in self.alliances.values():
            if len(ta.a_heroes) <= ta.a_size:
                team |= ta.a_heroes
        self.alliances.mixed |= team

    def _post_add_team(self) -> None:
        team: Set[Hero] = set()
        for ta in self.alliances.values():
            if len(ta.m_heroes) <= ta.m_size:
                team |= ta.m_heroes
        self.alliances.team |= team
        self.alliances.mixed -= team

    def _post_add_alliance(self) -> None:
        alliances: Dict[Alliance, List[Hero]] = {}
        for hero in self.alliances.team:
            for alliance in cast(List[Alliance], hero.alliances):
                alliances.setdefault(alliance, []).append(hero)
        for alliance, heroes in alliances.items():
            level = len(heroes) // alliance.level
            if level:
                ta = self.alliances[alliance]
                if level > ta.level:
                    ta.level = level

    def _post_add(self) -> None:
        self._post_add_mixed()
        self._post_add_team()
        self._post_add_alliance()

    def _add_heros(self, team):
        prev_tas = self.alliances.copy()
        self.alliances.pool |= team
        return prev_tas

    def _add(
        self, alliance: Alliance, levels: Union[Iterator[int], Iterable[int]]
    ) -> None:
        team: Set[Hero] = self.alliances.pool
        t_size = 0
        if alliance not in self.alliances:
            for al, ta in self.alliances.items():
                if al != alliance and ta.a_size > 0:
                    heroes = al.heroes & alliance.heroes
                    t_size += min(ta.a_size, len(heroes - team))
                    team |= heroes
        team -= self.alliances.pool
        ta = self.alliances[alliance]
        size = self.alliances.size
        for level in levels:
            if level > ta.level:
                amount = ta.level_up_amount(level, t_size)
                if size + amount <= self.limit:
                    size += amount
                    break
        if size > self.limit:
            raise ValueError(
                f'Adding {alliance.name} requires too many heroes {size}, even though {", ".join(h.name for h in team)} overlap'
            )
        prev_tas = self.alliances.copy()
        self.alliances.mixed |= team
        self.size = size
        self.alliances.set(alliance, level)
        if self.alliances.size > self.limit:
            size = self.alliances.size
            self.alliances = prev_tas
            raise ValueError(
                f'Adding {alliance.name} requires too many heroes {size}, even though {", ".join(h.name for h in team)} overlap'
            )
        self._post_check(prev_tas)
        self._post_add()

    def add(self, alliance: Alliance, level: int) -> Team:
        self._add(alliance, [min(level, alliance.total // alliance.level)])
        return self

    def add_max(self, alliance: Alliance) -> Team:
        self._add(alliance, range(alliance.total // alliance.level, 0, -1))
        return self

    def _add_hero(self, hero: Hero):
        if (
            not any(
                hero in ta.a_heroes for ta in self.alliances.values() if ta.a_size > 0
            )
            and self.alliances.size + 1 > self.limit
        ):
            raise ValueError(f"Team full can't add {hero.name}")
        prev_tas = self.alliances.copy()
        self.alliances.team |= {hero}
        self.alliances.mixed -= self.alliances.team
        self._post_check(prev_tas)
        self._post_add()

    def add_hero(self, hero: Hero) -> Team:
        self._add_hero(hero)
        return self

    def _increase(
        self, alliances: List[Alliance], *, fn: Callable[[Team, Alliance], Team],
    ) -> Iterator[Team]:
        for alliance in alliances:
            try:
                value = fn(self.copy(), alliance)
            except ValueError as e:
                print(alliance.name, e)
            else:
                if value != self:
                    yield value

    def increase(
        self, alliances: List[Alliance], *, fn: Callable[[Team, Alliance], Team],
    ) -> Iterator[Team]:
        return iter_or(self._increase(alliances, fn=fn), self)

    def _recursive_increase(
        self, alliances: List[Alliance], *, fn: Callable[[Team, Alliance], Team],
    ) -> Iterator[Team]:
        for team in self._increase(alliances, fn=fn):
            yield from team.recursive_increase(alliances, fn=fn)

    def recursive_increase(
        self, alliances: List[Alliance], *, fn: Callable[[Team, Alliance], Team],
    ) -> Iterator[Team]:
        return iter_or(self._recursive_increase(alliances, fn=fn), self)


class GlobalTeam(Team):
    def __init__(self, alliances: List[Alliance], limit=10) -> None:
        super().__init__(limit=limit)
        self._alliances = alliances

    def _copy(self) -> GlobalTeam:
        return type(self)(self._alliances, limit=self.limit)

    def increase(
        self, alliances: Any = None, fn: Callable[[Team, Alliance], Team] = team_max,
    ) -> Iterator[Team]:
        return iter_or(self._increase(self._alliances, fn=fn), self)

    def recursive_increase(
        self, alliances: Any = None, fn: Callable[[Team, Alliance], Team] = team_max,
    ) -> Iterator[Team]:
        return iter_or(self._recursive_increase(self._alliances, fn=fn), self)


class Underlord:
    def __init__(self, heroes: List[Hero], alliances: List[Alliance]):
        self.heroes = heroes
        self.hero = {h.name: h for h in heroes}
        self.alliances = alliances
        self.alliance = {a.name: a for a in alliances}
        self.alliances_overlap = {
            (a1, a2): a1.heroes & a2.heroes
            for a1, a2 in itertools.product(alliances, repeat=2)
        }

    def with_alliances(self, *alliances: Tuple[str, int]):
        team = GlobalTeam(self.alliances)
        for alliance, level in alliances:
            team.add(self.alliance[alliance], level)
        return team


def load(jailbirds: Set[str]) -> Tuple[List[Hero], List[Alliance]]:
    with open("underlord.json") as f:
        data = json.load(f)

    heroes = Hero.schema().load(data["heroes"], many=True)
    alliances = Alliance.schema().load(data["alliances"], many=True)
    alliance = {a.name: a for a in alliances}
    jailbirds = {j.lower() for j in jailbirds}
    for hero in heroes:
        if hero.name.lower() in jailbirds:
            continue
        try:
            hero.alliances = [alliance[a] for a in hero.alliances]
            for al in hero.alliances:
                al.heroes.add(hero)
            if hero.ace:
                hero.ace = alliance[hero.ace]
        except Exception as e:
            raise ValueError(f"Error loading {hero.name}") from e
    return heroes, alliances


def team_sort(team: Team) -> Tuple[float, int]:
    al = team.alliances
    return (sum(ta.total_size for ta in al.values()) / al.size, -al.size)


def short_str(team: Team) -> str:
    al = team.alliances
    return (
        f"Team({team.size},{al.size}):\n"
        f"  Team({len(al.team)}): {_str_heroes(al.team)}\n"
        f"  Mixed({len(al.mixed)}): {_str_heroes(al.mixed)}\n"
        + "  ".join(f"  {ta.alliance.name} {ta.level}" for ta in al.values())
    )


class UnderlordShell(cmd.Cmd):
    intro = (
        "Welcome to the Underlord team picker.\n" "Type help or ? to list commands.\n"
    )
    prompt = "> "

    def __init__(self, heroes: List[Hero], alliances: List[Alliance]) -> None:
        super().__init__()
        self.hero = {h.name: h for h in heroes}
        self.heroes = heroes
        self.alliance = {a.name: a for a in alliances}
        self.alliances = alliances
        self.team = None

    def do_info(self, arg):
        if arg.startswith("alliance ") or arg.startswith("a "):
            _, alliance = arg.split(maxsplit=1)
            try:
                print(self.alliance[alliance])
            except KeyError:
                print(f"Invalid alliance {alliance}")
                return
        elif arg.startswith("hero ") or arg.startswith("h "):
            _, hero = arg.split(maxsplit=1)
            try:
                print(self.hero[hero])
            except KeyError:
                print(f"Invalid hero {hero}")
                return
        else:
            team = self.team
            print(team)

    def do_team(self, arg):
        team = self.team
        if team is None:
            return
        ranks = collections.Counter(h.tier for h in team.alliances.team)
        print(" ".join(str(ranks[i]) for i in range(1, 6)))
        al = list(team.alliances)
        tier = 0
        for hero in sorted(team.alliances.team, key=hero_sort):
            if hero.tier > tier:
                tier = hero.tier
                print(f"{tier}:")
            al_index = (
                min(al.index(a) if a in al else len(al) for a in hero.alliances) + 1
            )
            print(f"  {al_index} {hero.name}")

    def do_alliance(self, arg):
        if arg:
            alliance, level, *_ = *arg.split(), None
            try:
                alliance = self.alliance[alliance]
            except KeyError:
                print(f"Invalid alliance {alliance}")
                return
            if level is None:
                team_inc(self.team, alliance)
            elif self.team is None:
                print("No team initialized")
            else:
                self.team.add(alliance, int(level))
            return

        if self.team is None:
            return

        teams = list(sorted(self.team.increase(fn=team_inc), key=team_sort))
        print("\n\n".join(short_str(team) for team in teams))
        print("\n" + short_str(self.team))

    def do_new(self, arg):
        self.team = GlobalTeam(self.alliances)

    def do_hero(self, arg):
        self.team.add_hero(self.hero[arg])


def main():
    heroes, alliances = load(
        {
            "Batrider",
            "Weaver",
            "Dazzle",
            "Slardar",
            "Shadow Demon",
            "Enigma",
            "Terrorblade",
            "Omniknight",
            "Necrophos",
            "Sand King",
        }
    )
    try:
        UnderlordShell(heroes, alliances).cmdloop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
