# -*- coding: utf-8 -*-
"""
Графики по результатам апробации для текста ВКР.
Промпт-источник: claude_code_prompt_charts.md.

Числа зафиксированы по презентации (см. claude_code_prompt_charts.md).
figure_05 рассчитан из сырой анкеты по Способу B: (mean - 1) / 4 * 100.
Запуск:  python make_charts.py   ->  figure_01..06 (PNG 300dpi + SVG) рядом.
"""
import math
import sys
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import rcParams
from matplotlib.patches import Patch

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# --- палитра презентации -----------------------------------------------------
PURPLE = "#6B2BCC"        # основной акцент
PURPLE_LIGHT = "#C8A2DC"  # светлый фон, нейтральные элементы
PURPLE_BG = "#F2EBFB"     # совсем светлый фон
RED = "#C92A4D"           # критические точки, проблемы
DARK = "#2C2D2E"          # текст, оси
GRAY = "#606060"          # вторичный текст, подписи
WHITE = "#FFFFFF"

# --- шрифт: Golos Text, fallback на DejaVu Sans, если не установлен -----------
rcParams["font.family"] = "sans-serif"
rcParams["font.sans-serif"] = ["Golos Text", "DejaVu Sans"]
rcParams["font.size"] = 12
rcParams["axes.spines.top"] = False
rcParams["axes.spines.right"] = False
rcParams["axes.edgecolor"] = DARK
rcParams["axes.labelcolor"] = DARK
rcParams["xtick.color"] = GRAY
rcParams["ytick.color"] = GRAY
rcParams["text.color"] = DARK

OUT = Path(__file__).resolve().parent
saved = []


def rnd(x):
    """Округление половины вверх — для подписей значений в процентах."""
    return int(math.floor(x + 0.5))


def save(fig, name):
    for ext in ("png", "svg"):
        p = OUT / f"{name}.{ext}"
        fig.savefig(p, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    saved.append(name)
    print(f"  saved {name}.png + .svg")


def title(ax, text):
    ax.set_title(text, fontsize=14, fontweight="bold", color=DARK, pad=14)


def caption(fig, text):
    fig.text(0.5, -0.02, text, ha="center", fontsize=9.5, color=GRAY)


# =============================================================================
# График 1 — прирост знаний на сессию (горизонтальные парные бары)
# 7 участников с валидной парой pre/post. Михаил исключён из прироста
# (проходил курс ранее, pre 81% — несопоставимый базовый уровень).
# =============================================================================
def figure_01():
    pre = [4, 8, 17, 38, 25, 38, 19]
    post = [63, 71, 58, 100, 88, 94, 94]
    n = len(pre)
    y = np.arange(n)[::-1]
    h = 0.38

    fig, ax = plt.subplots(figsize=(10, 6))
    b_pre = ax.barh(y + h / 2, pre, height=h, color=GRAY, label="До сессии")
    b_post = ax.barh(y - h / 2, post, height=h, color=PURPLE, label="После сессии")

    for bars in (b_pre, b_post):
        for b in bars:
            w = b.get_width()
            ax.text(w + 1.5, b.get_y() + b.get_height() / 2, f"{w}%",
                    va="center", ha="left", fontsize=10, color=DARK)

    ax.set_yticks(y)
    ax.set_yticklabels([f"Участник {i + 1}" for i in range(n)])
    ax.set_xlim(0, 112)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel("% правильных ответов")
    ax.xaxis.grid(True, color=PURPLE_LIGHT, alpha=0.4, lw=0.8)
    ax.set_axisbelow(True)
    ax.set_title("Прирост знаний по результатам тестирования",
                 fontsize=14, fontweight="bold", color=DARK, pad=38)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2,
              frameon=False, fontsize=10)
    caption(fig, "7 участников · тест по материалам курса PersonaLab")
    save(fig, "figure_01_knowledge_gain")


# =============================================================================
# График 2 — восприятие участниками (radar по 6 шкалам, n=9)
# =============================================================================
PERCEPTION = [
    ("Полезность", 92),
    ("Темп", 89),
    ("Понятность", 81),
    ("Распознавание\nречи", 78),
    ("Доверие", 75),
    ("Реакция\nна стоп", 72),
]


def figure_02():
    labels = [l for l, _ in PERCEPTION]
    vals = [v for _, v in PERCEPTION]
    n = len(vals)
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
    vals_c = vals + vals[:1]
    angles_c = angles + angles[:1]

    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.plot(angles_c, vals_c, color=PURPLE, lw=2.2)
    ax.fill(angles_c, vals_c, color=PURPLE, alpha=0.3)

    ax.set_xticks(angles)
    ax.set_xticklabels(labels, fontsize=11, color=DARK)
    ax.set_ylim(0, 100)
    ax.set_yticks([25, 50, 75, 100])
    ax.set_yticklabels(["25", "50", "75", "100%"], fontsize=9, color=GRAY)
    ax.set_rlabel_position(180 / n)
    ax.grid(color=PURPLE_LIGHT, alpha=0.7)
    ax.spines["polar"].set_color(PURPLE_LIGHT)

    for ang, v in zip(angles, vals):
        ax.text(ang, v + 7, f"{v}%", ha="center", va="center",
                fontsize=10, fontweight="bold", color=PURPLE)

    ax.set_title("Восприятие системы участниками (n = 9)",
                 fontsize=14, fontweight="bold", color=DARK, pad=28)
    caption(fig, "нормировка Likert: (среднее − 1) / 4 × 100%")
    save(fig, "figure_02_perception_radar")


# =============================================================================
# График 2b — восприятие участниками (горизонтальный bar, альтернатива radar)
# =============================================================================
def figure_02b():
    items = sorted(PERCEPTION, key=lambda x: x[1])  # снизу вверх по возрастанию
    labels = [l.replace("\n", " ") for l, _ in items]
    vals = [v for _, v in items]
    y = np.arange(len(vals))

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.barh(y, vals, height=0.62, color=PURPLE)
    for b in bars:
        w = b.get_width()
        ax.text(w + 1.2, b.get_y() + b.get_height() / 2, f"{w}%",
                va="center", ha="left", fontsize=11, fontweight="bold", color=DARK)

    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=11)
    ax.set_xlim(0, 105)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel("% (нормировка Likert)")
    ax.xaxis.grid(True, color=PURPLE_LIGHT, alpha=0.4, lw=0.8)
    ax.set_axisbelow(True)
    title(ax, "Восприятие системы участниками (n = 9)")
    caption(fig, "нормировка Likert: (среднее − 1) / 4 × 100%")
    save(fig, "figure_02b_perception_bars")


# =============================================================================
# График 3 — mid-замер: вклад тьютора отдельно от вклада чтения (5 участников)
# =============================================================================
def figure_03():
    d_read = [0, -6, 19, 31, 56]
    d_tutor = [19, 69, 44, 25, 19]
    n = len(d_read)
    x = np.arange(n)
    w = 0.38

    fig, ax = plt.subplots(figsize=(10, 6))
    b1 = ax.bar(x - w / 2, d_read, w, color=PURPLE_LIGHT, label="После чтения")
    b2 = ax.bar(x + w / 2, d_tutor, w, color=PURPLE, label="После тьютора")

    for bars in (b1, b2):
        for b in bars:
            hh = b.get_height()
            ax.text(b.get_x() + b.get_width() / 2,
                    hh + (2 if hh >= 0 else -2), f"{hh:+d}",
                    ha="center", va="bottom" if hh >= 0 else "top",
                    fontsize=10, color=DARK)

    ax.axhline(0, color=DARK, ls="--", lw=1)
    ax.set_xticks(x)
    ax.set_xticklabels([f"Участник {i + 1}" for i in range(n)])
    ax.set_ylim(-10, 80)
    ax.set_ylabel("Δ, процентные пункты")
    ax.yaxis.grid(True, color=PURPLE_LIGHT, alpha=0.4, lw=0.8)
    ax.set_axisbelow(True)
    ax.legend(loc="upper center", ncol=2, frameon=False, fontsize=10,
              bbox_to_anchor=(0.5, 1.02))
    title(ax, "Вклад тьютора и вклад самостоятельного чтения")
    caption(fig, "Второй раунд апробации, n = 5, дизайн pre/mid/post")
    save(fig, "figure_03_mid_breakdown")


# =============================================================================
# График 4 — траектории Pre / Mid / Post (5 участников)
# =============================================================================
def figure_04():
    traj = {
        "П1": [81, 81, 100],
        "П2": [38, 31, 100],
        "П3": [25, 44, 88],
        "П4": [38, 69, 94],
        "П5": [19, 75, 94],
    }
    stages = ["Pre", "Mid\n(после чтения)", "Post\n(после тьютора)"]
    x = np.arange(3)
    shades = ["#3D1A75", "#5A23A3", "#7B3FD0", "#9457D9", "#B98FE0"]

    fig, ax = plt.subplots(figsize=(10, 6))
    for (name, vals), color in zip(traj.items(), shades):
        ax.plot(x, vals, "-o", color=color, lw=2.2, ms=8, label=name)

    ax.set_xticks(x)
    ax.set_xticklabels(stages)
    ax.set_xlim(-0.15, 2.15)
    ax.set_ylim(0, 105)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_ylabel("% правильных ответов")
    ax.yaxis.grid(True, color=PURPLE_LIGHT, alpha=0.4, lw=0.8)
    ax.set_axisbelow(True)
    ax.legend(loc="lower right", frameon=False, fontsize=10, title="Участник")
    title(ax, "Траектория обучения: pre → mid → post")
    caption(fig, "n = 5, второй раунд апробации")
    save(fig, "figure_04_trajectories")


# =============================================================================
# График 5 — сравнение версий системы (старая vs новая)
# Рассчитано из анкеты по Способу B: (mean - 1) / 4 * 100.
# Старая = первые 4 респондента без R5; новая = последние 5 респондентов.
# =============================================================================
def figure_05():
    scales = ["Понятность", "Темп", "Учёт сказанного",
              "Тон не как у робота", "Стабильность"]
    old = [62.5, 87.5, 31.25, 18.75, 18.75]   # n=4
    new = [95.0, 90.0, 100.0, 70.0, 60.0]     # n=5
    n = len(scales)
    y = np.arange(n)[::-1]
    h = 0.38

    fig, ax = plt.subplots(figsize=(10, 6))
    b_old = ax.barh(y + h / 2, old, height=h, color=GRAY, label="Старая версия")
    b_new = ax.barh(y - h / 2, new, height=h, color=PURPLE, label="Новая версия")

    for bars in (b_old, b_new):
        for b in bars:
            w = b.get_width()
            ax.text(w + 1.5, b.get_y() + b.get_height() / 2, f"{rnd(w)}%",
                    va="center", ha="left", fontsize=10, color=DARK)

    ax.set_yticks(y)
    ax.set_yticklabels(scales, fontsize=11)
    ax.set_xlim(0, 112)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel("% (нормировка Likert)")
    ax.xaxis.grid(True, color=PURPLE_LIGHT, alpha=0.4, lw=0.8)
    ax.set_axisbelow(True)
    ax.legend(loc="lower right", frameon=False, fontsize=10)
    title(ax, "Изменение восприятия между версиями системы")
    caption(fig, "n = 4 (старая), n = 5 (новая), нормировка Likert")
    save(fig, "figure_05_version_comparison")


# =============================================================================
# График 6 — внутренняя выборка vs публичный бенчмарк RuBQ
# =============================================================================
def figure_06():
    metrics = ["hit@1", "hit@3", "MRR", "nDCG@10"]
    personalab = [0.556, 0.704, 0.631, None]
    rubq = [0.608, 0.797, 0.711, 0.694]
    x = np.arange(len(metrics))
    w = 0.36

    fig, ax = plt.subplots(figsize=(10, 6))
    for xi, v in zip(x, personalab):
        if v is None:
            ax.text(xi - w / 2, 0.02, "—", ha="center", va="bottom",
                    fontsize=13, color=GRAY)
            continue
        ax.bar(xi - w / 2, v, w, color=PURPLE_LIGHT)
        ax.text(xi - w / 2, v + 0.015, f"{v:.3f}", ha="center",
                fontsize=9.5, color=DARK)
    for xi, v in zip(x, rubq):
        ax.bar(xi + w / 2, v, w, color=PURPLE)
        ax.text(xi + w / 2, v + 0.015, f"{v:.3f}", ha="center",
                fontsize=9.5, color=DARK)

    ax.set_xticks(x)
    ax.set_xticklabels(metrics)
    ax.set_ylim(0, 1.0)
    ax.set_ylabel("значение метрики")
    ax.yaxis.grid(True, color=PURPLE_LIGHT, alpha=0.4, lw=0.8)
    ax.set_axisbelow(True)
    ax.legend(handles=[Patch(color=PURPLE_LIGHT, label="PersonaLab (27 пар)"),
                       Patch(color=PURPLE, label="RuBQ полный (1692 / 56826)")],
              loc="upper left", frameon=False, fontsize=10)
    title(ax, "Внутренняя выборка vs публичный бенчмарк")
    caption(fig, "Согласованность retrieval-метрик подтверждает, "
                 "что внутренняя выборка — не аномалия")
    save(fig, "figure_06_internal_vs_rubq")


if __name__ == "__main__":
    figure_01()
    figure_02()
    figure_02b()
    figure_03()
    figure_04()
    figure_05()
    figure_06()
    print(f"\n{len(saved)} графиков -> {OUT}")
