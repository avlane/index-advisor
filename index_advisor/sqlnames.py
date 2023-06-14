"""Quoting helpers for generated T-SQL."""


def quote_name(name):
    return "[%s]" % name.replace("]", "]]")


def quote_literal(value):
    return "N'%s'" % value.replace("'", "''")
