import unittest

from index_advisor.queries import parse_columns, parse_statement, split_identifiers


class ParseTest(unittest.TestCase):
    def test_simple_lists(self):
        self.assertEqual(parse_columns("[a], [b]"), ["a", "b"])
        self.assertEqual(parse_columns(None), [])
        self.assertEqual(parse_columns(""), [])

    def test_names_with_commas_dots_and_brackets(self):
        self.assertEqual(parse_columns("[last, first], [a.b], [x]]y]"), ["last, first", "a.b", "x]y"])

    def test_statement(self):
        self.assertEqual(parse_statement("[Sales].[dbo].[Orders]"), ("Sales", "dbo", "Orders"))
        self.assertEqual(parse_statement("[My.Db].[s]]x].[t]"), ("My.Db", "s]x", "t"))

    def test_text_between_identifiers_is_ignored(self):
        self.assertEqual(split_identifiers(" [a] , [b] "), ["a", "b"])
