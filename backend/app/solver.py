from collections.abc import Callable

import numpy as np

Report = Callable[[float, str], None]


class SolverError(Exception):
    pass


def build_system(params: dict) -> tuple[np.ndarray, np.ndarray]:
    if params["mode"] == "random":
        n = params["n"]
        rng = np.random.default_rng(params["seed"])
        return rng.uniform(-10, 10, (n, n)), rng.uniform(-10, 10, n)
    return np.array(params["a"], dtype=float), np.array(params["b"], dtype=float)


def gauss(a: np.ndarray, b: np.ndarray, report: Report) -> np.ndarray:
    n = len(b)
    m = np.hstack([a, b[:, None]])
    tol = n * np.finfo(float).eps * max(1.0, float(np.abs(a).max()))

    for k in range(n):
        pivot = k + int(np.argmax(np.abs(m[k:, k])))
        if abs(m[pivot, k]) <= tol:
            raise SolverError("Матриця вироджена: система не має єдиного розв'язку")
        if pivot != k:
            m[[k, pivot]] = m[[pivot, k]]
        factors = m[k + 1:, k] / m[k, k]
        m[k + 1:, k:] -= np.outer(factors, m[k, k:])
        remaining = (n - k - 1) / n
        report(5 + 85 * (1 - remaining ** 3), "Прямий хід методу Гауса")

    x = np.empty(n)
    for i in range(n - 1, -1, -1):
        x[i] = (m[i, n] - m[i, i + 1:n] @ x[i + 1:]) / m[i, i]
        if i % 100 == 0:
            report(90 + 8 * (n - i) / n, "Зворотний хід")

    if not np.all(np.isfinite(x)):
        raise SolverError("Розв'язок містить нескінченні значення: система погано обумовлена")
    return x


def solve(params: dict, report: Report) -> dict:
    report(0, "Підготовка системи")
    a, b = build_system(params)
    x = gauss(a, b, report)
    report(98, "Перевірка розв'язку")
    residual = float(np.linalg.norm(a @ x - b))
    return {"x": x.tolist(), "residual": residual}
