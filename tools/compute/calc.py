"""`compute calc`: a safe arithmetic evaluator so agents never do mental math.

Only numbers, named variables, + - * / // % **, parentheses, comparisons and a
small whitelist of functions are allowed. No attribute access, no subscripts,
no names other than the variables passed in, no imports. Exponents are capped.

    python -m tools compute calc "(rev26/rev23)**(1/3)-1" --var rev26=1075675 --var rev23=876396 --unit ratio
"""
from __future__ import annotations

import ast
import math
import operator

from ..common.errors import InputError
from ..common.provenance import derived

MAX_EXPONENT = 1000
MAX_ABS = 1e300
MAX_LEN = 2000

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_CMP = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne}


def _cagr(start: float, end: float, years: float) -> float:
    if start <= 0 or end <= 0 or years <= 0:
        raise CalcError("cagr() needs positive start, end and years")
    return (end / start) ** (1 / years) - 1


def _avg(*xs: float) -> float:
    if not xs:
        raise CalcError("avg() needs at least one value")
    return sum(xs) / len(xs)


FUNCTIONS = {
    "abs": abs, "min": min, "max": max, "round": round, "sqrt": math.sqrt, "log": math.log, "ln": math.log,
    "log10": math.log10, "exp": math.exp, "sum": lambda *xs: sum(xs), "avg": _avg, "cagr": _cagr,
}


class CalcError(InputError):
    pass


def evaluate(expr: str, variables: dict[str, float] | None = None) -> float:
    if len(expr) > MAX_LEN:
        raise CalcError("expression too long")
    variables = dict(variables or {})
    for k in variables:
        if not k.isidentifier() or k in FUNCTIONS:
            raise CalcError(f"bad variable name {k!r}")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise CalcError(f"syntax error: {e.msg}") from e

    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise CalcError(f"only numbers allowed, got {node.value!r}")
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise CalcError(f"unknown variable {node.id!r}; pass it with --var {node.id}=VALUE")
            return variables[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
                raise CalcError("exponent too large")
            try:
                out = _BIN[type(node.op)](left, right)
            except ZeroDivisionError as e:
                raise CalcError("division by zero") from e
            if isinstance(out, complex):
                raise CalcError("result is complex (negative base with fractional exponent)")
            return out
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _CMP:
            return 1.0 if _CMP[type(node.ops[0])](ev(node.left), ev(node.comparators[0])) else 0.0
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS and not node.keywords:
            args = [ev(a) for a in node.args]
            try:
                return FUNCTIONS[node.func.id](*args)
            except (ValueError, TypeError, OverflowError) as e:
                raise CalcError(f"{node.func.id}(): {e}") from e
        raise CalcError(f"not allowed: {type(node).__name__}")

    try:
        value = ev(tree)
    except OverflowError as e:
        raise CalcError("overflow") from e
    if isinstance(value, bool):
        value = float(value)
    if not isinstance(value, (int, float)) or math.isnan(value) or abs(value) > MAX_ABS:
        raise CalcError("result is not a finite number")
    return float(value)


def parse_vars(pairs: list[str] | None) -> dict[str, float]:
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise CalcError(f"--var needs NAME=VALUE, got {p!r}")
        k, v = p.split("=", 1)
        try:
            out[k.strip()] = float(v.replace(",", "").replace("_", ""))
        except ValueError as e:
            raise CalcError(f"--var {k}: {v!r} is not a number") from e
    return out


def cmd_calc(args) -> dict:
    variables = parse_vars(args.var)
    value = evaluate(args.expr, variables)  # CalcError -> status input_error, exit 2
    return {"expression": args.expr,
            "result": derived(value, args.unit, formula=args.expr, inputs={k: {"value": v, "unit": None} for k, v in variables.items()},
                              notes=args.label)}


def register(sub, leaf) -> None:
    p = leaf(sub, "calc", "Safe arithmetic: evaluate an expression with named inputs (use instead of mental math)")
    p.add_argument("expr", help="e.g. '(a-b)/b*100'; functions: " + ", ".join(sorted(FUNCTIONS)))
    p.add_argument("--var", action="append", help="NAME=VALUE (repeatable); cite each input's source in your own notes")
    p.add_argument("--unit", default=None, help="unit of the result, e.g. '%%', 'INR crore', 'x'")
    p.add_argument("--label", default=None, help="what this number is (copied to notes)")
    p.set_defaults(func=cmd_calc)
