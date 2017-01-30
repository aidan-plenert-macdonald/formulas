#!/usr/bin/env python
# -*- coding: UTF-8 -*-
#
# Copyright 2016-2017 European Commission (JRC);
# Licensed under the EUPL (the 'Licence');
# You may not use this work except in compliance with the Licence.
# You may obtain a copy of the Licence at: http://ec.europa.eu/idabc/eupl

"""
Python equivalents of excel operators.
"""

import collections
from ..errors import FunctionError, RangeValueError
from ..tokens.operand import _re_range, _range2parts, _index2col
import schedula.utils as sh_utl
import functools
import itertools
import numpy as np


def not_implemeted(*args, **kwargs):
    raise FunctionError()


def _has_same_sheet(x, y):
    return x and y and x['excel'] == y['excel'] and x['sheet'] == y['sheet']


def _have_intersect(x, y):
    if _has_same_sheet(x, y):
        z = {'excel': x['excel'], 'sheet': x['sheet']}
        z['n1'], z['r1'] = max(y['n1'], x['n1']), max(int(y['r1']), int(x['r1']))
        z['n2'], z['r2'] = min(y['n2'], x['n2']), min(int(y['r2']), int(x['r2']))
        if z['r1'] <= z['r2'] and z['n1'] <= z['n2']:
            return z
    return {}


def _single_intersect(x, y):
    z = _have_intersect(x, y)
    if z:
        z['r1'], z['r2'] = str(z['r1']), str(z['r2'])
        return dict(_range2parts().dsp.dispatch(z, ['name', 'n1', 'n2']))
    return {}


def _split(base, range, intersect=None):
    z = _have_intersect(base, range)
    if not z:
        return range,

    if intersect is not None:
        intersect.update(z)

    ranges = []
    range = sh_utl.selector(('excel', 'sheet', 'n1', 'n2', 'r1', 'r2'), range)
    range['r1'], range['r2'] = int(range['r1']), int(range['r2'])
    for i in ('n1', 'n2', 'r1', 'r2'):
        if z[i] != range[i]:
            n = 1 - 2 * (int(i[1]) // 2)
            j = '%s%d' % (i[0], 2 - int(i[1]) // 2)
            r = sh_utl.combine_dicts(range, {j: z[i] - n})
            r['r1'], r['r2'] = str(r['r1']), str(r['r2'])
            r = dict(_range2parts().dsp.dispatch(r, ['name', 'n1', 'n2']))
            ranges.append(r)
            range[i] = z[i]

    return tuple(ranges)


def _intersect(range, ranges):
    it = map(functools.partial(_single_intersect, range), ranges)
    return tuple(r for r in it if r)


def _merge_update(base, rng):
    if _has_same_sheet(base, rng):
        if base['n1'] == rng['n2'] and int(base['r2']) + 1 >= int(rng['r1']):
            base['r2'] = rng['r2']
            return True


def _get_indices_intersection(base, i):
    r, c = int(base['r1']), int(base['n1'])
    r = range(int(i['r1']) - r, int(i['r2']) - r + 1)
    c = range(int(i['n1']) - c, int(i['n2']) - c + 1)
    return r, c


class References(object):
    def __init__(self, *tokens):
        self.tokens = tokens

    def push(self, *tokens):
        self.tokens += tokens

    @property
    def refs(self):
        return [t.name for t in self.tokens]

    @property
    def __name__(self):
        return '=(%s)' % ';'.join(self.refs)

    def __call__(self, named_refs, *args):
        func = functools.partial(self.get_ranges, named_refs)
        return list(map(func, self.refs))

    @staticmethod
    def get_ranges(named_refs, ref):
        try:
            return Ranges().push(named_refs[ref])
        except KeyError:
            return sh_utl.NONE


class Ranges(object):
    format_range = _range2parts().dsp.dispatch
    input_fields = ('excel', 'sheet', 'n1', 'n2', 'r1', 'r2')

    def __init__(self, ranges=(), values=None, is_set=False, all_values=True):
        self.ranges = ranges
        self.values = values or {}
        self.is_set = is_set
        self.all_values = all_values

    def pushes(self, refs, values=(), context=None):
        for r, v in itertools.zip_longest(refs, values, fillvalue=sh_utl.EMPTY):
            self.push(r, value=v, context=context)
        self.is_set = self.is_set or len(self.ranges) > 1
        return self

    def push(self, ref, value=sh_utl.EMPTY, context=None):
        context = context or {}
        m = _re_range.match(ref).groupdict().items()
        m = {k: v for k, v in m if v is not None}
        if 'ref' in m:
            raise ValueError
        i = sh_utl.combine_dicts(context, m)
        rng = self.format_range(i, ['name', 'n1', 'n2'])
        self.ranges += dict(rng),
        if value != sh_utl.EMPTY:
            self.values[rng['name']] = (rng, np.asarray(value))
        else:
            self.all_values = False
        return self

    def __add__(self, ranges):
        base = self.ranges
        for r0 in ranges.ranges:
            stack = [r0]
            for b in base:
                stack, s = [], stack.copy()
                for r in s:
                    stack.extend(_split(b, r))
            base += tuple(stack)
        values = sh_utl.combine_dicts(self.values, ranges.values)
        return Ranges(base, values, True, self.all_values and ranges.all_values)

    def __sub__(self, ranges):
        r = []
        for range in ranges.ranges:
            r.extend(_intersect(range, self.ranges))
        values = sh_utl.combine_dicts(self.values, ranges.values)
        is_set = self.is_set or ranges.is_set
        return Ranges(r, values, is_set, self.all_values and ranges.all_values)

    def simplify(self):
        rng = self.ranges
        it = range(min(r['n1'] for r in rng), max(r['n2'] for r in rng) + 1)
        it = ['{0}:{0}'.format(_index2col(c)) for c in it]
        simpl = (self - Ranges(is_set=False).pushes(it))._merge()
        simpl.all_values = self.all_values
        return simpl

    def _merge(self):
        key = lambda x: (x['n1'], int(x['r1']), -x['n2'], -int(x['r2']))
        stack = []
        for r in sorted(self.ranges, key=key):
            if not (stack and _merge_update(stack[-1], r)):
                if stack:
                    i = sh_utl.selector(self.input_fields, stack.pop())
                    stack.append(dict(self.format_range(i, ['name'])))
                stack.append(r)
        return Ranges(tuple(stack), self.values, self.is_set, self.all_values)

    def __repr__(self):
        ranges = ', '.join(r['name'] for r in self.ranges)
        return '<%s>(%s)' % (self.__class__.__name__, ranges)

    @property
    def value(self):
        if not self.all_values:
            raise RangeValueError(str(self))
        stack, values = list(self.ranges), []
        while stack:
            for k, (rng, value) in sorted(self.values.items()):
                if not stack:
                    break
                i = {}
                new_rngs = _split(rng, stack[-1], intersect=i)
                if i:
                    stack.pop()
                    stack.extend(new_rngs)
                    r, c = _get_indices_intersection(rng, i)
                    values.append(value[:, c][r])

        if self.is_set:
            return np.concatenate([v.ravel() for v in values])
        return values[0]


OPERATORS = collections.defaultdict(lambda: not_implemeted)
OPERATORS.update({
    '+': lambda x, y: x + y,
    '-': lambda x, y: x - y,
    'U-': lambda x: -x,
    '*': lambda x, y: x * y,
    '/': lambda x, y: x / y,
    '^': lambda x, y: x ** y,
    '<': lambda x, y: x < y,
    '<=': lambda x, y: x <= y,
    '>': lambda x, y: x > y,
    '>=': lambda x, y: x >= y,
    '=': lambda x, y: x == y,
    '<>': lambda x, y: x != y,
    '&': '{}{}'.format,
    '%': lambda x: x / 100.0,
    ',': lambda x, y: x + y,
    ' ': lambda x, y: x - y,
})