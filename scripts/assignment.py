#!/usr/bin/env python3
"""The assignment that gives every class a target of its own.

The solver is the Hungarian method in its shortest path form: every row is
given a column, and the total weight is the largest that can be reached.
The routine is checked against a brute force search in the test at the end
of the file, so that a mistake in the indices cannot pass unnoticed.
"""
import itertools


def hungarian(weight):
    """The columns that the rows take, with the largest total weight.

    ``weight`` is a square matrix.  The rows are the classes and the columns
    the targets.  The result is a list that gives, for every row, the column
    that the row takes.
    """
    n = len(weight)
    if n == 0:
        return []
    inf = float('inf')
    # the cost of the assignment is the weight that is given up
    cost = [[-weight[i][j] for j in range(n)] for i in range(n)]
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    # p[j] is the row that takes the column j, way[j] the column before it
    p = [0] * (n + 1)
    way = [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [inf] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = inf
            j1 = 0
            for j in range(1, n + 1):
                if used[j]:
                    continue
                current = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if current < minv[j]:
                    minv[j] = current
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    result = [-1] * n
    for j in range(1, n + 1):
        if p[j]:
            result[p[j] - 1] = j - 1
    return result


def best_assignment(weight, rows, columns):
    """The assignment of the rows to the columns, with the largest weight.

    The matrix is squared with rows that take no column and columns that no
    row takes, so that a class is never forced to a target that is not there.
    """
    n = max(len(rows), len(columns))
    matrix = [[0] * n for _ in range(n)]
    for i, row in enumerate(rows):
        for j, column in enumerate(columns):
            matrix[i][j] = weight.get((row, column), 0)
    # the extra columns on the right are only there to square the matrix
    assignment = hungarian(matrix)
    result = {}
    for i, row in enumerate(rows):
        j = assignment[i]
        if j < len(columns):
            result[row] = columns[j]
    return result


def _test():
    import random
    for size in range(1, 7):
        for _ in range(60):
            matrix = [[random.randint(0, 20) for _ in range(size)]
                      for _ in range(size)]
            result = hungarian(matrix)
            assert sorted(result) == list(range(size)), result
            total = sum(matrix[i][result[i]] for i in range(size))
            best = max(sum(matrix[i][p[i]] for i in range(size))
                       for p in itertools.permutations(range(size)))
            assert total == best, (size, total, best)
    print('assignment solver agrees with the brute force')


if __name__ == '__main__':
    _test()
