"""Small helpers for values interpolated into DuckDB SQL statements."""


def literal(value: object) -> str:
    """Quote a path or string as a SQL string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def identifier(value: str) -> str:
    """Quote a CSV column name as a SQL identifier."""
    return '"' + value.replace('"', '""') + '"'
