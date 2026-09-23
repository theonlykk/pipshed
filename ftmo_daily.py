"""FTMO calendar day helpers and daily snapshot derivations (ADR-159). Pure functions, no I/O."""


def ftmo_day_bounds_utc(day):
    raise NotImplementedError


def ftmo_day_of_utc(dt):
    raise NotImplementedError


def parse_ftmo_day(text):
    raise NotImplementedError


def snapshot_row_from_detail(detail):
    raise NotImplementedError


def derive_counts(events, scalps, start, end, account_login):
    raise NotImplementedError


def critical_groups(rows, now):
    raise NotImplementedError


def s4_counts(fill_rows, eject_tickets, day_of):
    raise NotImplementedError
