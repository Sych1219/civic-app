"""
Normalization engine for transforming raw API responses into canonical datasets.
Uses JMESPath for field extraction with small helper functions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import jmespath


def _ensure_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _parse_number(value: str) -> Optional[float | int]:
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return None


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None
    return None


def _coerce_to_jmespath(expr: str) -> str:
    expr = (expr or "").strip()
    if not expr:
        return expr
    if expr == "$":
        return "@"
    if expr.startswith("$."):
        return expr[2:]
    if expr.startswith("$"):
        return expr[1:]
    return expr


def _jmespath_search(expr: str, data: Any) -> Any:
    if data is None or not expr:
        return None
    try:
        return jmespath.search(expr, data)
    except Exception:
        return None


def _split_args(text: str) -> List[str]:
    args: List[str] = []
    buf: List[str] = []
    depth = 0
    quote: Optional[str] = None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            buf.append(ch)
            if ch == quote and (i == 0 or text[i - 1] != "\\"):
                quote = None
            i += 1
            continue

        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            i += 1
            continue

        if ch == "(":
            depth += 1
            buf.append(ch)
            i += 1
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
            i += 1
            continue

        if ch == "," and depth == 0:
            arg = "".join(buf).strip()
            if arg:
                args.append(arg)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    if buf:
        arg = "".join(buf).strip()
        if arg:
            args.append(arg)
    return args


def _find_operator(expr: str, op: str) -> int:
    depth = 0
    quote: Optional[str] = None
    i = 0
    while i <= len(expr) - len(op):
        ch = expr[i]
        if quote:
            if ch == quote and (i == 0 or expr[i - 1] != "\\"):
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            i += 1
            continue
        if ch == "(":
            depth += 1
            i += 1
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            i += 1
            continue
        if depth == 0 and expr.startswith(op, i):
            return i
        i += 1
    return -1


def _split_condition(expr: str) -> Optional[Tuple[str, str, str]]:
    for op in (">=", "<=", "==", "!=", ">", "<"):
        idx = _find_operator(expr, op)
        if idx != -1:
            left = expr[:idx].strip()
            right = expr[idx + len(op) :].strip()
            return left, op, right
    return None


@dataclass
class ExpressionContext:
    data: Dict[str, Any]

    def get(self, path: str) -> Any:
        if not path:
            return None
        parts = [p for p in path.split(".") if p]
        value: Any = self.data
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return None
        return value


class ExpressionEvaluator:
    """
    Minimal evaluator for mapping expressions (JMESPath + helpers).
    """

    _custom_functions = ("concat", "if", "minutes_between")

    def eval(
        self,
        expr: str,
        row: Any,
        joins: Dict[str, Any],
        ctx: ExpressionContext,
        env: Dict[str, Any],
    ) -> Any:
        expr = (expr or "").strip()
        if not expr:
            return None

        if expr.startswith("ctx."):
            return ctx.get(expr[4:])

        if expr.startswith("join."):
            suffix = expr[5:]
            if "." in suffix:
                name, remainder = suffix.split(".", 1)
            else:
                name, remainder = suffix, ""
            join_item = joins.get(name)
            if remainder:
                remainder = _coerce_to_jmespath(remainder)
                return _jmespath_search(remainder, join_item)
            return join_item

        lower_expr = expr.lower()
        if any(lower_expr.startswith(f"{name}(") and expr.endswith(")") for name in self._custom_functions):
            name, args = self._parse_function(expr)
            return self._eval_function(name, args, row, joins, ctx, env)

        if expr.lower() in ("true", "false"):
            return expr.lower() == "true"

        if expr.lower() == "null":
            return None

        if expr[0] in ("'", '"') and expr[-1] == expr[0]:
            return _strip_quotes(expr)

        number = _parse_number(expr)
        if number is not None:
            return number

        if expr.startswith("$"):
            return _jmespath_search(_coerce_to_jmespath(expr), row)

        return _jmespath_search(expr, env)

    def _parse_function(self, expr: str) -> Tuple[str, List[str]]:
        idx = expr.find("(")
        name = expr[:idx].strip()
        args_str = expr[idx + 1 : -1].strip()
        args = _split_args(args_str) if args_str else []
        return name, args

    def _eval_function(
        self,
        name: str,
        args: List[str],
        row: Any,
        joins: Dict[str, Any],
        ctx: ExpressionContext,
        env: Dict[str, Any],
    ) -> Any:
        lowered = name.lower()
        if lowered == "concat":
            parts = [self.eval(arg, row, joins, ctx, env) for arg in args]
            return "".join("" if part is None else str(part) for part in parts)

        if lowered == "if":
            if len(args) < 2:
                return None
            condition = args[0]
            truthy = self._eval_condition(condition, row, joins, ctx, env)
            branch = args[1] if truthy else (args[2] if len(args) > 2 else None)
            if branch is None:
                return None
            return self.eval(branch, row, joins, ctx, env)

        if lowered == "minutes_between":
            if len(args) < 2:
                return None
            start = self.eval(args[0], row, joins, ctx, env)
            end = self.eval(args[1], row, joins, ctx, env)
            start_dt = _parse_datetime(start)
            end_dt = _parse_datetime(end)
            if not start_dt or not end_dt:
                return None
            return (end_dt - start_dt).total_seconds() / 60.0

        return None

    def _eval_condition(
        self,
        expr: str,
        row: Any,
        joins: Dict[str, Any],
        ctx: ExpressionContext,
        env: Dict[str, Any],
    ) -> bool:
        expr = (expr or "").strip()
        if not expr:
            return False

        split = _split_condition(expr)
        if not split:
            return bool(self.eval(expr, row, joins, ctx, env))

        left_expr, op, right_expr = split
        left = self.eval(left_expr, row, joins, ctx, env)
        right = self.eval(right_expr, row, joins, ctx, env)

        try:
            if op == ">":
                return left > right
            if op == "<":
                return left < right
            if op == ">=":
                return left >= right
            if op == "<=":
                return left <= right
            if op == "==":
                return left == right
            if op == "!=":
                return left != right
        except Exception:
            return False
        return False


class NormalizationEngine:
    """
    Applies mapping configs to raw API responses, producing canonical datasets.
    """

    def __init__(self, *, evaluator: ExpressionEvaluator | None = None):
        self.evaluator = evaluator or ExpressionEvaluator()

    def normalize(self, raw: Dict[str, Any], mapping: Dict[str, Any], *, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if not isinstance(mapping, dict):
            raise ValueError("mapping must be a dict")

        output = mapping.get("output") or {}
        columns = output.get("columns") or []

        list_expr = mapping.get("listExpr")
        if not list_expr:
            source = mapping.get("source") or {}
            list_expr = source.get("listPath")
        if not list_expr:
            raise ValueError("mapping.listExpr (or mapping.source.listPath) is required")

        items = _ensure_list(_jmespath_search(_coerce_to_jmespath(str(list_expr)), raw))

        joins_config = mapping.get("joins") or []
        join_indexes = self._build_join_indexes(raw, joins_config)

        ctx_data: Dict[str, Any] = {"now": datetime.now(timezone.utc).isoformat()}
        if context:
            ctx_data.update(context)
        ctx = ExpressionContext(data=ctx_data)

        mappings = mapping.get("mappings") or []
        if isinstance(mappings, dict):
            mappings = [{"to": key, "expr": value} for key, value in mappings.items()]
        rows: List[Dict[str, Any]] = []
        for item in items:
            join_matches = self._resolve_joins(item, join_indexes)
            env: Dict[str, Any] = {"root": raw}
            if isinstance(raw, dict):
                env.update(raw)
            if isinstance(item, dict):
                env.update(item)
            row_output: Dict[str, Any] = {}
            for entry in mappings:
                target = entry.get("to")
                expr = entry.get("expr")
                if not target or expr is None:
                    continue
                value = self.evaluator.eval(str(expr), item, join_matches, ctx, env)
                row_output[target] = value
            rows.append(row_output)

        return {
            "columns": columns,
            "rows": rows,
            "meta": mapping.get("meta") or {},
        }

    def _build_join_indexes(self, raw: Dict[str, Any], joins_config: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        join_indexes: Dict[str, Dict[str, Any]] = {}
        for join in joins_config:
            name = join.get("name")
            from_path = join.get("fromPath")
            from_key = join.get("fromKey")
            to_key = join.get("toKey")
            if not name or not from_path or not from_key or not to_key:
                continue

            items = _ensure_list(_jmespath_search(_coerce_to_jmespath(str(from_path)), raw))
            index: Dict[str, Any] = {}
            for item in items:
                key_value = _jmespath_search(_coerce_to_jmespath(str(from_key)), item)
                if isinstance(key_value, list) and key_value:
                    key_value = key_value[0]
                if key_value is None:
                    continue
                index[str(key_value)] = item
            join_indexes[name] = {"index": index, "toKey": str(to_key)}
        return join_indexes

    def _resolve_joins(self, row: Any, join_indexes: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        results: Dict[str, Any] = {}
        for name, info in join_indexes.items():
            to_key = info.get("toKey")
            if not to_key:
                results[name] = None
                continue
            key_value = _jmespath_search(_coerce_to_jmespath(str(to_key)), row)
            if isinstance(key_value, list) and key_value:
                key_value = key_value[0]
            if key_value is None:
                results[name] = None
                continue
            match = info.get("index", {}).get(str(key_value))
            results[name] = match
        return results
