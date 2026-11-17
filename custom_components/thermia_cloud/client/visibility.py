"""Parser and evaluator for the cloud's register visibility conditions.

Examples (``docs/API-NOTES.md`` section 5)::

    {REG_DESIRED_SUPPLY_LINE_TEMP} >= 0
    {REG_OPER_TIME_HOT_WATER} > 0 AND {REG_OPER_TIME_HOT_WATER} < 65535

Grammar: ``or := and (OR and)*``, ``and := atom (AND atom)*``,
``atom := '(' or ')' | operand OP operand``, operands are ``{NAME}`` references or numbers,
``OP`` is one of ``= == != <> < <= > >=``. Only ``> >= =`` and ``AND`` are confirmed in real
data so far (roadmap P0.5); the rest is accepted defensively.

Policy: a reference that cannot be resolved makes its comparison *true* (visible) and is
reported in ``Evaluation.unresolved``.
"""

from __future__ import annotations

import operator
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

_TOKEN = re.compile(
    r"""\s*(?:
        (?P<ref>\{[A-Za-z0-9_]+\})
      | (?P<num>-?\d+(?:\.\d+)?)
      | (?P<op><=|>=|!=|<>|==|=|<|>)
      | (?P<paren>[()])
      | (?P<word>AND|OR)\b
    )""",
    re.VERBOSE | re.IGNORECASE,
)
_OPS: dict[str, Callable[[float, float], bool]] = {
    "=": operator.eq,
    "==": operator.eq,
    "!=": operator.ne,
    "<>": operator.ne,
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}

Resolver = Callable[[str], float | None]


class VisibilityParseError(ValueError):
    """The condition text is not valid in the grammar above."""


@dataclass(frozen=True, slots=True)
class Evaluation:
    visible: bool
    unresolved: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class _Ref:
    name: str


Operand = _Ref | float


@dataclass(frozen=True, slots=True)
class Compare:
    left: Operand
    op: str
    right: Operand

    def refs(self) -> frozenset[str]:
        return frozenset(o.name for o in (self.left, self.right) if isinstance(o, _Ref))

    def evaluate(self, resolve: Resolver) -> Evaluation:
        values: list[float] = []
        unresolved: set[str] = set()
        for operand in (self.left, self.right):
            if isinstance(operand, _Ref):
                value = resolve(operand.name)
                if value is None:
                    unresolved.add(operand.name)
                else:
                    values.append(value)
            else:
                values.append(operand)
        if unresolved:
            return Evaluation(True, frozenset(unresolved))
        return Evaluation(_OPS[self.op](values[0], values[1]))


@dataclass(frozen=True, slots=True)
class BoolOp:
    kind: str  # "AND" | "OR"
    terms: tuple[Node, ...]

    def refs(self) -> frozenset[str]:
        return frozenset().union(*(t.refs() for t in self.terms))

    def evaluate(self, resolve: Resolver) -> Evaluation:
        results = [t.evaluate(resolve) for t in self.terms]
        unresolved = frozenset().union(*(r.unresolved for r in results))
        flags = [r.visible for r in results]
        return Evaluation(all(flags) if self.kind == "AND" else any(flags), unresolved)


Node = Compare | BoolOp


@dataclass(frozen=True, slots=True)
class Condition:
    """A parsed condition."""

    text: str
    root: Node = field(repr=False)

    @property
    def refs(self) -> frozenset[str]:
        """Names of all referenced registers."""
        return self.root.refs()

    def evaluate(self, resolve: Resolver) -> Evaluation:
        return self.root.evaluate(resolve)

    def split(self, own_name: str) -> tuple[Node | None, Node | None]:
        """Split into ``(structural, value_based)`` parts for the register ``own_name``.

        Top-level ``AND`` terms are sorted by what they reference: terms that only look at
        the register itself are *value-based* (re-evaluated on every poll, they make the
        entity unavailable); terms that look at other registers are *structural*
        (evaluated at discovery, they decide whether the entity exists). A term that mixes
        both stays value-based, so it can never remove an entity.
        """
        terms = (
            self.root.terms
            if isinstance(self.root, BoolOp) and self.root.kind == "AND"
            else (self.root,)
        )
        structural = [t for t in terms if t.refs() - {own_name} and own_name not in t.refs()]
        value = [t for t in terms if t not in structural]
        return _join(structural), _join(value)


def _join(terms: list[Node]) -> Node | None:
    if not terms:
        return None
    return terms[0] if len(terms) == 1 else BoolOp("AND", tuple(terms))


def evaluate_node(node: Node | None, resolve: Resolver) -> Evaluation:
    """Evaluate a part returned by :meth:`Condition.split`; ``None`` means always visible."""
    return Evaluation(True) if node is None else node.evaluate(resolve)


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    text = text.rstrip()
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if match is None or match.end() == pos:
            raise VisibilityParseError(f"unexpected input at {pos}: {text[pos : pos + 12]!r}")
        kind = match.lastgroup or ""
        tokens.append((kind, match.group(kind).strip()))
        pos = match.end()
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self._tokens = tokens
        self._pos = 0

    def _peek(self) -> tuple[str, str] | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _next(self) -> tuple[str, str]:
        token = self._peek()
        if token is None:
            raise VisibilityParseError("unexpected end of condition")
        self._pos += 1
        return token

    def parse(self) -> Node:
        node = self._or()
        if self._peek() is not None:
            raise VisibilityParseError(f"unexpected token {self._peek()!r}")
        return node

    def _or(self) -> Node:
        terms = [self._and()]
        while self._is_word("OR"):
            self._next()
            terms.append(self._and())
        return terms[0] if len(terms) == 1 else BoolOp("OR", tuple(terms))

    def _and(self) -> Node:
        terms = [self._atom()]
        while self._is_word("AND"):
            self._next()
            terms.append(self._atom())
        return terms[0] if len(terms) == 1 else BoolOp("AND", tuple(terms))

    def _is_word(self, word: str) -> bool:
        token = self._peek()
        return token is not None and token[0] == "word" and token[1].upper() == word

    def _atom(self) -> Node:
        token = self._peek()
        if token == ("paren", "("):
            self._next()
            node = self._or()
            if self._next() != ("paren", ")"):
                raise VisibilityParseError("missing closing parenthesis")
            return node
        left = self._operand()
        kind, op = self._next()
        if kind != "op":
            raise VisibilityParseError(f"expected a comparison operator, got {op!r}")
        return Compare(left, op, self._operand())

    def _operand(self) -> Operand:
        kind, value = self._next()
        if kind == "ref":
            return _Ref(value[1:-1])
        if kind == "num":
            return float(value)
        raise VisibilityParseError(f"expected a register or number, got {value!r}")


def parse_condition(text: str) -> Condition:
    """Parse a condition; raises :class:`VisibilityParseError` when it is malformed."""
    tokens = _tokenize(text)
    if not tokens:
        raise VisibilityParseError("empty condition")
    return Condition(text, _Parser(tokens).parse())


class RegisterLookup:
    """Resolves references by name, preferring the register's own group.

    Names are not unique across groups (``REG_HEATING_HEAT_CURVE`` exists in two). A name that
    is ambiguous and not found in the own group is unresolved and listed in ``ambiguous``.
    """

    def __init__(self, registers: Iterable[tuple[str, str, float | None]]) -> None:
        self._by_name: dict[str, dict[str, float | None]] = {}
        for group, name, value in registers:
            self._by_name.setdefault(name, {})[group] = value
        self.ambiguous: set[str] = set()

    def resolver(self, own_group: str) -> Resolver:
        def resolve(name: str) -> float | None:
            groups: Mapping[str, float | None] = self._by_name.get(name, {})
            if own_group in groups:
                return groups[own_group]
            if len(groups) == 1:
                return next(iter(groups.values()))
            if groups:
                self.ambiguous.add(name)
            return None

        return resolve
