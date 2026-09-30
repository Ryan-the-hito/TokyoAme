#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""TokyoAme —— 《你是东京更好的老天爷吗？》像素风天气小游戏

画面：下方是东京（东京塔 + 街景 + 砖块地面），上方是一条从左往右连续滑动的天气条。
玩法：点击屏幕（或按空格），东京塔正上方那一格天气，就是今天的天气；
     一关 = 一个月，一共 12 关（1 月到 12 月），越往后滑得越快。
     每累计 7 天下雨（小雨、大雨都算，连续或不连续都算）失去 1 颗星，
     5 颗星全部失去（累计 35 天雨）就游戏结束。星星会带到下一关，不会恢复。

所有画面都画在一张画布上，坐标用"像素格"（基准 320×214 格），窗口缩放时尽量按整数倍放大，
像素保持方正清晰；文字用系统默认字体，按实际分辨率画在像素画上面。
界面语言：English（默认）/ 中文 / 日本語，翻译文件在 i18n/ 目录（gen_ts.py 生成 + lrelease 编译）。
"""

import sys
import os
import json
import math
import random
import calendar
import datetime
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QWidget, QFileDialog
from PyQt6.QtCore import (Qt, QTimer, QElapsedTimer, QRectF, QPointF, QEvent, QUrl,
                          QCoreApplication, QTranslator)
from PyQt6.QtGui import QPainter, QColor, QImage, QFont, QFontMetricsF, QIcon, QPixmap, QGuiApplication

try:    # 背景音乐（没有 QtMultimedia 时游戏照常运行，只是没有音乐）
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
except Exception:
    QMediaPlayer = None
    QAudioOutput = None


NAME = 'TokyoAme'
VERSION = '1.0.0'

_FONT_CACHE = {}

TOKYOAME_APP_DATA_DIR = os.path.join(str(Path.home()), 'TokyoAmeAppPath')
TOKYOAME_SETTINGS_PATH = os.path.join(TOKYOAME_APP_DATA_DIR, 'settings.json')
TOKYOAME_SAVE_PATH = os.path.join(TOKYOAME_APP_DATA_DIR, 'save.json')
TOKYOAME_RECORDS_PATH = os.path.join(TOKYOAME_APP_DATA_DIR, 'records.json')

# 字体：现在先用系统默认字体。以后想换可爱字体，只改这一行即可，
# 比如 'Yuanti SC'（圆体）或 'Hiragino Maru Gothic ProN'（丸ゴシック）。
FONT_FAMILY = ''


# ── 界面语言（Qt Linguist）─────────────────────────────────────────
# 源文字是英文；中文 / 日文由 i18n/tokyoame_<lang>.qm 提供。设置面板里切换，立即生效。
UI_LANGUAGES = (('en', 'English'), ('zh_CN', '中文'), ('ja_JP', '日本語'))
_TRANSLATORS = []   # 保持引用，Qt 不负责它们的生命周期
# 汉字的后备字体跟着界面语言走：日文用日文字形，中文用简体字形（否则会按系统语言顺序乱配）
CJK_FALLBACK_FONTS = {
    'en': ['Hiragino Sans', 'PingFang SC'],
    'ja_JP': ['Hiragino Sans', 'Hiragino Kaku Gothic ProN', 'Yu Gothic', 'Noto Sans CJK JP'],
    'zh_CN': ['PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Noto Sans CJK SC'],
}
_UI_LANG = 'en'


def _tr(text: str) -> str:
    return QCoreApplication.translate(NAME, text)


def N_(text: str) -> str:
    """只做标记：表格里的字符串先用 N_() 标出来给 i18n/gen_ts.py 提取，显示时再 _tr()。"""
    return text


def _resource_dirs(sub: str) -> list:
    """资源子目录（i18n / music）的候选位置：打包后的 app 里、源码旁边。"""
    candidates = []
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', '')
        if meipass:
            candidates.append(os.path.join(meipass, sub))
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidates.append(os.path.join(exe_dir, '..', 'Resources', sub))
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), sub))
    return candidates


def _i18n_dirs() -> list:
    return _resource_dirs('i18n')


def find_resource(sub: str, name: str):
    for folder in _resource_dirs(sub):
        path = os.path.join(folder, name)
        if os.path.exists(path):
            return path
    return None


def apply_ui_language(code: str) -> bool:
    """换界面语言：先卸掉旧翻译，再装新的。英文是源语言，不需要翻译文件。"""
    global _UI_LANG
    qt_app = QCoreApplication.instance()
    if qt_app is None:
        return False
    _UI_LANG = code if code in dict(UI_LANGUAGES) else 'en'
    _FONT_CACHE.clear()
    while _TRANSLATORS:
        qt_app.removeTranslator(_TRANSLATORS.pop())
    if code not in dict(UI_LANGUAGES) or code == 'en':
        return True
    translator = QTranslator(qt_app)
    for folder in _i18n_dirs():
        qm_path = os.path.join(folder, 'tokyoame_%s.qm' % code)
        if os.path.exists(qm_path) and translator.load(qm_path):
            qt_app.installTranslator(translator)
            _TRANSLATORS.append(translator)
            return True
    return False


# ── 游戏参数 ─────────────────────────────────────────────────
LEVEL_COUNT = 12                # 关卡数：一关 = 一个月，1 月到 12 月
STAR_COUNT = 5                  # 星星 = 体力
RAIN_DAYS_PER_STAR = 7          # 每累计 7 天雨失去 1 颗星（5 × 7 = 35 天雨就结束）

ART_W = 320                     # 像素画布基准尺寸（单位：像素格）
ART_H = 214

BASE_SPEED_FIRST = 70.0 / 3     # 第 1 关基础滚动速度（像素格/秒）
BASE_SPEED_LAST = 250.0 / 3     # 第 12 关基础滚动速度（再经过上限柔性压缩）
SPEED_PERCENT_MIN = 60          # 设置里的速度倍率范围（百分比）
SPEED_PERCENT_MAX = 130
SPEED_PERCENT_STEP = 5
SOFT_CAP_KNEE = 0.8             # 速度到达上限的 80% 之后开始柔性压缩，永远碰不到上限
STRIP_HALF_SPAN = 1000.0        # 天气条以东京塔正上方为原点，左右各生成这么远（像素格），与窗口宽度无关

# 三种难度：速度系数、云朵宽度、最短停留时间（=可玩性下限）、雨云比例、每天经过几朵云
MODE_ORDER = ('easy', 'normal', 'hard')
MODES = {
    'easy': {
        'label': N_('Easy'), 'desc': N_('Slower, bigger clouds, less rain, more time each day'),
        'speed_mul': 0.82, 'tile_w': 50.0, 'min_dwell': 0.62,
        'rain_first': 0.22, 'rain_last': 0.30, 'day_clouds': (6.5, 5.0),
    },
    'normal': {
        'label': N_('Normal'), 'desc': N_('Standard speed and rain'),
        'speed_mul': 1.00, 'tile_w': 44.0, 'min_dwell': 0.50,
        'rain_first': 0.30, 'rain_last': 0.40, 'day_clouds': (6.0, 4.6),
    },
    'hard': {
        'label': N_('Hard'), 'desc': N_('Faster, smaller clouds, more rain, less time each day'),
        'speed_mul': 1.18, 'tile_w': 40.0, 'min_dwell': 0.42,
        'rain_first': 0.38, 'rain_last': 0.50, 'day_clouds': (5.8, 4.4),
    },
}

# 天气种类：显示名、是否算下雨、云朵相对宽度（晴天最窄，最难点中）
WEATHER_ORDER = ('sunny', 'partly', 'cloudy', 'light_rain', 'heavy_rain', 'snow')
WEATHER_INFO = {
    'sunny': {'label': N_('Sunny'), 'rain': False, 'width': 0.86},
    'partly': {'label': N_('Partly cloudy'), 'rain': False, 'width': 0.96},
    'cloudy': {'label': N_('Cloudy'), 'rain': False, 'width': 1.04},
    'light_rain': {'label': N_('Light rain'), 'rain': True, 'width': 1.00},
    'heavy_rain': {'label': N_('Heavy rain'), 'rain': True, 'width': 1.16},
    'snow': {'label': N_('Snow'), 'rain': False, 'width': 0.96},
}
DRY_WEIGHTS = (('sunny', 0.34), ('partly', 0.26), ('cloudy', 0.24), ('snow', 0.16))
HEAVY_RAIN_SHARE = 0.4          # 雨云里大雨占的比例
WEATHER_PERSIST = 0.3           # 天气会"连着来"：以这个概率延续上一朵的晴/雨属性

# 分数：每天按天气加分，每过一关加分，通关再加奖励；最后按难度乘系数
SCORE_PER_DAY = {'sunny': 10, 'partly': 6, 'snow': 5, 'cloudy': 3, 'light_rain': 0, 'heavy_rain': 0}
SCORE_LEVEL_CLEAR = 100
SCORE_VICTORY = 500
SCORE_STAR = 100                # 通关时每颗剩下的星星
SCORE_MODE_MUL = {'easy': 0.8, 'normal': 1.0, 'hard': 1.3}
RECORDS_MAX = 300               # 排行榜最多保留多少局（超出时去掉分数最低的）

# 背景音乐：music/ 目录里的文件（来源与许可见 music/CREDITS.md）。缺文件时自动不放。
MUSIC_TRACKS = {'menu': 'menu.ogg', 'game': 'game.ogg'}
MUSIC_VOLUME = 0.45
MUSIC_CREDIT = '"Flowerbed Fields" (CC0) & "Sideways City" (CC BY 4.0) by Zane Little — opengameart.org'

# 天气日记（整局每天的天气）存进纪录时用的单字母编码
DIARY_CODES = {'sunny': 'S', 'partly': 'P', 'cloudy': 'C', 'light_rain': 'r', 'heavy_rain': 'R', 'snow': 'W'}
DIARY_KINDS = {code: kind for kind, code in DIARY_CODES.items()}

MONTH_ABBR = (N_('Jan'), N_('Feb'), N_('Mar'), N_('Apr'), N_('May'), N_('Jun'),
              N_('Jul'), N_('Aug'), N_('Sep'), N_('Oct'), N_('Nov'), N_('Dec'))
WEEKDAY_ABBR = (N_('Mon'), N_('Tue'), N_('Wed'), N_('Thu'), N_('Fri'), N_('Sat'), N_('Sun'))

# ── 像素配色（整体风格都在这里调）──────────────────────────────────
PAL = {
    'ol': '#1d1d35',            # 描边 / 主文字
    'ink_soft': '#4a4a6a',
    'paper': '#fff7e6',         # 面板底色（奶油色）
    'white': '#fcfcfc',
    'shade': '#a4e4fc',         # 白云阴影（浅蓝）
    'grey1': '#dcdce4', 'grey2': '#a8a8b8', 'grey3': '#7c7c90', 'grey4': '#56566c',
    'sun1': '#fce0a8', 'sun2': '#f8b800', 'sun3': '#e45c10',
    'drop': '#3cbcfc', 'drop2': '#0078f8',
    'blush': '#f8a4c0',
    'btn': '#fcfcfc', 'btn_hover': '#fff1c8',
    'accent': '#e45c10', 'accent_hi': '#fc9838', 'accent_lo': '#a83000', 'accent_hover': '#f87838',
    'blue': '#3cbcfc', 'blue_lo': '#0078f8',
    'danger': '#e40058',
    'star': '#f8b800', 'star_hi': '#fce0a8', 'star_empty': '#bcbcc8',
    'tower_red': '#d82800', 'tower_red_d': '#a01000', 'tower_white': '#fcfcfc', 'tower_white_d': '#d0c8c0',
    'fuji': '#7890d8', 'fuji_ol': '#4a5aa8',
    'far_city': '#a8bce0', 'near_city': '#7890b8', 'window_on': '#fce0a8', 'window_off': '#56688c',
    'bush': '#00a800', 'bush_hi': '#80d010',
    'grass': '#80d010', 'grass_d': '#00a800',
    'brick': '#c84c0c', 'brick_mortar': '#5c1c00', 'brick_hi': '#fc9838',
    'sky_title_top': '#5c94fc', 'sky_title_bottom': '#b4d4fc',
}

# 每种天气下东京的天空（上端颜色, 下端颜色）与画面蒙色
SKY_COLORS = {
    'sunny': ('#5c94fc', '#9cc4fc'),
    'partly': ('#6c9cf0', '#a8c8f0'),
    'cloudy': ('#8e9cb8', '#bcc4d4'),
    'light_rain': ('#6d7fa6', '#9eaac4'),
    'heavy_rain': ('#3c4870', '#6c7896'),
    'snow': ('#a8b8d8', '#dce4f4'),
}
SCENE_TINT = {
    'sunny': (0, 0, 0, 0),
    'partly': (0, 0, 0, 0),
    'cloudy': (60, 70, 96, 40),
    'light_rain': (30, 40, 80, 56),
    'heavy_rain': (20, 24, 56, 96),
    'snow': (255, 255, 255, 36),
}


# ── 规则与数值（纯逻辑，不依赖界面，方便测试和移植）──────────────────────
def clamp(value, low, high):
    return max(low, min(high, value))


def clamp_speed_percent(value) -> int:
    value = int(round(value / SPEED_PERCENT_STEP) * SPEED_PERCENT_STEP)
    return int(clamp(value, SPEED_PERCENT_MIN, SPEED_PERCENT_MAX))


def lerp(a, b, t):
    return a + (b - a) * t


def soft_cap(value: float, cap: float) -> float:
    """速度上限的柔性压缩：膝点以下原样，膝点以上平滑地逼近上限但永远到不了。"""
    knee = cap * SOFT_CAP_KNEE
    if value <= knee:
        return value
    span = cap - knee
    return knee + span * (1.0 - math.exp(-(value - knee) / span))


def level_params(level: int, mode: str, speed_percent: int) -> dict:
    """某一关在某个难度、某个速度倍率下的全部数值。
    速度：只对第 1 关和第 12 关做上限压缩，中间线性插值——每关都明显更快，且永远不超过上限。
    每天限时：按"每天会经过几朵云"来定，速度倍率只改变节奏，不改变每天有几次选择。"""
    cfg = MODES.get(mode, MODES['normal'])
    level = int(clamp(level, 1, LEVEL_COUNT))
    t = (level - 1) / max(1, LEVEL_COUNT - 1)
    mul = cfg['speed_mul'] * clamp_speed_percent(speed_percent) / 100.0
    narrowest = cfg['tile_w'] * min(info['width'] for info in WEATHER_INFO.values())
    speed_cap = narrowest / cfg['min_dwell']
    speed_first = soft_cap(BASE_SPEED_FIRST * mul, speed_cap)
    speed_last = soft_cap(BASE_SPEED_LAST * mul, speed_cap)
    speed = lerp(speed_first, speed_last, t)
    clouds_per_day = lerp(cfg['day_clouds'][0], cfg['day_clouds'][1], t)
    return {
        'level': level,
        'speed': speed,
        'speed_cap': speed_cap,
        'tile_w': cfg['tile_w'],
        'narrowest_w': narrowest,
        'min_dwell': narrowest / speed,
        'rain_ratio': lerp(cfg['rain_first'], cfg['rain_last'], t),
        'clouds_per_day': clouds_per_day,
        'day_limit': clouds_per_day * cfg['tile_w'] / speed,
    }


def compute_score(counts: dict, levels_cleared: int, victory: bool, stars: int, mode: str) -> int:
    base = sum(SCORE_PER_DAY[kind] * int(counts.get(kind, 0)) for kind in WEATHER_ORDER)
    base += int(levels_cleared) * SCORE_LEVEL_CLEAR
    if victory:
        base += SCORE_VICTORY + int(stars) * SCORE_STAR
    return int(math.floor(base * SCORE_MODE_MUL.get(mode, 1.0) + 0.5))


def encode_diary(months: list) -> str:
    """[[当月每天的天气], ...] → 'SPC...|SrR...'（未知的月份写成 '?'）。"""
    return '|'.join('?' if month is None else ''.join(DIARY_CODES[k] for k in month) for month in months)


def decode_diary(text: str) -> list:
    months = []
    for chunk in str(text or '').split('|') if text else []:
        if chunk == '?':
            months.append(None)
        else:
            months.append([DIARY_KINDS[c] for c in chunk if c in DIARY_KINDS])
    return months


def level_month(start_year: int, level: int):
    """第 level 关对应的年、月（第 1 关 = 1 月 …… 第 12 关 = 12 月）。"""
    index = level - 1
    return start_year + index // 12, index % 12 + 1


def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


class Mulberry32:
    """很小的可移植随机数发生器：同一个种子在 Python 和 JavaScript 里得到完全相同的序列，
    以后做网页版时，同一局的天空可以一模一样。"""

    MASK = 0xFFFFFFFF

    def __init__(self, seed: int):
        self.state = int(seed) & self.MASK

    def next_u32(self) -> int:
        m = self.MASK
        self.state = (self.state + 0x6D2B79F5) & m
        t = self.state
        t = ((t ^ (t >> 15)) * (t | 1)) & m
        t = ((t + (((t ^ (t >> 7)) * (t | 61)) & m)) & m) ^ t
        return (t ^ (t >> 14)) & m

    def random(self) -> float:
        return self.next_u32() / 4294967296.0


def next_weather_kind(rng, prev_kind, rain_ratio: float) -> str:
    if prev_kind is not None and rng.random() < WEATHER_PERSIST:
        want_rain = WEATHER_INFO[prev_kind]['rain']
    else:
        want_rain = rng.random() < rain_ratio
    if want_rain:
        return 'heavy_rain' if rng.random() < HEAVY_RAIN_SHARE else 'light_rain'
    roll = rng.random() * sum(weight for _, weight in DRY_WEIGHTS)
    for kind, weight in DRY_WEIGHTS:
        roll -= weight
        if roll <= 0:
            return kind
    return DRY_WEIGHTS[-1][0]


class WeatherTile:
    __slots__ = ('kind', 'x', 'w', 'used', 'uid')

    def __init__(self, kind: str, x: float, w: float, uid: int):
        self.kind = kind
        self.x = x          # 左边缘（相对天气条左端，单位：像素格）
        self.w = w
        self.used = False   # 已经被选中、落到东京了
        self.uid = uid

    @property
    def center(self) -> float:
        return self.x + self.w / 2.0


class WeatherStrip:
    """从左往右连续滚动的天气条。云朵首尾相接，任何时刻正上方都恰好有一朵。
    坐标以东京塔正上方为 0；开局一次性生成左右各 half_span 范围内的云，之后只从左边补新云。
    窗口多宽只影响画出来多少，不影响生成顺序——同一个种子、同一段时间，经过正上方的云完全相同。"""

    def __init__(self, rng, base_w: float, rain_ratio: float, half_span: float = STRIP_HALF_SPAN):
        self.rng = rng
        self.base_w = base_w
        self.rain_ratio = rain_ratio
        self.half_span = half_span
        self._uid = 0
        self._prev_kind = None
        self.max_w = base_w * max(info['width'] for info in WEATHER_INFO.values())
        self.tiles = [self._new_tile(self.half_span + self.max_w)]
        self._fill()

    def _new_tile(self, right_edge: float) -> WeatherTile:
        kind = next_weather_kind(self.rng, self._prev_kind, self.rain_ratio)
        self._prev_kind = kind
        w = self.base_w * WEATHER_INFO[kind]['width']
        self._uid += 1
        return WeatherTile(kind, right_edge - w, w, self._uid)

    def _fill(self):
        while self.tiles[0].x > -self.half_span - self.max_w:
            self.tiles.insert(0, self._new_tile(self.tiles[0].x))

    def advance(self, dx: float):
        for tile in self.tiles:
            tile.x += dx
        while len(self.tiles) > 1 and self.tiles[-1].x > self.half_span + self.max_w:
            self.tiles.pop()
        self._fill()

    def tile_at(self, x: float = 0.0):
        for tile in self.tiles:
            if tile.x <= x < tile.x + tile.w:
                return tile
        return None

    def nearest_unused(self, x: float = 0.0, reach: float = None):
        """离 x 最近、还没被选过的云（只在 reach 范围内找，也就是屏幕上看得到的那些）。"""
        best = None
        for tile in self.tiles:
            if tile.used or (reach is not None and abs(tile.center - x) > reach):
                continue
            if best is None or abs(tile.center - x) < abs(best.center - x):
                best = tile
        return best


class GameSession:
    """一局游戏的全部状态：关卡、星星、累计雨天、每天的天气。可以存成 JSON，再原样读回来。"""

    SAVE_VERSION = 2

    def __init__(self, mode: str = 'normal', start_year: int = None, seed: int = None):
        self.mode = mode if mode in MODES else 'normal'
        self.start_year = start_year if start_year is not None else datetime.date.today().year
        self.seed = (seed if seed is not None else random.randrange(1, 1 << 31)) & 0xFFFFFFFF
        self.level = 1
        self.rain_total = 0
        self.counts = {kind: 0 for kind in WEATHER_ORDER}
        self.days_played = 0
        self.levels_cleared = 0
        self.month_days = []
        self.history = []            # 已经定完的每个月（None = 旧存档里没有记录的月份）
        self.game_over = False
        self.victory = False

    @property
    def stars(self) -> int:
        return max(0, STAR_COUNT - self.rain_total // RAIN_DAYS_PER_STAR)

    @property
    def rain_progress(self) -> int:
        """距离下一次失去星星，已经累计了几天雨（0~6）。"""
        return self.rain_total % RAIN_DAYS_PER_STAR

    @property
    def year_month(self):
        return level_month(self.start_year, self.level)

    @property
    def days_in_level(self) -> int:
        year, month = self.year_month
        return days_in_month(year, month)

    @property
    def day_index(self) -> int:
        """今天是这个月的第几天（从 0 开始）。"""
        return len(self.month_days)

    @property
    def level_done(self) -> bool:
        return len(self.month_days) >= self.days_in_level

    def level_rng(self) -> Mulberry32:
        return Mulberry32(self.seed ^ ((self.level * 0x9E3779B1) & 0xFFFFFFFF))

    def assign(self, kind: str) -> dict:
        """把 kind 定为今天的天气，返回这一步引发的事件。"""
        events = {'rain': False, 'star_lost': False, 'game_over': False, 'level_done': False, 'victory': False}
        if self.game_over or self.victory or self.level_done:
            return events
        self.month_days.append(kind)
        self.counts[kind] += 1
        self.days_played += 1
        if WEATHER_INFO[kind]['rain']:
            events['rain'] = True
            self.rain_total += 1
            if self.rain_total % RAIN_DAYS_PER_STAR == 0:
                events['star_lost'] = True
            if self.stars <= 0:
                self.game_over = True
                events['game_over'] = True
                return events
        if self.level_done:
            events['level_done'] = True
            self.levels_cleared = self.level
            if self.level >= LEVEL_COUNT:
                self.victory = True
                events['victory'] = True
        return events

    def next_level(self) -> bool:
        if self.game_over or self.victory or not self.level_done or self.level >= LEVEL_COUNT:
            return False
        self.history.append(list(self.month_days))
        self.level += 1
        self.month_days = []
        return True

    @property
    def score(self) -> int:
        return compute_score(self.counts, self.levels_cleared, self.victory, self.stars, self.mode)

    def diary(self) -> list:
        """整局每个月每天的天气（含当前这个月已经定下的部分）。"""
        return [None if month is None else list(month) for month in self.history] + [list(self.month_days)]

    def result(self) -> dict:
        year, month = self.year_month
        return {
            'mode': self.mode,
            'level': self.level,
            'levels_cleared': self.levels_cleared,
            'year': year,
            'month': month,
            'rain_total': self.rain_total,
            'sunny_total': self.counts['sunny'],
            'counts': dict(self.counts),
            'days_played': self.days_played,
            'victory': self.victory,
            'stars': self.stars,
            'score': self.score,
            'start_year': self.start_year,
            'diary': encode_diary(self.diary()),
        }

    def to_dict(self) -> dict:
        return {
            'version': self.SAVE_VERSION,
            'mode': self.mode,
            'start_year': self.start_year,
            'seed': self.seed,
            'level': self.level,
            'rain_total': self.rain_total,
            'counts': dict(self.counts),
            'days_played': self.days_played,
            'levels_cleared': self.levels_cleared,
            'month_days': list(self.month_days),
            'history': [None if month is None else list(month) for month in self.history],
            'victory': self.victory,
        }

    @classmethod
    def from_dict(cls, data):
        """从存档恢复；任何字段不对劲就整个作废（返回 None），不会带着坏数据开局。
        版本 1 的存档没有整局历史，读进来后之前的月份记为"未知"。"""
        def is_count(value):
            return isinstance(value, int) and not isinstance(value, bool) and value >= 0

        try:
            if not isinstance(data, dict) or data.get('version') not in (1, cls.SAVE_VERSION):
                return None
            mode = data.get('mode')
            if not isinstance(mode, str) or mode not in MODES:
                return None
            for key in ('start_year', 'seed', 'level', 'rain_total', 'days_played', 'levels_cleared'):
                if not is_count(data.get(key)):
                    return None
            session = cls(mode, start_year=data['start_year'], seed=data['seed'])
            if not 1900 <= session.start_year <= 9999 or not 1 <= data['level'] <= LEVEL_COUNT:
                return None
            session.level = data['level']

            def valid_month(month, days):
                return (isinstance(month, list) and len(month) <= days
                        and all(isinstance(k, str) and k in WEATHER_INFO for k in month))
            if not valid_month(data.get('month_days'), session.days_in_level):
                return None
            session.month_days = list(data['month_days'])
            history = data.get('history') if data['version'] >= 2 else [None] * (session.level - 1)
            if not isinstance(history, list) or len(history) != session.level - 1:
                return None
            for i, month in enumerate(history):
                if month is None:
                    continue
                days = days_in_month(*level_month(session.start_year, i + 1))
                if not valid_month(month, days) or len(month) != days:
                    return None
            session.history = [None if month is None else list(month) for month in history]
            counts = data.get('counts')
            if not isinstance(counts, dict):
                return None
            for kind in WEATHER_ORDER:
                if not is_count(counts.get(kind, 0)):
                    return None
                session.counts[kind] = counts.get(kind, 0)
            session.rain_total = data['rain_total']
            session.days_played = data['days_played']
            session.levels_cleared = data['levels_cleared']
            # 交叉核对：各项计数必须和关卡、天数、每天的天气对得上
            rain_in_counts = session.counts['light_rain'] + session.counts['heavy_rain']
            if session.rain_total != rain_in_counts or session.days_played != sum(session.counts.values()):
                return None
            earlier_days = sum(days_in_month(*level_month(session.start_year, m)) for m in range(1, session.level))
            if session.days_played != earlier_days + len(session.month_days):
                return None
            known = [k for month in session.history if month is not None for k in month] + session.month_days
            if None not in session.history:
                if any(session.counts[k] != known.count(k) for k in WEATHER_ORDER):
                    return None
            elif any(session.counts[k] < known.count(k) for k in WEATHER_ORDER):
                return None
            if session.levels_cleared != session.level - 1 + int(session.level_done):
                return None
            if session.stars <= 0:
                return None
            # 通关标记不信文件，按关卡和天数推出来；文件里写了却对不上的直接作废
            derived_victory = session.level == LEVEL_COUNT and session.level_done
            if data.get('victory') is True and not derived_victory:
                return None
            session.victory = derived_victory
            return session
        except Exception:
            return None


# ── 存储：设置 / 存档 ──────────────────────────────────────────────
def ensure_tokyoame_data_dir() -> None:
    os.makedirs(TOKYOAME_APP_DATA_DIR, exist_ok=True)


def default_settings() -> dict:
    return {
        'language': 'en',          # en / zh_CN / ja_JP
        'mode': 'normal',          # easy / normal / hard
        'speed_percent': 100,      # 滚动速度倍率（有上限保护）
        'day_timer': True,         # 每天限时：时间到了，正上方的天气自动成为今天的天气
        'music': True,             # 背景音乐（主页右上角、设置里都能开关，快捷键 M）
        'best_by_mode': {mode: 0 for mode in MODE_ORDER},   # 各难度最佳纪录：到达的关卡（13 = 全部通关）
        'best_sunny': 0,
        'games_played': 0,
    }


def _safe_int(value, default: int, low: int, high: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return default
        return int(clamp(int(number), low, high))
    except Exception:
        return default


def load_settings() -> dict:
    settings = default_settings()
    try:
        with open(TOKYOAME_SETTINGS_PATH, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except Exception:
        return settings
    if not isinstance(data, dict):
        return settings
    language = data.get('language')
    if isinstance(language, str) and language in dict(UI_LANGUAGES):
        settings['language'] = language
    mode = data.get('mode')
    if isinstance(mode, str) and mode in MODES:
        settings['mode'] = mode
    settings['speed_percent'] = clamp_speed_percent(_safe_int(data.get('speed_percent'), 100, -10 ** 6, 10 ** 6))
    if isinstance(data.get('day_timer'), bool):
        settings['day_timer'] = data['day_timer']
    if isinstance(data.get('music'), bool):
        settings['music'] = data['music']
    best = data.get('best_by_mode')
    if isinstance(best, dict):
        for mode_key in MODE_ORDER:
            settings['best_by_mode'][mode_key] = _safe_int(best.get(mode_key, 0), 0, 0, LEVEL_COUNT + 1)
    settings['best_sunny'] = _safe_int(data.get('best_sunny', 0), 0, 0, 10 ** 6)
    settings['games_played'] = _safe_int(data.get('games_played', 0), 0, 0, 10 ** 9)
    return settings


def write_json_atomic(path: str, data) -> bool:
    """先写临时文件再替换：写到一半出错也不会把原来的文件弄坏。"""
    tmp_path = path + '.tmp'
    try:
        ensure_tokyoame_data_dir()
        with open(tmp_path, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
        return True
    except Exception:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        return False


def save_settings(settings: dict) -> bool:
    return write_json_atomic(TOKYOAME_SETTINGS_PATH, settings)


def save_game(session: GameSession) -> bool:
    """把当前一局写进存档（每定一天、暂停、回主页、关窗口时都会自动存；暂停菜单里也能手动存）。"""
    data = session.to_dict()
    data['saved_at'] = datetime.datetime.now().isoformat(timespec='seconds')
    return write_json_atomic(TOKYOAME_SAVE_PATH, data)


def load_game():
    """读存档；没有存档、存档坏了、或者那一局已经结束，都返回 None。"""
    try:
        with open(TOKYOAME_SAVE_PATH, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except Exception:
        return None
    return GameSession.from_dict(data)


def clear_save() -> None:
    try:
        os.remove(TOKYOAME_SAVE_PATH)
    except Exception:
        pass


# ── 排行榜：每一局结束（游戏结束或全部通关）都记一条 ─────────────────────────
RECORD_INT_KEYS = ('level', 'levels_cleared', 'score', 'stars', 'rain_total', 'sunny_total', 'days_played', 'start_year')


def _clean_record(item):
    if not isinstance(item, dict):
        return None
    try:
        record = {'id': str(item['id']), 'finished_at': str(item['finished_at']), 'mode': item['mode'],
                  'victory': item.get('victory') is True, 'diary': str(item.get('diary', ''))}
        if record['mode'] not in MODES:
            return None
        for key in RECORD_INT_KEYS:
            value = item[key]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                return None
            record[key] = value
        counts = item.get('counts', {})
        record['counts'] = {k: int(counts.get(k, 0)) if isinstance(counts.get(k, 0), int) else 0 for k in WEATHER_ORDER}
        if not 1 <= record['level'] <= LEVEL_COUNT:
            return None
        return record
    except Exception:
        return None


def load_records() -> list:
    try:
        with open(TOKYOAME_RECORDS_PATH, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [r for r in (_clean_record(item) for item in data) if r is not None]


def make_record(result: dict) -> dict:
    now = datetime.datetime.now()
    return {
        'id': '{0}-{1}'.format(now.strftime('%Y%m%d%H%M%S%f'), random.randrange(1 << 16)),
        'finished_at': now.isoformat(timespec='seconds'),
        'mode': result['mode'],
        'victory': bool(result['victory']),
        'level': int(result['level']),
        'levels_cleared': int(result['levels_cleared']),
        'score': int(result['score']),
        'stars': int(result['stars']),
        'rain_total': int(result['rain_total']),
        'sunny_total': int(result['sunny_total']),
        'days_played': int(result['days_played']),
        'start_year': int(result['start_year']),
        'counts': dict(result['counts']),
        'diary': result.get('diary', ''),
    }


def add_record(record: dict) -> list:
    """记下一局，返回更新后的全部纪录。超过上限时去掉分数最低的旧纪录（新的这条永远保留）。"""
    records = load_records()
    records.append(record)
    while len(records) > RECORDS_MAX:
        victim = min((r for r in records if r['id'] != record['id']), key=lambda r: (r['score'], r['finished_at']))
        records.remove(victim)
    write_json_atomic(TOKYOAME_RECORDS_PATH, records)
    return records


# 排行榜的几种排法：分数 / 关卡 / 晴天数 / 最近
LEADERBOARD_SORTS = ('score', 'level', 'sunny', 'recent')


def record_level_value(record: dict) -> int:
    return LEVEL_COUNT + 1 if record.get('victory') else record['level']


def sort_records(records: list, key: str, mode: str = 'all') -> list:
    rows = [r for r in records if mode == 'all' or r['mode'] == mode]
    if key == 'level':
        rows.sort(key=lambda r: (-record_level_value(r), -r['score'], r['finished_at']))
    elif key == 'sunny':
        rows.sort(key=lambda r: (-r['sunny_total'], -r['score'], r['finished_at']))
    elif key == 'recent':
        rows.sort(key=lambda r: r['finished_at'], reverse=True)
    else:
        rows.sort(key=lambda r: (-r['score'], r['finished_at']))
    return rows


# ── 显示用文字 ─────────────────────────────────────────────────
def month_name(month: int) -> str:
    return _tr(MONTH_ABBR[month - 1])


def weekday_name(year: int, month: int, day: int) -> str:
    return _tr(WEEKDAY_ABBR[calendar.weekday(year, month, day)])


def format_date(year: int, month: int, day: int) -> str:
    return _tr('{mon} {d} ({wd})').format(mon=month_name(month), m=month, d=day,
                                           wd=weekday_name(year, month, day), y=year)


def format_year_month(year: int, month: int) -> str:
    return _tr('{mon} {y}').format(mon=month_name(month), m=month, y=year)


def mode_label(mode: str) -> str:
    return _tr(MODES.get(mode, MODES['normal'])['label'])


def best_label(level: int) -> str:
    if level > LEVEL_COUNT:
        return _tr('All clear')
    return _tr('Level {n}').format(n=level)


def format_score(value: int) -> str:
    return '{0:,}'.format(int(value))


def format_finished_at(text: str) -> str:
    try:
        return datetime.datetime.fromisoformat(text).strftime('%Y-%m-%d %H:%M')
    except Exception:
        return str(text)[:16]


# ── 像素素材（逐格生成，纯 Python，方便以后移植）──────────────────────────
_COLOR_CACHE = {}


def C(value) -> QColor:
    """颜色缓存：'#rrggbb' 或 (r, g, b, a) → QColor。"""
    if isinstance(value, QColor):
        return value
    color = _COLOR_CACHE.get(value)
    if color is None:
        color = QColor(*value) if isinstance(value, tuple) else QColor(value)
        _COLOR_CACHE[value] = color
    return color


class Grid:
    """一张小像素图：每格一个颜色（None = 透明）。"""

    def __init__(self, w: int, h: int):
        self.w, self.h = int(w), int(h)
        self.px = [[None] * self.w for _ in range(self.h)]

    def set(self, x, y, color):
        x, y = int(x), int(y)
        if 0 <= x < self.w and 0 <= y < self.h:
            self.px[y][x] = color

    def to_image(self) -> QImage:
        image = QImage(max(1, self.w), max(1, self.h), QImage.Format.Format_ARGB32)
        image.fill(0)
        for y, row in enumerate(self.px):
            for x, color in enumerate(row):
                if color is not None:
                    image.setPixelColor(x, y, C(color))
        return image


def _mask(w: int, h: int, inside) -> list:
    return [[bool(inside(x + 0.5, y + 0.5)) for x in range(w)] for y in range(h)]


def _is_edge(mask, x, y) -> bool:
    h, w = len(mask), len(mask[0]) if mask else 0
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = x + dx, y + dy
        if not (0 <= nx < w and 0 <= ny < h) or not mask[ny][nx]:
            return True
    return False


def _cloud_inside(w: int, h: int):
    circles = ((0.27, 0.58, 0.19, 0.31), (0.53, 0.40, 0.23, 0.40), (0.75, 0.52, 0.17, 0.30))
    r = 0.27 * h

    def inside(x, y):
        u, v = x / w, y / h
        if 0.45 <= v <= 1.0:
            if x < r and y > h - r and (x - r) ** 2 + (y - (h - r)) ** 2 > r * r:
                return False
            if x > w - r and y > h - r and (x - (w - r)) ** 2 + (y - (h - r)) ** 2 > r * r:
                return False
            return 0.0 <= u <= 1.0
        for cu, cv, ru, rv in circles:
            if ((u - cu) / ru) ** 2 + ((v - cv) / rv) ** 2 <= 1.0:
                return True
        return False
    return inside


def paint_cloud(g: Grid, ox: int, oy: int, w: int, h: int, face: str, shade: str, outline: str):
    w, h = max(4, int(w)), max(3, int(h))
    mask = _mask(w, h, _cloud_inside(w, h))
    for y in range(h):
        for x in range(w):
            if not mask[y][x]:
                continue
            if _is_edge(mask, x, y):
                color = outline
            elif y >= h * 0.72:
                color = shade
            else:
                color = face
            g.set(ox + x, oy + y, color)


def paint_face(g: Grid, cx: int, cy: int, mood: str):
    """可爱小脸：两只眼睛 + 腮红 + 嘴巴（happy / meh / sad）。"""
    eye, blush = PAL['ol'], PAL['blush']
    for dy in (0, 1):
        g.set(cx - 3, cy + dy, eye)
        g.set(cx + 2, cy + dy, eye)
    for dx in (-5, -4, 3, 4):
        g.set(cx + dx, cy + 2, blush)
    if mood == 'happy':
        for x, y in ((cx - 2, cy + 2), (cx + 1, cy + 2), (cx - 1, cy + 3), (cx, cy + 3)):
            g.set(x, y, eye)
    elif mood == 'sad':
        for x, y in ((cx - 2, cy + 3), (cx + 1, cy + 3), (cx - 1, cy + 2), (cx, cy + 2)):
            g.set(x, y, eye)
    else:
        g.set(cx - 1, cy + 3, eye)
        g.set(cx, cy + 3, eye)


def paint_sun(g: Grid, cx: float, cy: float, r: float, rays: bool = True):
    for y in range(int(cy - r - 1), int(cy + r + 2)):
        for x in range(int(cx - r - 1), int(cx + r + 2)):
            d = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
            if d <= r:
                if d > r - 1.0:
                    color = PAL['sun3']
                elif (x + 0.5 - cx) + (y + 0.5 - cy) < -r * 0.6:
                    color = PAL['sun1']
                else:
                    color = PAL['sun2']
                g.set(x, y, color)
    if rays:
        for i in range(8):
            a = math.pi * 2 * i / 8
            for k in (r + 2, r + 3):
                g.set(int(round(cx - 0.5 + math.cos(a) * k)), int(round(cy - 0.5 + math.sin(a) * k)),
                      PAL['sun3'] if i % 2 else PAL['sun2'])


def weather_grid(kind: str, w: int, h: int) -> Grid:
    """天气小图（像素格）。h >= 18 时带表情，更小的只画外形（用于日历）。"""
    w, h = max(6, int(w)), max(5, int(h))
    g = Grid(w, h)
    big = h >= 18
    if kind == 'sunny':
        paint_sun(g, w / 2, h / 2, min(w, h) * (0.30 if big else 0.28), rays=True)
        if big:
            paint_face(g, w // 2, h // 2 - 1, 'happy')
    elif kind == 'partly' and not big:
        # 小图：太阳大一点、云小一点，两样都看得出
        paint_sun(g, w * 0.66, h * 0.36, min(w, h) * 0.30, rays=False)
        paint_cloud(g, 0, int(h * 0.42), int(w * 0.74), h - int(h * 0.42), PAL['white'], PAL['shade'], PAL['ol'])
    elif kind == 'partly':
        paint_sun(g, w * 0.64, h * 0.34, min(w, h) * 0.22, rays=big)
        cw, ch = int(w * 0.74), int(h * 0.52)
        ox, oy = int(w * 0.05), int(h * 0.40)
        paint_cloud(g, ox, oy, cw, ch, PAL['white'], PAL['shade'], PAL['ol'])
        if big:
            paint_face(g, ox + cw // 2, oy + int(ch * 0.48), 'happy')
    elif kind == 'cloudy' and not big:
        # 小图：只画一朵居中的灰云（两朵叠在一起太小会糊成一团）
        cw, ch = int(w * 0.94), int(h * 0.72)
        paint_cloud(g, (w - cw) // 2, (h - ch) // 2, cw, ch, PAL['grey1'], PAL['grey2'], PAL['ol'])
    elif kind == 'cloudy':
        paint_cloud(g, int(w * 0.36), int(h * 0.12), int(w * 0.58), int(h * 0.44), PAL['grey1'], PAL['grey2'], PAL['ol'])
        cw, ch = int(w * 0.80), int(h * 0.58)
        ox, oy = int(w * 0.03), int(h * 0.30)
        paint_cloud(g, ox, oy, cw, ch, PAL['grey1'], PAL['grey2'], PAL['ol'])
        if big:
            paint_face(g, ox + cw // 2, oy + int(ch * 0.5), 'meh')
    elif kind in ('light_rain', 'heavy_rain'):
        heavy = kind == 'heavy_rain'
        cw, ch = int(w * 0.88), int(h * 0.58)
        ox, oy = (w - cw) // 2, 0 if heavy else int(h * 0.04)
        paint_cloud(g, ox, oy, cw, ch, PAL['grey3'] if heavy else PAL['grey1'],
                    PAL['grey4'] if heavy else PAL['grey2'], PAL['ol'])
        if big:
            paint_face(g, ox + cw // 2, oy + int(ch * 0.48), 'sad' if heavy else 'meh')
        count = (5 if heavy else 3) if big else (3 if heavy else 2)
        length = (6 if heavy else 3) if big else (3 if heavy else 2)
        top = oy + ch + 1
        for i in range(count):
            x = int(ox + cw * (i + 0.8) / (count + 0.4))
            y0 = top + (i % 2) * (2 if big else 1)
            for k in range(length):
                g.set(x - k // 3, y0 + k, PAL['drop2'] if heavy or k == length - 1 else PAL['drop'])
    elif kind == 'snow':
        cw, ch = int(w * 0.86), int(h * 0.58)
        ox, oy = (w - cw) // 2, int(h * 0.04)
        paint_cloud(g, ox, oy, cw, ch, PAL['white'], PAL['shade'], PAL['ol'])
        if big:
            paint_face(g, ox + cw // 2, oy + int(ch * 0.48), 'happy')
        count = 3 if big else 2
        for i in range(count):
            x = int(ox + cw * (i + 0.7) / (count + 0.4))
            y = oy + ch + 2 + (i % 2) * (3 if big else 1)
            for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
                g.set(x + dx, y + dy, PAL['white'] if (dx, dy) == (0, 0) else PAL['blue'])
    return g


def star_grid(size: int, filled: bool) -> Grid:
    g = Grid(size, size)
    c = size / 2.0
    r = size / 2.0

    def inside(x, y):
        angle = math.atan2(y - c, x - c) + math.pi / 2
        seg = (angle % (2 * math.pi / 5)) / (2 * math.pi / 5)
        tri = abs(seg - 0.5) * 2
        rr = lerp(r * 0.45, r, tri ** 1.6)
        return math.hypot(x - c, y - c) <= rr
    mask = _mask(size, size, inside)
    for y in range(size):
        for x in range(size):
            if not mask[y][x]:
                continue
            if _is_edge(mask, x, y):
                color = PAL['ol']
            elif not filled:
                color = PAL['star_empty']
            elif x + y < size * 0.8:
                color = PAL['star_hi']
            else:
                color = PAL['star']
            g.set(x, y, color)
    return g


def drop_grid(w: int, h: int, color: str) -> Grid:
    g = Grid(w, h)

    def inside(x, y):
        cx, cy, r = w / 2.0, h - w / 2.0, w / 2.0
        if y >= cy:
            return math.hypot(x - cx, y - cy) <= r
        return abs(x - cx) <= r * (y / cy) ** 1.1
    mask = _mask(w, h, inside)
    for y in range(h):
        for x in range(w):
            if mask[y][x]:
                g.set(x, y, PAL['ol'] if _is_edge(mask, x, y) else color)
    return g


def tower_half_width(height: float, t: float) -> float:
    """东京塔在高度比例 t（0=塔脚，0.8=塔身顶端）处的半宽。"""
    return height * (0.20 * max(0.0, 1 - t / 0.8) ** 2.2 + 0.018)


def tower_grid(H: int) -> Grid:
    """像素东京塔：红白相间的塔身 + 格构斜纹 + 两层展望台 + 天线。"""
    H = max(20, int(H))
    W = int(H * 0.44) + 5
    if W % 2 == 0:
        W += 1
    g = Grid(W, H)
    cx = W // 2
    mask = [[False] * W for _ in range(H)]
    for y in range(H):
        t = (H - 1 - y) / H
        if t > 0.8:
            continue
        hw = tower_half_width(H, t)
        for x in range(W):
            if abs(x - cx) <= hw:
                mask[y][x] = True
    aw, ah = H * 0.12, H * 0.13
    for y in range(H):
        for x in range(W):
            dx = (x - cx) / aw
            if abs(dx) < 1 and (H - 1 - y) < ah * (1 - dx * dx):
                mask[y][x] = False
    for y in range(H):
        band = int(((H - 1 - y) / H) / 0.08)
        for x in range(W):
            if not mask[y][x]:
                continue
            if _is_edge(mask, x, y):
                color = PAL['ol']
            else:
                lattice = (x - cx + y) % 4 == 0 or (x - cx - y) % 4 == 0
                if band % 2 == 0:
                    color = PAL['tower_red_d'] if lattice else PAL['tower_red']
                else:
                    color = PAL['tower_white_d'] if lattice else PAL['tower_white']
            g.set(x, y, color)

    def deck(t, width_scale, deck_h):
        y0 = int(H - 1 - H * t)
        hw = tower_half_width(H, t) * width_scale
        x0, x1 = int(cx - hw), int(cx + hw)
        for y in range(y0 - deck_h, y0 + 1):
            for x in range(x0, x1 + 1):
                edge = y in (y0 - deck_h, y0) or x in (x0, x1)
                g.set(x, y, PAL['ol'] if edge else (PAL['blue'] if y == y0 - deck_h + 2 else PAL['tower_white']))

    deck(0.36, 1.5, max(4, int(H * 0.05)))
    deck(0.62, 1.8, max(3, int(H * 0.03)))
    top = int(H - 1 - H * 0.8)
    for y in range(0, top + 1):
        g.set(cx, y, PAL['tower_red'] if (y // 3) % 2 == 0 else PAL['tower_white'])
        if y > top * 0.4:
            g.set(cx - 1, y, PAL['ol'])
            g.set(cx + 1, y, PAL['ol'])
    g.set(cx, 0, '#ff3b30')
    return g


def skytree_grid(H: int) -> Grid:
    H = max(20, int(H))
    W = max(9, int(H * 0.1) | 1)
    g = Grid(W, H)
    cx = W // 2
    color = PAL['far_city']
    for y in range(H):
        t = (H - 1 - y) / H
        hw = lerp(H * 0.045, H * 0.012, t / 0.78) if t < 0.78 else 0.5
        for x in range(W):
            if abs(x - cx) <= hw + 0.2:
                g.set(x, y, color)
    for t, ww, hh in ((0.56, 0.036, 3), (0.74, 0.028, 2)):
        y0 = int(H - 1 - H * t)
        for y in range(y0 - hh, y0 + 1):
            for x in range(int(cx - H * ww), int(cx + H * ww) + 1):
                g.set(x, y, color)
    return g


def fuji_grid(half_w: int, height: int) -> Grid:
    half_w = max(6, int(half_w))
    W, H = half_w * 2 + 1, max(8, int(height))
    g = Grid(W, H)
    cx = half_w
    plateau = max(2, int(half_w * 0.12))
    for y in range(H):
        hw = plateau + (half_w - plateau) * ((y / (H - 1)) ** 0.85)
        for x in range(W):
            dx = abs(x - cx)
            if dx > hw:
                continue
            snow_line = H * 0.3 + (2 if (x // 3) % 2 == 0 else 0)
            if dx > hw - 1 or y == 0:
                color = PAL['fuji_ol']
            elif y < snow_line:
                color = PAL['white']
            else:
                color = PAL['fuji']
            g.set(x, y, color)
    return g


def bush_grid(w: int, h: int) -> Grid:
    g = Grid(w, h)
    paint_cloud(g, 0, 0, w, h, PAL['bush_hi'], PAL['bush'], PAL['ol'])
    return g


def big_cloud_grid(w: int) -> Grid:
    g = Grid(w, int(w * 0.5))
    paint_cloud(g, 0, 0, w, int(w * 0.5), PAL['white'], PAL['shade'], PAL['ol'])
    return g


def brick_grid() -> Grid:
    g = Grid(16, 8)
    for y in range(8):
        for x in range(16):
            color = PAL['brick']
            if y in (3, 7):
                color = PAL['brick_mortar']
            elif y < 3 and x in (7, 15):
                color = PAL['brick_mortar']
            elif y > 3 and x in (3, 11):
                color = PAL['brick_mortar']
            elif y in (0, 4):
                color = PAL['brick_hi']
            g.set(x, y, color)
    return g


class SpriteCache:
    """生成过的像素图只生成一次。"""

    def __init__(self):
        self._images = {}

    def get(self, key, builder) -> QImage:
        image = self._images.get(key)
        if image is None:
            if len(self._images) > 400:
                self._images.clear()
            image = builder().to_image()
            self._images[key] = image
        return image

    def weather(self, kind: str, w: int, h: int) -> QImage:
        w, h = int(w), int(h)
        return self.get(('weather', kind, w, h), lambda: weather_grid(kind, w, h))

    def star(self, size: int, filled: bool) -> QImage:
        return self.get(('star', size, filled), lambda: star_grid(size, filled))

    def drop(self, w: int, h: int, color: str) -> QImage:
        return self.get(('drop', w, h, color), lambda: drop_grid(w, h, color))


SPRITES = SpriteCache()


def build_scene_image(w: int, h: int, ground_y: int, tower_x: int, tower_h: int, fuji_x: int) -> QImage:
    """整幅东京街景（不含天空和天气效果）：富士山、远景楼、晴空塔、近景楼、灌木、东京塔、砖块地面。"""
    image = QImage(max(1, w), max(1, h), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    p = QPainter(image)
    fuji = SPRITES.get(('fuji', min(70, w // 4), min(58, int(tower_h * 0.55))),
                       lambda: fuji_grid(min(70, w // 4), min(58, int(tower_h * 0.55))))
    p.drawImage(int(fuji_x - fuji.width() // 2), ground_y - fuji.height(), fuji)
    rng = random.Random(3)
    x = -3
    while x < w:
        bw, bh = rng.randint(9, 20), rng.randint(18, 48)
        p.fillRect(x, ground_y - bh, bw, bh, C(PAL['far_city']))
        x += bw + rng.randint(-1, 2)
    skytree = SPRITES.get(('skytree', tower_h), lambda: skytree_grid(int(tower_h * 0.98)))
    p.drawImage(int(w * 0.84) - skytree.width() // 2, ground_y - skytree.height(), skytree)
    rng = random.Random(7)
    x = -3
    while x < w:
        bw, bh = rng.randint(9, 20), rng.randint(9, 32)
        p.fillRect(x, ground_y - bh, bw, bh, C(PAL['ol']))
        p.fillRect(x + 1, ground_y - bh + 1, bw - 2, bh - 1, C(PAL['near_city']))
        yy = ground_y - bh + 3
        while yy < ground_y - 2:
            xx = x + 2
            while xx < x + bw - 2:
                p.fillRect(xx, yy, 1, 2, C(PAL['window_on'] if rng.random() < 0.5 else PAL['window_off']))
                xx += 3
            yy += 4
        x += bw + rng.randint(0, 2)
    rng = random.Random(11)
    x = rng.randint(4, 30)
    while x < w - 10:
        bw = rng.randint(16, 26)
        if abs(x + bw / 2 - tower_x) > 34:
            bush = SPRITES.get(('bush', bw), lambda bw=bw: bush_grid(bw, max(8, bw // 2)))
            p.drawImage(x, ground_y - bush.height() + 1, bush)
        x += bw + rng.randint(30, 80)
    tower = SPRITES.get(('tower', tower_h), lambda: tower_grid(tower_h))
    p.drawImage(tower_x - tower.width() // 2, ground_y - tower.height(), tower)
    brick = SPRITES.get(('brick',), brick_grid)
    for gx in range(0, w, 16):
        for gy in range(ground_y + 2, h, 8):
            p.drawImage(gx, gy, brick)
    p.fillRect(0, ground_y, w, 2, C(PAL['grass']))
    p.fillRect(0, ground_y + 1, w, 1, C(PAL['grass_d']))
    p.end()
    return image


class SceneCache:
    def __init__(self):
        self._key = None
        self._image = None

    def get(self, w, h, ground_y, tower_x, tower_h, fuji_x) -> QImage:
        key = (w, h, ground_y, tower_x, tower_h, fuji_x)
        if key != self._key:
            self._image = build_scene_image(w, h, ground_y, tower_x, tower_h, fuji_x)
            self._key = key
        return self._image


def make_app_icon_image(size: int = 64) -> QImage:
    """像素风应用图标：圆角方块里的蓝天 + 带表情的云和太阳 + 东京塔 + 砖块地面。
    四周留出约 10% 透明边距（macOS 图标的标准比例）。"""
    g = Grid(size, size)
    inset = max(2, size * 6 // 64)
    x0, y0, x1, y1 = inset, inset, size - 1 - inset, size - 1 - inset
    radius = max(3, size // 8)

    def inside(x, y):
        cx = min(max(x, x0 + radius), x1 - radius)
        cy = min(max(y, y0 + radius), y1 - radius)
        return x0 <= x <= x1 and y0 <= y <= y1 and (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2 + radius * 0.8
    mask = [[inside(x, y) for x in range(size)] for y in range(size)]
    ground = y1 - max(6, size // 7)
    brick = brick_grid()
    for y in range(size):
        for x in range(size):
            if not mask[y][x]:
                continue
            if _is_edge(mask, x, y):
                color = PAL['ol']
            elif y > ground + 1:
                color = brick.px[(y - ground - 2) % 8][(x - x0) % 16]
            elif y >= ground:
                color = PAL['grass'] if y == ground else PAL['grass_d']
            else:
                color = '#5c94fc' if y > y0 + (ground - y0) * 0.45 else '#4c84ec'
            g.set(x, y, color)

    def stamp(grid, ox, oy):
        for yy in range(grid.h):
            for xx in range(grid.w):
                if grid.px[yy][xx] is not None and 0 <= oy + yy < size and mask[oy + yy][ox + xx]:
                    g.set(ox + xx, oy + yy, grid.px[yy][xx])
    tower = tower_grid(int((ground - y0) * 0.92))
    stamp(tower, x1 - 3 - tower.w, ground - tower.h)
    cloud = weather_grid('partly', int(size * 0.48), int(size * 0.38))
    stamp(cloud, x0 + 3, y0 + int(size * 0.12))
    return g.to_image()


def make_app_icon() -> QIcon:
    icon = QIcon()
    base = make_app_icon_image()
    for scale in (1, 2, 4, 8, 16):
        icon.addPixmap(QPixmap.fromImage(base.scaled(base.width() * scale, base.height() * scale,
                                                     Qt.AspectRatioMode.IgnoreAspectRatio,
                                                     Qt.TransformationMode.FastTransformation)))
    return icon


# ── 画图工具（坐标都是像素格，画笔已缩放）──────────────────────────────
def ui_font(px: int, bold: bool = False) -> QFont:
    key = (int(px), bool(bold))
    font = _FONT_CACHE.get(key)
    if font is None:
        font = QFont(QApplication.font())
        base = FONT_FAMILY or font.family()
        font.setFamilies([base] + CJK_FALLBACK_FONTS.get(_UI_LANG, []))
        font.setPixelSize(max(1, int(px)))
        font.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
        _FONT_CACHE[key] = font
    return font


def text_width(p: QPainter, text: str, size: float, bold: bool = False) -> float:
    """文字宽度（像素格）。"""
    scale = max(0.01, p.transform().m11())
    font = ui_font(max(1, round(size * scale)), bold)
    return QFontMetricsF(font).horizontalAdvance(text) / scale


def draw_text(p: QPainter, rect: QRectF, text: str, size: float, color, bold: bool = False,
              align=Qt.AlignmentFlag.AlignCenter, outline=None, wrap: bool = False, fit: bool = True):
    """在像素格坐标的 rect 里画文字，字号 size 也是像素格；实际按屏幕分辨率清晰绘制。
    放不下时自动缩小字号（不同语言长度差很多，这样哪种语言都不会溢出）。"""
    if not text:
        return
    transform = p.transform()
    scale = max(0.01, transform.m11())
    target = transform.mapRect(rect)
    px = max(1, round(size * scale))
    min_px = max(6, round(px * 0.55))
    flags = (align | Qt.TextFlag.TextWordWrap) if wrap else align
    font = ui_font(px, bold)
    if fit:
        while px > min_px:
            metrics = QFontMetricsF(font)
            if wrap:
                need = metrics.boundingRect(target, flags, text)
                if need.height() <= target.height() + 0.5 and need.width() <= target.width() + 0.5:
                    break
            elif metrics.horizontalAdvance(text) <= target.width():
                break
            px -= 1
            font = ui_font(px, bold)
    p.save()
    p.resetTransform()
    if outline is not None:
        p.drawImage(target.topLeft() - QPointF(OUTLINE_PAD, OUTLINE_PAD),
                    outlined_text_image(text, font, flags, target.size(), color, outline, scale,
                                        p.device().devicePixelRatioF()))
    else:
        p.setFont(font)
        p.setPen(C(color))
        p.drawText(target, flags, text)
    p.restore()


OUTLINE_PAD = 6
_OUTLINE_CACHE = {}


def outlined_text_image(text, font, flags, size, color, outline, scale, dpr) -> QImage:
    """带描边的文字画成一张透明图并缓存：描边按设备像素一圈圈铺满（Retina 上不会有缺口）。"""
    key = (text, font.pixelSize(), font.weight(), tuple(font.families()), int(flags), round(size.width(), 1),
           round(size.height(), 1), str(color), str(outline), round(scale, 3), round(dpr, 2))
    image = _OUTLINE_CACHE.get(key)
    if image is not None:
        return image
    if len(_OUTLINE_CACHE) > 400:
        _OUTLINE_CACHE.clear()
    pad = OUTLINE_PAD
    image = QImage(max(1, math.ceil((size.width() + 2 * pad) * dpr)), max(1, math.ceil((size.height() + 2 * pad) * dpr)),
                   QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(0)
    q = QPainter(image)
    q.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    q.setFont(font)
    rect = QRectF(pad, pad, size.width(), size.height())
    ring = max(1, round(scale * dpr * 0.6))
    q.setPen(C(outline))
    for r in range(1, ring + 1):
        d = r / dpr
        for dx, dy in ((-d, 0), (d, 0), (0, -d), (0, d), (-d, -d), (d, -d), (-d, d), (d, d)):
            q.drawText(rect.translated(dx, dy), flags, text)
    q.setPen(C(color))
    q.drawText(rect, flags, text)
    q.end()
    _OUTLINE_CACHE[key] = image
    return image


def fill(p: QPainter, x, y, w, h, color):
    p.fillRect(QRectF(x, y, w, h), C(color))


def pixel_box(p: QPainter, r: QRectF, face=None, border=None, shadow: bool = True, bevel: bool = True):
    """像素风方框：1 格描边、切角、上亮下暗的斜面、右下硬阴影。"""
    x, y, w, h = int(round(r.x())), int(round(r.y())), int(round(r.width())), int(round(r.height()))
    face = face or PAL['paper']
    border = border or PAL['ol']
    if shadow:
        fill(p, x + 2, y + 2, w, h, (0, 0, 0, 70))
    fill(p, x + 1, y, w - 2, h, border)
    fill(p, x, y + 1, w, h - 2, border)
    fill(p, x + 1, y + 1, w - 2, h - 2, face)
    if bevel and w > 4 and h > 4:
        fill(p, x + 1, y + 1, w - 2, 1, (255, 255, 255, 150))
        fill(p, x + 1, y + h - 2, w - 2, 1, (0, 0, 0, 40))


def draw_image(p: QPainter, x: float, y: float, image: QImage, w: float = None, h: float = None):
    p.drawImage(QRectF(int(round(x)), int(round(y)), w if w is not None else image.width(),
                       h if h is not None else image.height()), image)


def sky_fill(p: QPainter, W: float, H: float, top: QColor, bottom: QColor, bands: int = 8):
    """像素风天空：竖向分成几段色带，而不是平滑渐变。"""
    band_h = H / bands
    for i in range(bands):
        color = mix_color(top, bottom, i / max(1, bands - 1))
        p.fillRect(QRectF(0, int(i * band_h), W, int(band_h) + 2), color)


def mix_color(a: QColor, b: QColor, t: float) -> QColor:
    t = clamp(t, 0.0, 1.0)
    return QColor(int(lerp(a.red(), b.red(), t)), int(lerp(a.green(), b.green(), t)),
                  int(lerp(a.blue(), b.blue(), t)), int(lerp(a.alpha(), b.alpha(), t)))


def ease_out_cubic(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    return 1 - (1 - t) ** 3


class Button:
    """画在画布上的像素按钮。label 是英文源文字（显示时翻译），也可以是返回文字的函数。"""

    def __init__(self, key: str, label, style: str = 'normal', size: float = 6.0):
        self.key = key
        self.label = label
        self.style = style          # primary / normal / choice / icon_pause / icon_close
        self.size = size
        self.rect = QRectF()
        self.visible = True
        self.enabled = True
        self.hover = False
        self.down = False
        self.selected = False
        self.sub = None             # 第二行小字（函数或文字）

    def text(self) -> str:
        return self.label() if callable(self.label) else _tr(self.label)

    def contains(self, point: QPointF) -> bool:
        return self.visible and self.enabled and self.rect.contains(point)


def draw_button(p: QPainter, b: Button, show_cursor: bool = False, blink: bool = True):
    if not b.visible:
        return
    r = QRectF(b.rect)
    pressed = b.down or (b.style == 'choice' and b.selected)
    if b.down:
        r.translate(0, 1)
    if b.style in ('icon_pause', 'icon_close', 'icon_music'):
        pixel_box(p, r, PAL['btn_hover'] if b.hover else PAL['btn'], shadow=not b.down)
        cx, cy = int(r.center().x()), int(r.center().y())
        if b.style == 'icon_pause':
            fill(p, cx - 3, cy - 3, 2, 7, PAL['ol'])
            fill(p, cx + 1, cy - 3, 2, 7, PAL['ol'])
        elif b.style == 'icon_music':
            # 像素音符；关掉时画一道红色斜线
            ink = PAL['ol'] if b.selected else PAL['grey3']
            fill(p, cx - 4, cy + 1, 3, 2, ink)
            fill(p, cx - 2, cy - 4, 1, 6, ink)
            fill(p, cx - 1, cy - 4, 3, 1, ink)
            fill(p, cx + 1, cy - 3, 1, 2, ink)
            if not b.selected:
                for i in range(-4, 5):
                    fill(p, cx + i, cy + i, 1, 1, PAL['danger'])
        else:
            for i in range(-2, 3):
                fill(p, cx + i, cy + i, 1, 1, PAL['ol'])
                fill(p, cx + i, cy - i, 1, 1, PAL['ol'])
        return
    accent = b.enabled and (b.style == 'primary' or (b.style == 'choice' and b.selected))
    if not b.enabled:
        face, text_color, outline = PAL['grey1'], PAL['grey3'], None
    elif accent:
        face = PAL['accent_hover'] if b.hover and not pressed else PAL['accent']
        text_color, outline = PAL['white'], PAL['accent_lo']
    else:
        face = PAL['btn_hover'] if b.hover else PAL['btn']
        text_color, outline = PAL['ol'], None
    pixel_box(p, r, face, shadow=not pressed)
    if accent:
        fill(p, r.x() + 1, r.y() + 1, r.width() - 2, 1, PAL['accent_hi'])
        fill(p, r.x() + 1, r.bottom() - 2, r.width() - 2, 1, PAL['accent_lo'])
    if b.sub is not None:
        sub = b.sub() if callable(b.sub) else b.sub
        draw_text(p, QRectF(r.x() + 4, r.y() + 1, r.width() - 8, r.height() * 0.58), b.text(), b.size,
                  text_color, bold=True, outline=outline)
        draw_text(p, QRectF(r.x() + 4, r.y() + r.height() * 0.52, r.width() - 8, r.height() * 0.42), sub,
                  b.size * 0.68, text_color)
    else:
        draw_text(p, r.adjusted(4, 0, -4, 0), b.text(), b.size, text_color,
                  bold=b.style != 'normal' or b.hover, outline=outline)
    if show_cursor and (b.hover or b.selected) and blink:
        # 选中项左边的小三角（经典菜单光标）
        cx, cy = int(r.x()) - 8, int(r.center().y())
        for i in range(4):
            fill(p, cx + i, cy - 3 + i, 1, 7 - 2 * i, PAL['white'])
            fill(p, cx + i, cy - 4 + i, 1, 1, PAL['ol'])
            fill(p, cx + i, cy + 4 - i, 1, 1, PAL['ol'])
        fill(p, cx + 4, cy, 1, 1, PAL['ol'])


# ── 天气粒子（雨、雪）────────────────────────────────────────────
class WeatherParticles:
    RATES = {'light_rain': 60.0, 'heavy_rain': 200.0, 'snow': 26.0}

    def __init__(self, seed: int = 7):
        self.rng = random.Random(seed)
        self.items = []
        self._carry = 0.0

    def clear(self):
        self.items = []
        self._carry = 0.0

    def update(self, dt: float, kind: str, area: QRectF):
        self._carry += self.RATES.get(kind, 0.0) * dt
        while self._carry >= 1.0:
            self._carry -= 1.0
            x = self.rng.uniform(area.left() - 20, area.right() + 6)
            if kind == 'snow':
                self.items.append(['snow', x, area.top(), self.rng.uniform(-5, 5), self.rng.uniform(13, 24),
                                   self.rng.choice((1, 1, 2)), self.rng.uniform(0, math.tau)])
            else:
                heavy = kind == 'heavy_rain'
                speed = self.rng.uniform(175, 235) if heavy else self.rng.uniform(125, 175)
                self.items.append(['rain', x, area.top(), speed * 0.22, speed, 4 if heavy else 3, 0.0])
        alive = []
        for item in self.items:
            item[1] += item[3] * dt
            item[2] += item[4] * dt
            if item[0] == 'snow':
                item[6] += dt * 2.0
                item[1] += math.sin(item[6]) * 4 * dt
            if item[2] < area.bottom() + 6:
                alive.append(item)
        self.items = alive[-700:]

    def draw(self, p: QPainter, heavy: bool = False):
        rain = C((164, 228, 252, 200)) if not heavy else C((120, 190, 250, 220))
        snow = C(PAL['white'])
        for item in self.items:
            x, y = int(item[1]), int(item[2])
            if item[0] == 'rain':
                length = item[5]
                p.fillRect(QRectF(x, y - length, 1, length - 1), rain)
                p.fillRect(QRectF(x - 1, y - 1, 1, 1), rain)
            else:
                p.fillRect(QRectF(x, y, item[5], item[5]), snow)


# ── 画面基类 ─────────────────────────────────────────────────
class Screen:
    """一个画面（或浮层）：自己画、自己更新、自己处理输入。坐标都是像素格。"""

    def __init__(self, ui):
        self.ui = ui
        self.buttons = []
        self._pressed = None
        self.time = 0.0

    def add_button(self, key, label, style='normal', size=6.0) -> Button:
        button = Button(key, label, style, size)
        self.buttons.append(button)
        return button

    def button_at(self, point: QPointF):
        for button in reversed(self.buttons):
            if button.contains(point):
                return button
        return None

    # 子类覆盖
    def update(self, dt: float):
        self.time += dt

    def paint(self, p: QPainter, W: float, H: float):
        pass

    def animating(self) -> bool:
        return True

    def on_button(self, key: str):
        pass

    def canvas_press(self, point: QPointF):
        pass

    def key(self, key: int, auto_repeat: bool) -> bool:
        return False

    # 输入分发
    def press(self, point: QPointF) -> bool:
        """返回 True 表示按在了按钮上。"""
        button = self.button_at(point)
        if button is not None:
            button.down = True
            self._pressed = button
            return True
        self.canvas_press(point)
        return False

    def release(self, point: QPointF):
        button = self._pressed
        self._pressed = None
        if button is None:
            return
        button.down = False
        if button.contains(point):
            self.on_button(button.key)

    def move(self, point: QPointF) -> bool:
        hovered = self.button_at(point)
        changed = False
        for button in self.buttons:
            state = button is hovered
            if button.hover != state:
                button.hover = state
                changed = True
        return changed

    def clear_hover(self):
        for button in self.buttons:
            button.hover = False
            button.down = False
        self._pressed = None

    def hovering_button(self) -> bool:
        return any(b.hover and b.visible and b.enabled for b in self.buttons)


class Overlay(Screen):
    """浮在画面上方的像素面板：外面压一层半透明遮罩，点遮罩或按 Esc 关闭。"""

    PANEL_W = 200

    def __init__(self, ui):
        super().__init__(ui)
        self.panel = QRectF()
        self.btn_close = self.add_button('close', '', 'icon_close')

    def panel_height(self, W: float, H: float) -> float:
        return 150

    def layout(self, W: float, H: float):
        pw = min(self.PANEL_W, W - 12)
        ph = min(self.panel_height(W, H), H - 8)
        self.panel = QRectF(int((W - pw) / 2), int((H - ph) / 2), int(pw), int(ph))
        self.btn_close.rect = QRectF(self.panel.right() - 15, self.panel.y() + 4, 11, 11)

    def paint(self, p: QPainter, W: float, H: float):
        self.layout(W, H)
        fill(p, 0, 0, W, H, (20, 20, 48, 120))
        appear = ease_out_cubic(min(1.0, self.time / 0.18))
        p.save()
        p.translate(0, int((1 - appear) * 8))
        pixel_box(p, self.panel)
        self.paint_panel(p, self.panel)
        for button in self.buttons:
            draw_button(p, button)
        p.restore()

    def paint_panel(self, p: QPainter, r: QRectF):
        pass

    def animating(self) -> bool:
        return self.time < 0.3

    def canvas_press(self, point: QPointF):
        if not self.panel.contains(point):
            self.ui.close_overlay(self)

    def on_button(self, key: str):
        if key == 'close':
            self.ui.close_overlay(self)

    def key(self, key: int, auto_repeat: bool) -> bool:
        if key == Qt.Key.Key_Escape:
            self.ui.close_overlay(self)
        return True     # 浮层打开时，按键都不传给下面的画面


# ── 开始画面 ─────────────────────────────────────────────────
class TitleScreen(Screen):
    def __init__(self, ui):
        super().__init__(ui)
        self.saved = None
        self.strip = WeatherStrip(Mulberry32(2027), 40.0, 0.3)
        self.scene = SceneCache()
        self.clouds = [[random.Random(i).uniform(0, 400), 30 + i * 13, 5 + i * 2.5] for i in range(3)]
        self.btn_continue = self.add_button('continue', N_('Continue'), 'primary', 6.5)
        self.btn_new = self.add_button('new', N_('New Game'), 'normal', 6.0)
        self.btn_board = self.add_button('board', N_('Leaderboard'), 'normal', 6.0)
        self.btn_settings = self.add_button('settings', N_('Settings'), 'normal', 6.0)
        self.btn_help = self.add_button('help', N_('How to Play'), 'normal', 6.0)
        self.btn_quit = self.add_button('quit', N_('Quit'), 'normal', 6.0)
        self.btn_music = self.add_button('music', '', 'icon_music')
        self.btn_continue.sub = self._continue_caption
        self.selected = 0

    def refresh(self):
        self.saved = load_game()
        self.btn_continue.visible = self.saved is not None
        self.btn_new.style = 'normal' if self.saved is not None else 'primary'
        self.selected = 0

    def _continue_caption(self) -> str:
        session = self.saved
        if session is None:
            return ''
        if session.victory:
            return _tr('All {n} levels cleared!').format(n=LEVEL_COUNT) + ' · ' + mode_label(session.mode)
        level, day = session.level, session.day_index + 1
        if session.level_done:
            level, day = level + 1, 1          # 上个月已经定完，继续时从下个月 1 号开始
        year, month = level_month(session.start_year, level)
        return _tr('Level {n} · {date} · {mode}').format(
            n=level, date=format_date(year, month, day), mode=mode_label(session.mode))

    def menu(self) -> list:
        return [b for b in (self.btn_continue, self.btn_new, self.btn_board, self.btn_settings, self.btn_help,
                            self.btn_quit) if b.visible]

    def on_button(self, key: str):
        if key == 'continue':
            self.ui.continue_game()
        elif key == 'new':
            self.ui.request_new_game()
        elif key == 'board':
            self.ui.show_leaderboard()
        elif key == 'music':
            self.ui.toggle_music()
        elif key == 'settings':
            self.ui.open_settings()
        elif key == 'help':
            self.ui.open_help()
        elif key == 'quit':
            self.ui.quit_requested()

    def move(self, point: QPointF) -> bool:
        changed = super().move(point)
        for i, button in enumerate(self.menu()):
            if button.hover and button is not self.btn_music and self.selected != i:
                self.selected = i
                changed = True
        return changed

    def key(self, key: int, auto_repeat: bool) -> bool:
        menu = self.menu()
        if key in (Qt.Key.Key_Up, Qt.Key.Key_W, Qt.Key.Key_Down, Qt.Key.Key_S):
            for button in self.buttons:
                button.hover = False
        if key in (Qt.Key.Key_Up, Qt.Key.Key_W):
            self.selected = (self.selected - 1) % len(menu)
            return True
        if key in (Qt.Key.Key_Down, Qt.Key.Key_S):
            self.selected = (self.selected + 1) % len(menu)
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space) and not auto_repeat:
            self.on_button(menu[self.selected % len(menu)].key)
            return True
        return False

    def update(self, dt: float):
        super().update(dt)
        self.strip.advance(9 * dt)
        for cloud in self.clouds:
            cloud[0] += cloud[2] * dt

    def paint(self, p: QPainter, W: float, H: float):
        sky_fill(p, W, H, C(PAL['sky_title_top']), C(PAL['sky_title_bottom']))
        # 大白云（慢慢飘）
        for i, cloud in enumerate(self.clouds):
            cw = 44 + i * 10
            image = SPRITES.get(('bigcloud', cw), lambda cw=cw: big_cloud_grid(cw))
            x = (cloud[0] % (W + cw + 40)) - cw - 20
            draw_image(p, x, cloud[1] + 14, image)
        # 顶部一排缓缓经过的天气
        for tile in self.strip.tiles:
            x = W / 2 + tile.x
            if x > W or x + tile.w < 0:
                continue
            bob = 1 if math.sin(self.time * 2.2 + tile.uid) > 0.6 else 0
            image = SPRITES.weather(tile.kind, int(tile.w * 0.72), 20)
            draw_image(p, x + tile.w * 0.14, 2 + bob, image)
        ground_y = int(H) - 14
        tower_h = int(min(128, ground_y - 64))
        tower_x = int(W * 0.78)
        scene = self.scene.get(int(W) + 1, int(H) + 1, ground_y, tower_x, tower_h, int(W * 0.5))
        draw_image(p, 0, 0, scene)
        # 标题
        left = 14
        title_w = min(W * 0.62, 230)
        draw_text(p, QRectF(left, 28, title_w, 44), _tr("Are You Tokyo's Better Weather God?"), 14,
                  PAL['white'], bold=True, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                  outline=PAL['ol'], wrap=True)
        draw_text(p, QRectF(left, 73, title_w, 9), _tr("Click to decide Tokyo's weather, one day at a time"), 5,
                  PAL['white'], align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, outline=PAL['ol'])
        # 菜单
        y = 87
        blink = int(self.time * 3) % 2 == 0
        menu = self.menu()
        for i, button in enumerate(menu):
            h = 21 if button is self.btn_continue else 13
            button.rect = QRectF(left + 8, y, 116, h)
            button.selected = i == self.selected
            y += h + 3
        for button in menu:
            draw_button(p, button, show_cursor=True, blink=blink)
        # 右上角：背景音乐开关
        self.btn_music.visible = self.ui.music.available
        self.btn_music.selected = bool(self.ui.settings.get('music', True))
        self.btn_music.rect = QRectF(int(W) - 18, 30, 14, 14)
        draw_button(p, self.btn_music)
        # 当前设置与该难度的最佳纪录
        settings = self.ui.settings
        mode = settings.get('mode', 'normal')
        info = _tr('{mode} · Speed {pct}%').format(mode=mode_label(mode), pct=settings.get('speed_percent', 100))
        best = int(settings.get('best_by_mode', {}).get(mode, 0))
        if best > 0:
            info += '  ·  ' + _tr('Best: {best}').format(best=best_label(best))
        width = min(W - 60, text_width(p, info, 4.5) + 12)
        pill = QRectF(left, H - 12, width, 10)
        pixel_box(p, pill, shadow=False, bevel=False)
        draw_text(p, pill.adjusted(3, 0, -3, 0), info, 4.5, PAL['ol'])
        draw_text(p, QRectF(W - 40, H - 11, 36, 8), 'v' + VERSION, 4, PAL['white'],
                  align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, outline=PAL['brick_mortar'])


# ── 游戏画面 ─────────────────────────────────────────────────
def play_layout(W: float, H: float) -> dict:
    """游戏画面的布局（像素格）。"""
    strip = QRectF(5, 20, int(W) - 10, 42)
    ground_y = int(H) - 30
    tower_top = max(int(strip.bottom()) + 26, ground_y - 132)
    return {
        'strip': strip,
        'marker_x': int(W / 2),
        'ground_y': ground_y,
        'tower_top': tower_top,
        'calendar': QRectF(5, int(H) - 28, int(W) - 10, 26),
        'scene': QRectF(0, strip.bottom(), W, ground_y - strip.bottom()),
    }


def calendar_chip_rects(area: QRectF, days: int) -> list:
    """底部日历：分上下两行排（一行 31 格太挤，图标看不清）。"""
    gap = 1
    cols = (days + 1) // 2
    chip_w = int(min(22, (area.width() - gap * (cols - 1)) / cols))
    chip_h = int((area.height() - gap) / 2)
    total = chip_w * cols + gap * (cols - 1)
    x0 = int(area.center().x() - total / 2)
    rects = []
    for i in range(days):
        row, col = divmod(i, cols)
        rects.append(QRectF(x0 + col * (chip_w + gap), area.y() + row * (chip_h + gap), chip_w, chip_h))
    return rects


def chip_icon_rect(rect: QRectF) -> QRectF:
    """日历小格里放天气图标的位置（左边留给日期数字）。"""
    return QRectF(rect.x() + 7, rect.y() + 1, rect.width() - 8, rect.height() - 2)


class PlayScreen(Screen):
    INTRO_LOCK = 0.3        # 进入新关卡后这么久内按键不算（防止手快跳过）
    CLEAR_LOCK = 0.8        # 月结卡片至少显示这么久

    def __init__(self, ui):
        super().__init__(ui)
        self.session = None
        self.params = None
        self.strip = None
        self.state = 'idle'              # intro / playing / paused / clear / over / done
        self.state_time = 0.0
        self.day_elapsed = 0.0
        self.scene_kind = 'sunny'
        self.sky_top = QColor(SKY_COLORS['sunny'][0])
        self.sky_bottom = QColor(SKY_COLORS['sunny'][1])
        self.tint = QColor(0, 0, 0, 0)
        self.sun_alpha = 1.0
        self.particles = WeatherParticles()
        self.scene = SceneCache()
        self.flyers = []                 # 选中的云飞向日历
        self.toasts = []                 # 飘字提示
        self.landed_days = 0             # 已经落到日历上的天数
        self.star_breaks = []            # 正在碎掉的星星
        self.shake = 0.0
        self.rain_flash = 0.0
        self.saved_flash = 0.0
        self.save_failed = False
        self._save_warned = False
        self.resumed = False
        self.last_events = {}
        self._paused_from = 'playing'
        self.btn_pause = self.add_button('pause', '', 'icon_pause')
        self.btn_start = self.add_button('start', self._start_label, 'primary', 6.5)
        self.btn_resume = self.add_button('resume', N_('Resume'), 'primary')
        self.btn_save = self.add_button('save', self._save_label)
        self.btn_settings = self.add_button('settings', N_('Settings'))
        self.btn_title = self.add_button('title', N_('Save & Back to Menu'))
        self.btn_next = self.add_button('next', self._next_label, 'primary', 6.5)

    def _start_label(self) -> str:
        if self.resumed:
            return _tr('Continue')
        return _tr('Start Level {n}').format(n=self.session.level if self.session else 1)

    def _save_label(self) -> str:
        if self.saved_flash > 0:
            return _tr('Save failed') if self.save_failed else _tr('Saved!')
        return _tr('Save Progress')

    def _autosave(self):
        """自动存档；失败时提示一次（不会每天都弹）。"""
        if self.ui.autosave():
            self._save_warned = False
        elif not self._save_warned and self.session is not None and not self.session.game_over:
            self._save_warned = True
            self._toast(_tr('Could not save progress'), PAL['danger'], big=True)

    def _next_label(self) -> str:
        if self.session is not None and self.session.victory:
            return _tr('See the Ending')
        return _tr('Go to Level {n}').format(n=(self.session.level + 1) if self.session else 2)

    # ── 流程 ──
    def begin(self, session: GameSession, resumed: bool = False):
        self.session = session
        self.resumed = resumed
        self.scene_kind = session.month_days[-1] if (resumed and session.month_days) else 'sunny'
        kind = self.scene_kind
        self.sky_top = QColor(SKY_COLORS[kind][0])
        self.sky_bottom = QColor(SKY_COLORS[kind][1])
        self.tint = QColor(*SCENE_TINT[kind])
        self.sun_alpha = 1.0 if kind in ('sunny', 'partly') else 0.0
        self.particles.clear()
        self.toasts = []
        self.star_breaks = []
        self.shake = 0.0
        self.rain_flash = 0.0
        self.saved_flash = 0.0
        self.save_failed = False
        self._save_warned = False
        self.last_events = {}
        if resumed and session.level_done and not session.victory:
            session.next_level()
            self.resumed = False
        self._begin_level()
        if session.victory and session.level_done:
            self._set_state('clear')
            self.state_time = self.CLEAR_LOCK

    def apply_settings(self, settings: dict):
        """游戏中改设置：速度倍率、每日限时立刻生效（今天已用掉的时间按比例保留）；难度从下一局开始生效。"""
        if self.session is None or self.params is None:
            return
        old_limit = self.params['day_limit']
        self.params = level_params(self.session.level, self.session.mode, settings['speed_percent'])
        if old_limit > 0:
            self.day_elapsed *= self.params['day_limit'] / old_limit

    def _begin_level(self):
        session = self.session
        self.params = level_params(session.level, session.mode, self.ui.settings['speed_percent'])
        self.strip = WeatherStrip(session.level_rng(), self.params['tile_w'], self.params['rain_ratio'])
        self.flyers = []
        self.landed_days = len(session.month_days)
        self.day_elapsed = 0.0
        self._set_state('intro')
        self.ui.autosave()

    def _set_state(self, state: str):
        self.state = state
        self.state_time = 0.0
        for button in self.buttons:
            button.visible = False
            button.hover = False
            button.down = False
        self._pressed = None
        if state in ('intro', 'playing'):
            self.btn_pause.visible = True
        if state == 'intro':
            self.btn_start.visible = True
        elif state == 'paused':
            for button in (self.btn_resume, self.btn_save, self.btn_settings, self.btn_title):
                button.visible = True
        elif state == 'clear':
            self.btn_next.visible = True

    def pause(self):
        if self.state in ('intro', 'playing'):
            self._paused_from = self.state
            self._set_state('paused')
            self.ui.autosave()

    def resume(self):
        if self.state == 'paused':
            self._set_state(self._paused_from)
            if self._paused_from == 'intro':
                self.state_time = self.INTRO_LOCK

    def on_button(self, key: str):
        if key == 'pause':
            self.pause()
        elif key == 'start':
            self._start_playing()
        elif key == 'resume':
            self.resume()
        elif key == 'save':
            self.save_failed = not self.ui.autosave()
            self.saved_flash = 1.6
        elif key == 'settings':
            self.ui.open_settings()
        elif key == 'title':
            self.ui.autosave()
            self.ui.show_title()
        elif key == 'next':
            self._go_next()

    def _go_next(self):
        if self.state != 'clear' or self.state_time < self.CLEAR_LOCK:
            return
        if self.session.victory:
            self.state = 'done'
            self.ui.finish_game(self.session.result())
        elif self.session.next_level():
            self.resumed = False
            self._begin_level()

    def _start_playing(self):
        if self.state == 'intro' and self.state_time >= self.INTRO_LOCK:
            self.day_elapsed = 0.0
            self._set_state('playing')

    # ── 选天气 ──
    def pick(self, timeout: bool = False) -> bool:
        """把东京塔正上方那朵云定为今天的天气。成功返回 True。"""
        if self.state != 'playing' or self.session is None or self.session.level_done:
            return False
        W, H = self.ui.art_size()
        layout = play_layout(W, H)
        tile = self.strip.tile_at(0.0)
        if tile is None or tile.used:
            if not timeout:
                self.shake = 1.0
                self._toast(_tr('That cloud already fell on Tokyo. Wait for the next one!'), PAL['ol'])
                return False
            tile = self.strip.nearest_unused(0.0, reach=layout['strip'].width() / 2)
            if tile is None:
                return False
        tile.used = True
        day = self.session.day_index
        events = self.session.assign(tile.kind)
        self.last_events = events
        self.day_elapsed = 0.0
        strip = layout['strip']
        start = QRectF(layout['marker_x'] + tile.x, strip.y(), tile.w, strip.height())
        self.flyers.append({'kind': tile.kind, 'start': start, 'day': day, 't': 0.0})
        self.scene_kind = tile.kind
        label = _tr(WEATHER_INFO[tile.kind]['label'])
        if events['game_over']:
            # 游戏结束：清掉所有提示，让 GAME OVER 文字干干净净
            self.toasts = []
            self.star_breaks.append({'index': 0, 't': 0.0})
            self._set_state('over')
            self.ui.game_over_reached()
            return True
        if timeout:
            self._toast(_tr("Time's up! Today: {w}").format(w=label), PAL['ol'])
        elif events['rain']:
            self.rain_flash = 1.0
            self._toast(_tr('{w}… it rains in Tokyo').format(w=label), PAL['blue_lo'])
        else:
            self._toast(_tr('{w}!').format(w=label), PAL['accent'])
        if events['star_lost']:
            self.star_breaks.append({'index': self.session.stars, 't': 0.0})
            self._toast(_tr('{n} rainy days in total: you lost a star').format(n=self.session.rain_total),
                        PAL['danger'], big=True)
        self._autosave()
        return True

    def _toast(self, text: str, color: str, big: bool = False):
        for toast in self.toasts:
            if toast['text'] == text:
                toast['t'] = min(toast['t'], 0.15)
                return
        self.toasts = [t for t in self.toasts if t['big']] if big else self.toasts[-2:]
        self.toasts.append({'text': text, 'color': color, 't': 0.0, 'big': big})

    # ── 更新 ──
    def animating(self) -> bool:
        if self.state == 'paused':
            return self.saved_flash > 0
        return self.state not in ('done', 'idle')

    def update(self, dt: float):
        super().update(dt)
        if self.session is None:
            return
        self.state_time += dt
        self.saved_flash = max(0.0, self.saved_flash - dt)
        if self.state in ('paused', 'done'):
            return
        W, H = self.ui.art_size()
        layout = play_layout(W, H)
        if self.strip is not None and self.state in ('intro', 'playing', 'clear'):
            self.strip.advance(self.params['speed'] * dt)
        if self.state == 'playing':
            if self.ui.settings.get('day_timer', True):
                self.day_elapsed += dt
                if self.day_elapsed >= self.params['day_limit']:
                    self.pick(timeout=True)
            if self.state == 'playing' and self.session.level_done and not self.flyers:
                self._set_state('clear')
                self.ui.autosave()
        elif self.state == 'over' and self.state_time >= 2.2:
            self.state = 'done'
            self.ui.finish_game(self.session.result())
            return
        k = clamp(dt * 3.0, 0.0, 1.0)
        kind = 'heavy_rain' if self.state == 'over' else self.scene_kind
        self.sky_top = mix_color(self.sky_top, C(SKY_COLORS[kind][0]), k)
        self.sky_bottom = mix_color(self.sky_bottom, C(SKY_COLORS[kind][1]), k)
        self.tint = mix_color(self.tint, C(SCENE_TINT[kind]), k)
        self.sun_alpha = lerp(self.sun_alpha, 1.0 if kind in ('sunny', 'partly') else 0.0, k)
        self.particles.update(dt, kind, layout['scene'])
        for flyer in self.flyers:
            flyer['t'] += dt / 0.55
        landed = [f for f in self.flyers if f['t'] >= 1.0]
        if landed:
            self.landed_days = max([self.landed_days] + [f['day'] + 1 for f in landed])
            self.flyers = [f for f in self.flyers if f['t'] < 1.0]
        for toast in self.toasts:
            toast['t'] += dt
        self.toasts = [t for t in self.toasts if t['t'] < (2.2 if t['big'] else 1.3)]
        for item in self.star_breaks:
            item['t'] += dt
        self.star_breaks = [s for s in self.star_breaks if s['t'] < 1.2]
        self.shake = max(0.0, self.shake - dt * 3.0)
        self.rain_flash = max(0.0, self.rain_flash - dt * 1.6)

    # ── 输入 ──
    def canvas_press(self, point: QPointF):
        if self.state == 'intro':
            self._start_playing()
        elif self.state == 'playing':
            self.pick()

    def key(self, key: int, auto_repeat: bool) -> bool:
        if auto_repeat:
            return True
        if key in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.state == 'intro':
                self._start_playing()
            elif self.state == 'playing':
                self.pick()
            elif self.state == 'paused':
                self.resume()
            elif self.state == 'clear':
                self._go_next()
            return True
        if key in (Qt.Key.Key_Escape, Qt.Key.Key_P):
            if self.state == 'paused':
                self.resume()
            else:
                self.pause()
            return True
        return False

    # ── 绘制 ──
    def paint(self, p: QPainter, W: float, H: float):
        if self.session is None:
            return
        layout = play_layout(W, H)
        sky_fill(p, W, H, self.sky_top, self.sky_bottom)
        if self.sun_alpha > 0.05:
            p.save()
            p.setOpacity(self.sun_alpha)
            draw_image(p, 18, layout['strip'].bottom() + 16, SPRITES.weather('sunny', 26, 26))
            p.restore()
        tower_h = layout['ground_y'] - layout['tower_top']
        scene = self.scene.get(int(W) + 1, int(H) + 1, layout['ground_y'], layout['marker_x'], tower_h, int(W * 0.2))
        draw_image(p, 0, 0, scene)
        if self.tint.alpha() > 0:
            p.fillRect(QRectF(0, layout['strip'].bottom(), W, layout['ground_y'] - layout['strip'].bottom()),
                       self.tint)
        self.particles.draw(p, heavy=self.scene_kind == 'heavy_rain')
        self._paint_guide(p, layout)
        self._paint_strip(p, layout)
        self._paint_hud(p, W, layout)
        self._paint_calendar(p, layout)
        self._paint_flyers(p, layout)
        self._paint_toasts(p, W, layout)
        self._paint_overlay(p, W, H)

    def _paint_guide(self, p: QPainter, layout: dict):
        """东京塔天线 → 天气条 的点线、今天的日期、每天倒计时格。"""
        mx = layout['marker_x']
        strip = layout['strip']
        session = self.session
        y = int(strip.bottom()) + 22
        while y < layout['tower_top'] - 2:
            fill(p, mx, y, 1, 1, PAL['white'])
            y += 3
        if session.level_done or session.game_over or self.state not in ('intro', 'playing', 'paused'):
            return
        year, month = session.year_month
        label = format_date(year, month, session.day_index + 1)
        box = QRectF(mx - 30, strip.bottom() + 5, 60, 10)
        pixel_box(p, box, shadow=False)
        draw_text(p, box.adjusted(2, 0, -2, 0), label, 5, PAL['ol'], bold=True)
        if self.ui.settings.get('day_timer', True):
            remain = 1.0 - clamp(self.day_elapsed / self.params['day_limit'], 0.0, 1.0)
            cells = 10
            lit = int(math.ceil(remain * cells - 1e-6))
            x0 = mx - (cells * 5 - 1) // 2
            blink = lit <= 2 and int(self.time * 6) % 2 == 0
            for i in range(cells):
                if i < lit:
                    color = PAL['danger'] if lit <= 3 else PAL['blue']
                    if blink and i == lit - 1:
                        color = PAL['white']
                else:
                    color = (0, 0, 0, 60)
                fill(p, x0 + i * 5, box.bottom() + 2, 4, 3, color)

    def _paint_strip(self, p: QPainter, layout: dict):
        strip = layout['strip']
        mx = layout['marker_x']
        x0, y0, w, h = int(strip.x()), int(strip.y()), int(strip.width()), int(strip.height())
        fill(p, x0, y0, w, h, (252, 252, 252, 64))
        fill(p, x0, y0, w, 1, (255, 255, 255, 170))
        fill(p, x0, y0 + h - 1, w, 1, (255, 255, 255, 170))
        p.save()
        p.setClipRect(QRectF(x0, y0, w, h))
        current = self.strip.tile_at(0.0)
        blink = int(self.time * 4) % 2 == 0
        for tile in self.strip.tiles:
            x = int(round(mx + tile.x))
            tw = int(round(tile.w))
            if x > x0 + w or x + tw < x0:
                continue
            if tile is current and not tile.used and self.state in ('intro', 'playing', 'paused'):
                sx = int(round(math.sin(self.shake * 30) * 2 * self.shake))
                self._paint_selection(p, QRectF(x + 2 + sx, y0 + 2, tw - 4, h - 4), blink)
            else:
                yy = y0 + 4
                while yy < y0 + h - 4:
                    fill(p, x, yy, 1, 1, (255, 255, 255, 160))
                    yy += 2
            image = SPRITES.weather(tile.kind, max(8, tw - 10), 26)
            if tile.used:
                p.setOpacity(0.2)
            draw_image(p, x + (tw - image.width()) // 2, y0 + 4, image)
            draw_text(p, QRectF(x + 1, y0 + h - 12, tw - 2, 9), _tr(WEATHER_INFO[tile.kind]['label']), 4.6,
                      PAL['white'], bold=True, outline=PAL['ol'])
            p.setOpacity(1.0)
        p.restore()
        # 固定的"东京上空"箭头
        top = int(strip.bottom()) + 1
        for i in range(5):
            fill(p, mx - 4 + i, top + i, 9 - 2 * i, 1, PAL['accent'])
            fill(p, mx - 5 + i, top + i, 1, 1, PAL['ol'])
            fill(p, mx + 5 - i, top + i, 1, 1, PAL['ol'])

    def _paint_selection(self, p: QPainter, r: QRectF, blink: bool):
        fill(p, r.x(), r.y(), r.width(), r.height(), (255, 255, 255, 110))
        color = PAL['accent'] if blink else PAL['sun2']
        x, y, w, h = int(r.x()), int(r.y()), int(r.width()), int(r.height())
        arm = 5
        for cx, cy, dx, dy in ((x, y, 1, 1), (x + w - 1, y, -1, 1), (x, y + h - 1, 1, -1), (x + w - 1, y + h - 1, -1, -1)):
            for i in range(arm):
                fill(p, cx + dx * i, cy, 1, 1, color)
                fill(p, cx, cy + dy * i, 1, 1, color)
                fill(p, cx + dx * i, cy + dy, 1, 1, color)
                fill(p, cx + dx, cy + dy * i, 1, 1, color)

    def _paint_hud(self, p: QPainter, W: float, layout: dict):
        session = self.session
        breaking = {item['index']: item['t'] for item in self.star_breaks}
        for i in range(STAR_COUNT):
            x, y = 5 + i * 13, 4
            if i < session.stars:
                draw_image(p, x, y, SPRITES.star(11, True))
            elif i in breaking:
                t = breaking[i]
                draw_image(p, x, y, SPRITES.star(11, False))
                if int(t * 10) % 2 == 0:
                    draw_image(p, x, y - int(t * 6), SPRITES.star(11, True))
            else:
                draw_image(p, x, y, SPRITES.star(11, False))
        year, month = session.year_month
        title = _tr('Level {n} · {ym}').format(n=session.level, ym=format_year_month(year, month))
        sub = _tr('{mode} · {done}/{total} days').format(mode=mode_label(session.mode), done=session.day_index,
                                                          total=session.days_in_level)
        if self.state != 'clear':
            box_w = int(clamp(W - 2 * 112, 70, 124))
            box = QRectF(int(W / 2 - box_w / 2), 2, box_w, 16)
            pixel_box(p, box, shadow=False)
            draw_text(p, QRectF(box.x() + 2, box.y() + 1, box.width() - 4, 8), title, 5.2, PAL['ol'], bold=True)
            draw_text(p, QRectF(box.x() + 2, box.y() + 8.5, box.width() - 4, 6), sub, 3.8, PAL['ink_soft'])
        # 雨量计：累计几天雨，满 7 天掉一颗星
        progress = session.rain_progress
        if self.last_events.get('star_lost') and self.star_breaks:
            progress = RAIN_DAYS_PER_STAR
        right = int(W) - 22
        meter = QRectF(right - RAIN_DAYS_PER_STAR * 6 - 30, 3, RAIN_DAYS_PER_STAR * 6 + 32, 14)
        pixel_box(p, meter, shadow=False)
        draw_text(p, QRectF(meter.x() + 2, meter.y(), 26, meter.height()),
                  _tr('Rain {a}/{b}').format(a=progress, b=RAIN_DAYS_PER_STAR), 4.2, PAL['ol'], bold=True)
        for i in range(RAIN_DAYS_PER_STAR):
            filled = i < progress
            color = PAL['blue'] if filled else PAL['white']
            if filled and self.rain_flash > 0 and i == progress - 1 and int(self.rain_flash * 8) % 2 == 0:
                color = PAL['danger']
            draw_image(p, meter.x() + 29 + i * 6, meter.y() + 3, SPRITES.drop(5, 8, color))
        self.btn_pause.rect = QRectF(int(W) - 18, 3, 14, 14)
        draw_button(p, self.btn_pause)

    def _paint_calendar(self, p: QPainter, layout: dict):
        session = self.session
        year, month = session.year_month
        rects = calendar_chip_rects(layout['calendar'], session.days_in_level)
        today = session.day_index
        for i, rect in enumerate(rects):
            is_today = i == today and self.state in ('intro', 'playing', 'paused')
            face = PAL['paper'] if (i < self.landed_days or is_today) else (255, 247, 230, 150)
            pixel_box(p, rect, face, border=PAL['accent'] if is_today else PAL['ol'], shadow=False, bevel=False)
            weekday = calendar.weekday(year, month, i + 1)
            num_color = PAL['danger'] if weekday == 6 else (PAL['blue_lo'] if weekday == 5 else PAL['ol'])
            draw_text(p, QRectF(rect.x() + 1, rect.y(), 7, rect.height()), str(i + 1), 3.4, num_color, bold=True)
            if i < self.landed_days and i < len(session.month_days):
                icon = chip_icon_rect(rect)
                image = SPRITES.weather(session.month_days[i], int(icon.width()), int(icon.height()))
                draw_image(p, icon.x(), icon.y(), image)

    def _paint_flyers(self, p: QPainter, layout: dict):
        if not self.flyers:
            return
        rects = calendar_chip_rects(layout['calendar'], self.session.days_in_level)
        for flyer in self.flyers:
            t = ease_out_cubic(flyer['t'])
            start = flyer['start']
            end = chip_icon_rect(rects[min(flyer['day'], len(rects) - 1)])
            sw, sh = max(8.0, start.width() - 10), 26.0
            w, h = lerp(sw, end.width(), t), lerp(sh, end.height(), t)
            cx = lerp(start.center().x(), end.center().x(), t)
            cy = lerp(start.y() + 4 + sh / 2, end.center().y(), t) - math.sin(math.pi * t) * 14
            image = SPRITES.weather(flyer['kind'], int(sw), 26)
            draw_image(p, cx - w / 2, cy - h / 2, image, int(w), int(h))

    def _paint_toasts(self, p: QPainter, W: float, layout: dict):
        y = layout['strip'].bottom() + 34
        for toast in self.toasts:
            life = 2.2 if toast['big'] else 1.3
            t = toast['t'] / life
            if t > 0.8 and int(toast['t'] * 12) % 2 == 0:
                continue      # 快消失时闪一闪（像素游戏的经典做法）
            size = 6 if toast['big'] else 5
            width = min(W - 16, text_width(p, toast['text'], size, True) + 12)
            rect = QRectF(int(W / 2 - width / 2), int(y - min(1.0, t * 4) * 3), int(width), size + 6)
            pixel_box(p, rect, shadow=True)
            draw_text(p, rect.adjusted(3, 0, -3, 0), toast['text'], size, toast['color'], bold=True)
            y += size + 10

    def _paint_overlay(self, p: QPainter, W: float, H: float):
        session = self.session
        if self.state == 'intro':
            card = QRectF(int(W / 2 - 70), int(H / 2 - 30), 140, 82)
            pixel_box(p, card)
            year, month = session.year_month
            head = _tr('Welcome back!') if self.resumed else _tr('Level {n}').format(n=session.level)
            draw_text(p, QRectF(card.x(), card.y() + 4, card.width(), 13), head, 9, PAL['white'], bold=True,
                      outline=PAL['ol'])
            if self.resumed:
                line = _tr('Level {n} · continue from {date}').format(
                    n=session.level, date=format_date(year, month, session.day_index + 1))
            else:
                line = _tr('{ym} · {d} days').format(ym=format_year_month(year, month), d=session.days_in_level)
            draw_text(p, QRectF(card.x() + 4, card.y() + 18, card.width() - 8, 8), line, 5, PAL['ol'])
            x0 = int(card.center().x() - LEVEL_COUNT * 6 / 2)
            for i in range(LEVEL_COUNT):
                fill(p, x0 + i * 6, card.y() + 29, 5, 5, PAL['ol'])
                fill(p, x0 + i * 6 + 1, card.y() + 30, 3, 3, PAL['accent'] if i < session.level else PAL['grey1'])
            draw_text(p, QRectF(card.x(), card.y() + 35, card.width(), 7), _tr('Scroll speed'), 4, PAL['ink_soft'])
            self.btn_start.rect = QRectF(int(card.center().x() - 42), card.y() + 45, 84, 16)
            draw_button(p, self.btn_start)
            draw_text(p, QRectF(card.x() + 2, card.bottom() - 13, card.width() - 4, 8),
                      _tr('Click anywhere or press Space'), 4, PAL['ink_soft'])
        elif self.state == 'paused':
            fill(p, 0, 0, W, H, (20, 20, 48, 120))
            card = QRectF(int(W / 2 - 62), int(H / 2 - 52), 124, 104)
            pixel_box(p, card)
            draw_text(p, QRectF(card.x(), card.y() + 4, card.width(), 14), _tr('Paused'), 9, PAL['white'],
                      bold=True, outline=PAL['ol'])
            y = card.y() + 22
            for button in (self.btn_resume, self.btn_save, self.btn_settings, self.btn_title):
                button.rect = QRectF(int(card.x() + 10), int(y), int(card.width() - 20), 15)
                draw_button(p, button)
                y += 19
        elif self.state == 'clear':
            self._paint_clear_card(p, W, H)
        elif self.state in ('over', 'done'):
            t = clamp(self.state_time / 0.8, 0.0, 1.0) if self.state == 'over' else 1.0
            fill(p, 0, 0, W, H, (16, 16, 40, int(150 * t)))
            if t > 0.2:
                draw_text(p, QRectF(0, H / 2 - 26, W, 26), 'GAME OVER', 20, PAL['white'], bold=True,
                          outline=PAL['ol'])
                draw_text(p, QRectF(10, H / 2 + 2, W - 20, 10),
                          _tr('Tokyo has had {n} rainy days…').format(n=session.rain_total), 6, PAL['white'],
                          outline=PAL['ol'])

    def _paint_clear_card(self, p: QPainter, W: float, H: float):
        session = self.session
        fill(p, 0, 0, W, H, (20, 20, 48, 120))
        card = QRectF(int(W / 2 - 76), int(H / 2 - 98), 152, 196)
        pixel_box(p, card)
        year, month = session.year_month
        if session.victory:
            title = _tr('All {n} levels cleared!').format(n=LEVEL_COUNT)
        else:
            title = _tr('Level {n} cleared!').format(n=session.level)
        draw_text(p, QRectF(card.x() + 4, card.y() + 4, card.width() - 8, 12), title, 8, PAL['white'], bold=True,
                  outline=PAL['ol'])
        draw_text(p, QRectF(card.x() + 4, card.y() + 16, card.width() - 8, 8),
                  _tr("Tokyo's weather in {ym}").format(ym=format_year_month(year, month)), 4.6, PAL['ink_soft'])
        cell_w, cell_h = 20, 16
        grid_x = int(card.center().x() - cell_w * 7 / 2)
        grid_y = int(card.y() + 26)
        for i in range(7):
            name = _tr(WEEKDAY_ABBR[(i + 6) % 7])
            color = PAL['danger'] if i == 0 else (PAL['blue_lo'] if i == 6 else PAL['ink_soft'])
            draw_text(p, QRectF(grid_x + i * cell_w, grid_y, cell_w, 6), name, 3.8, color, bold=True)
        first_col = (calendar.weekday(year, month, 1) + 1) % 7
        for i, kind in enumerate(session.month_days):
            slot = first_col + i
            col, row = slot % 7, slot // 7
            rect = QRectF(grid_x + col * cell_w + 1, grid_y + 7 + row * cell_h, cell_w - 2, cell_h - 1)
            fill(p, rect.x(), rect.y(), rect.width(), rect.height(),
                 '#e8f4ff' if not WEATHER_INFO[kind]['rain'] else '#d8dce8')
            draw_text(p, QRectF(rect.x() + 1, rect.y(), 8, 5), str(i + 1), 3, PAL['ink_soft'],
                      align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            draw_image(p, rect.x() + 3, rect.y() + 3, SPRITES.weather(kind, 13, 11))
        sunny = session.month_days.count('sunny')
        rain = sum(1 for kind in session.month_days if WEATHER_INFO[kind]['rain'])
        draw_text(p, QRectF(card.x() + 4, card.bottom() - 52, card.width() - 8, 9),
                  _tr('This month: {s} sunny · {r} rainy').format(s=sunny, r=rain), 5, PAL['ol'], bold=True)
        for i in range(STAR_COUNT):
            draw_image(p, int(card.center().x()) - 32 + i * 13, card.bottom() - 41, SPRITES.star(11, i < session.stars))
        self.btn_next.rect = QRectF(int(card.center().x() - 50), card.bottom() - 25, 100, 17)
        self.btn_next.enabled = self.state_time >= self.CLEAR_LOCK
        draw_button(p, self.btn_next)


# ── 结束画面（Game Over / 全部通关）──────────────────────────────────
class ResultScreen(Screen):
    INPUT_LOCK = 0.8        # 刚出现的这段时间不接受输入，防止手里的空格把结果直接跳过

    def __init__(self, ui):
        super().__init__(ui)
        self.result = None
        self.record = {}
        self.particles = WeatherParticles(seed=11)
        self.scene = SceneCache()
        self.btn_share = self.add_button('share', N_('Share Image'), 'normal', 5.4)
        self.btn_retry = self.add_button('retry', N_('Play Again'), 'primary', 6.5)
        self.btn_menu = self.add_button('menu', N_('Back to Menu'), 'normal', 6.0)

    def set_result(self, result: dict, record: dict):
        self.result = dict(result)
        self.record = dict(record)
        self.time = 0.0
        self.particles.clear()

    def _locked(self) -> bool:
        return self.time < self.INPUT_LOCK

    def on_button(self, key: str):
        if self._locked():
            return
        if key == 'retry':
            self.ui.request_new_game(confirm=False)
        elif key == 'share':
            record = self.record.get('record') or make_record(self.result)
            self.ui.open_share(record)
        else:
            self.ui.show_title()

    def key(self, key: int, auto_repeat: bool) -> bool:
        if auto_repeat or self._locked():
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.on_button('retry')
            return True
        if key == Qt.Key.Key_Escape:
            self.on_button('menu')
            return True
        return False

    def update(self, dt: float):
        super().update(dt)
        W, H = self.ui.art_size()
        victory = bool(self.result and self.result.get('victory'))
        self.particles.update(dt, 'snow' if victory else 'light_rain', QRectF(0, 0, W, H - 20))

    def paint(self, p: QPainter, W: float, H: float):
        result = self.result or GameSession().result()
        victory = bool(result.get('victory'))
        top, bottom = SKY_COLORS['sunny'] if victory else SKY_COLORS['light_rain']
        sky_fill(p, W, H, C(top), C(bottom))
        ground_y = int(H) - 14
        tower_x = int(max(30, W / 2 - 104))
        scene = self.scene.get(int(W) + 1, int(H) + 1, ground_y, tower_x, min(120, ground_y - 70), int(W * 0.8))
        draw_image(p, 0, 0, scene)
        if not victory:
            fill(p, 0, 0, W, ground_y, SCENE_TINT['light_rain'])
        self.particles.draw(p)
        self._paint_card(p, W, H, result, victory)

    def _paint_card(self, p: QPainter, W: float, H: float, result: dict, victory: bool):
        appear = ease_out_cubic(min(1.0, self.time / 0.4))
        card = QRectF(int(W / 2 - 80), int(H / 2 - 100 + (1 - appear) * 12), 160, 200)
        pixel_box(p, card)
        title = _tr('All clear!') if victory else 'GAME OVER'
        draw_text(p, QRectF(card.x(), card.y() + 5, card.width(), 16), title, 12,
                  PAL['sun2'] if victory else PAL['white'], bold=True, outline=PAL['ol'])
        if victory:
            sub = _tr('You decided a whole year of Tokyo weather')
        else:
            sub = _tr("Tokyo's weather diary stopped at {ym}").format(
                ym=format_year_month(result['year'], result['month']))
        draw_text(p, QRectF(card.x() + 4, card.y() + 22, card.width() - 8, 8), sub, 4.6, PAL['ink_soft'])
        draw_text(p, QRectF(card.x(), card.y() + 31, card.width(), 7),
                  _tr('You made it through all') if victory else _tr('You reached'), 4.6, PAL['ink_soft'])
        level_text = _tr('{n} levels').format(n=LEVEL_COUNT) if victory else _tr('Level {n}').format(n=result['level'])
        draw_text(p, QRectF(card.x(), card.y() + 38, card.width(), 15), level_text, 11.5, PAL['ol'], bold=True)
        score = result.get('score', compute_score(result.get('counts', {}), result.get('levels_cleared', 0),
                                                  victory, result.get('stars', 0), result.get('mode', 'normal')))
        draw_text(p, QRectF(card.x(), card.y() + 53, card.width(), 10),
                  _tr('Score {s}').format(s=format_score(score)), 7, PAL['accent'], bold=True)
        tiles = (
            ('heavy_rain', _tr('Rain you gave Tokyo'), result['rain_total'], _tr('rainy days'), PAL['blue_lo'],
             '#e8f4ff'),
            ('sunny', _tr('Sunshine you won for Tokyo'), result['sunny_total'], _tr('sunny days'), PAL['accent'],
             '#fff0c8'),
        )
        for i, (kind, caption, value, unit, color, face) in enumerate(tiles):
            rect = QRectF(card.x() + 6 + i * 75, card.y() + 65, 73, 46)
            pixel_box(p, rect, face, shadow=False)
            draw_text(p, QRectF(rect.x() + 2, rect.y() + 2, rect.width() - 4, 11), caption, 4.2, PAL['ink_soft'],
                      wrap=True)
            draw_image(p, rect.x() + 3, rect.y() + 15, SPRITES.weather(kind, 24, 20))
            draw_text(p, QRectF(rect.x() + 27, rect.y() + 13, rect.width() - 29, 16), str(value), 12, color,
                      bold=True, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            draw_text(p, QRectF(rect.x() + 27, rect.y() + 31, rect.width() - 29, 8), unit, 4.2,
                      PAL['ink_soft'], align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        counts = result.get('counts', {})
        detail = _tr('Partly cloudy {a} · Cloudy {b} · Snow {c} · {d} days in all').format(
            a=counts.get('partly', 0), b=counts.get('cloudy', 0), c=counts.get('snow', 0), d=result.get('days_played', 0))
        draw_text(p, QRectF(card.x() + 4, card.y() + 114, card.width() - 8, 8), detail, 4.2, PAL['ink_soft'])
        mode = mode_label(result.get('mode'))
        if self.record.get('rank'):
            draw_text(p, QRectF(card.x() + 4, card.y() + 123, card.width() - 8, 8),
                      _tr('Leaderboard: #{r} of {n} by score').format(r=self.record['rank'], n=self.record['total']),
                      4.4, PAL['ink_soft'])
        if self.record.get('new_record'):
            record_text = _tr('New record! ({mode})').format(mode=mode)
            record_color = PAL['accent']
        else:
            record_text = _tr('{mode} best: {best}').format(mode=mode, best=best_label(self.record.get('best', 0)))
            record_color = PAL['ink_soft']
        draw_text(p, QRectF(card.x() + 4, card.y() + 131, card.width() - 8, 8), record_text, 4.6, record_color,
                  bold=True)
        self.btn_share.rect = QRectF(int(card.center().x() - 42), card.y() + 143, 84, 14)
        self.btn_retry.rect = QRectF(card.x() + 8, card.bottom() - 25, 70, 17)
        self.btn_menu.rect = QRectF(card.right() - 78, card.bottom() - 25, 70, 17)
        locked = self._locked()
        p.save()
        if locked:
            p.setOpacity(0.35 + 0.65 * appear)
        for button in (self.btn_share, self.btn_retry, self.btn_menu):
            button.enabled = True
            draw_button(p, button)
            button.enabled = not locked
        p.restore()


# ── 排行榜 ─────────────────────────────────────────────────
class LeaderboardScreen(Screen):
    """所有打完的局（游戏结束或全部通关）按不同项目排名；点一行可以给那一局生成分享图。"""

    ROW_H = 11
    SORT_LABELS = {'score': N_('Score'), 'level': N_('Level'), 'sunny': N_('Sunny days'), 'recent': N_('Recent')}
    MODE_FILTERS = ('all', 'easy', 'normal', 'hard')

    def __init__(self, ui):
        super().__init__(ui)
        self.scene = SceneCache()
        self.records = []
        self.sort_key = 'score'
        self.mode = 'all'
        self.page = 0
        self.highlight_id = None
        self.hover_row = -1
        self.row_rects = []
        self.sort_buttons = [self.add_button('sort:' + k, self.SORT_LABELS[k], 'choice', 4.8) for k in LEADERBOARD_SORTS]
        self.mode_buttons = [self.add_button('mode:' + m, N_('All') if m == 'all' else MODES[m]['label'], 'choice', 4.8)
                             for m in self.MODE_FILTERS]
        self.btn_prev = self.add_button('prev', lambda: '<', 'normal', 6)
        self.btn_next = self.add_button('next', lambda: '>', 'normal', 6)
        self.btn_back = self.add_button('back', N_('Back to Menu'), 'normal', 5.6)

    def refresh(self, highlight_id=None):
        self.records = load_records()
        self.highlight_id = highlight_id
        self.page = 0
        if highlight_id:
            rows = sort_records(self.records, self.sort_key, self.mode)
            ids = [r['id'] for r in rows]
            if highlight_id in ids:
                self.page = ids.index(highlight_id) // max(1, self._rows_per_page())

    def _rows_per_page(self) -> int:
        _, H = self.ui.art_size()
        return max(4, int((H - 8 - 62 - 34) // self.ROW_H))

    def rows(self) -> list:
        return sort_records(self.records, self.sort_key, self.mode)

    def animating(self) -> bool:
        return False

    def on_button(self, key: str):
        if key.startswith('sort:'):
            self.sort_key = key.split(':', 1)[1]
            self.page = 0
        elif key.startswith('mode:'):
            self.mode = key.split(':', 1)[1]
            self.page = 0
        elif key == 'prev':
            self.page = max(0, self.page - 1)
        elif key == 'next':
            self.page += 1
        elif key == 'back':
            self.ui.show_title()

    def key(self, key: int, auto_repeat: bool) -> bool:
        if key in (Qt.Key.Key_Escape, Qt.Key.Key_Backspace):
            if not auto_repeat:
                self.ui.show_title()
            return True
        if key == Qt.Key.Key_Left:
            self.on_button('prev')
            return True
        if key == Qt.Key.Key_Right:
            self.on_button('next')
            return True
        return False

    def canvas_press(self, point: QPointF):
        for record, rect in self.row_rects:
            if rect.contains(point):
                self.ui.open_share(record)
                return

    def move(self, point: QPointF) -> bool:
        changed = super().move(point)
        hover = -1
        for i, (_, rect) in enumerate(self.row_rects):
            if rect.contains(point):
                hover = i
        if hover != self.hover_row:
            self.hover_row = hover
            changed = True
        return changed

    def hovering_button(self) -> bool:
        return super().hovering_button() or self.hover_row >= 0

    def clear_hover(self):
        super().clear_hover()
        self.hover_row = -1

    def paint(self, p: QPainter, W: float, H: float):
        sky_fill(p, W, H, C(PAL['sky_title_top']), C(PAL['sky_title_bottom']))
        ground_y = int(H) - 14
        scene = self.scene.get(int(W) + 1, int(H) + 1, ground_y, int(W * 0.86), min(110, ground_y - 70), int(W * 0.3))
        draw_image(p, 0, 0, scene)
        panel = QRectF(8, 5, int(W) - 16, int(H) - 12)
        pixel_box(p, panel)
        draw_text(p, QRectF(panel.x(), panel.y() + 3, panel.width(), 12), _tr('Leaderboard'), 8.5, PAL['white'],
                  bold=True, outline=PAL['ol'])
        x0 = panel.x() + 8
        inner_w = panel.width() - 16
        left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        # 排序 / 难度筛选
        label_w = 26
        draw_text(p, QRectF(x0, panel.y() + 18, label_w, 11), _tr('Sort'), 4.4, PAL['ink_soft'], bold=True, align=left)
        bw = (inner_w - label_w - 3 * 3) / 4
        for i, button in enumerate(self.sort_buttons):
            button.rect = QRectF(int(x0 + label_w + i * (bw + 3)), int(panel.y() + 18), int(bw), 11)
            button.selected = self.sort_key == LEADERBOARD_SORTS[i]
        draw_text(p, QRectF(x0, panel.y() + 32, label_w, 11), _tr('Mode'), 4.4, PAL['ink_soft'], bold=True, align=left)
        for i, button in enumerate(self.mode_buttons):
            button.rect = QRectF(int(x0 + label_w + i * (bw + 3)), int(panel.y() + 32), int(bw), 11)
            button.selected = self.mode == self.MODE_FILTERS[i]
        # 表头
        cols = self._columns(x0, inner_w)
        header_y = panel.y() + 47
        fill(p, x0, header_y, inner_w, 9, PAL['ol'])
        for key, cx, cw, label in cols:
            color = PAL['sun2'] if key == self.sort_key else PAL['white']
            draw_text(p, QRectF(cx + 1, header_y, cw - 2, 9), label, 4.2, color, bold=True)
        rows = self.rows()
        per_page = self._rows_per_page()
        pages = max(1, (len(rows) + per_page - 1) // per_page)
        self.page = int(clamp(self.page, 0, pages - 1))
        shown = rows[self.page * per_page:(self.page + 1) * per_page]
        self.row_rects = []
        y = header_y + 10
        if not rows:
            draw_text(p, QRectF(x0, y + 10, inner_w, 30), _tr('No games yet. Finish a game to get on the board!'),
                      5, PAL['ink_soft'], wrap=True)
        for i, record in enumerate(shown):
            rank = self.page * per_page + i + 1
            rect = QRectF(x0, y, inner_w, self.ROW_H - 1)
            self.row_rects.append((record, rect))
            face = '#fffdf6' if i % 2 == 0 else '#f6ead0'
            if i == self.hover_row:
                face = PAL['btn_hover']
            fill(p, rect.x(), rect.y(), rect.width(), rect.height(), face)
            if record['id'] == self.highlight_id:
                pixel_box(p, rect.adjusted(-1, -1, 1, 1), face, border=PAL['accent'], shadow=False, bevel=False)
            self._paint_row(p, record, rank, rect, cols)
            y += self.ROW_H
        # 翻页 + 返回
        bottom = panel.bottom() - 18
        self.btn_prev.rect = QRectF(x0, bottom, 14, 12)
        self.btn_next.rect = QRectF(x0 + 48, bottom, 14, 12)
        self.btn_prev.enabled = self.page > 0
        self.btn_next.enabled = self.page < pages - 1
        draw_text(p, QRectF(x0 + 14, bottom, 34, 12), '{0} / {1}'.format(self.page + 1, pages), 4.6, PAL['ol'],
                  bold=True)
        self.btn_back.rect = QRectF(int(panel.right() - 8 - 70), bottom - 1, 70, 14)
        if rows:
            draw_text(p, QRectF(x0 + 66, bottom, inner_w - 66 - 76, 12), _tr('Click a game to make a share image'),
                      4, PAL['ink_soft'])
        for button in self.buttons:
            draw_button(p, button)

    def _columns(self, x0: float, width: float) -> list:
        """(排序键, x, 宽, 表头文字)。多出来的宽度都给日期那一列。"""
        spec = [('rank', 16, '#'), ('score', 38, _tr('Score')), ('level', 44, _tr('Level')),
                ('sunny', 30, _tr('Sunny')), ('rain', 26, _tr('Rain')), ('mode', 40, _tr('Mode'))]
        fixed = sum(w for _, w, _ in spec)
        spec.append(('recent', max(40, width - fixed), _tr('Date')))
        cols, x = [], x0
        for key, w, label in spec:
            cols.append((key, x, w, label))
            x += w
        return cols

    def _paint_row(self, p: QPainter, record: dict, rank: int, rect: QRectF, cols: list):
        values = {
            'rank': str(rank),
            'score': format_score(record['score']),
            'level': best_label(record_level_value(record)),
            'sunny': str(record['sunny_total']),
            'rain': str(record['rain_total']),
            'mode': mode_label(record['mode']),
            'recent': format_finished_at(record['finished_at']),
        }
        for key, cx, cw, _ in cols:
            if key == 'rank' and rank <= 3:
                medal = (PAL['sun2'], '#c8c8d8', '#d88840')[rank - 1]
                cy = int(rect.center().y())
                fill(p, cx + 4, cy - 4, 8, 8, PAL['ol'])
                fill(p, cx + 5, cy - 3, 6, 6, medal)
                draw_text(p, QRectF(cx + 4, cy - 4, 8, 8), str(rank), 4, PAL['ol'], bold=True)
                continue
            bold = key in ('score', self.sort_key)
            draw_text(p, QRectF(cx + 1, rect.y(), cw - 2, rect.height()), values[key], 4.4,
                      PAL['ol'] if key != 'rain' else PAL['blue_lo'], bold=bold)


# ── 分享图（1200×630，像素风）──────────────────────────────────────
SHARE_ART_W, SHARE_ART_H, SHARE_SCALE = 400, 210, 3
DIARY_COLORS = {'sunny': '#f8b800', 'partly': '#fce0a8', 'cloudy': '#a8a8b8', 'light_rain': '#3cbcfc',
                'heavy_rain': '#0058b8', 'snow': '#fcfcfc'}


def render_share_card(record: dict) -> QImage:
    """把一局的结果画成一张分享图：标题、结局、分数、雨天/晴天，右边是一整年的"天气日记"。
    按当前界面语言出图；底图 400×210 像素格，放大 3 倍 = 1200×630（社交平台常用尺寸）。"""
    W, H, k = SHARE_ART_W, SHARE_ART_H, SHARE_SCALE
    image = QImage(W * k, H * k, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(C(PAL['ol']))
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    p.scale(k, k)
    victory = bool(record.get('victory'))
    top, bottom = SKY_COLORS['sunny'] if victory else SKY_COLORS['light_rain']
    sky_fill(p, W, H, C(top), C(bottom))
    for cx, cy, cw in ((150, 150, 40), (268, 168, 30)):
        draw_image(p, cx, cy, SPRITES.get(('bigcloud', cw), lambda cw=cw: big_cloud_grid(cw)))
    scene = build_scene_image(W + 1, H + 1, H - 16, 380, 104, 110)
    draw_image(p, 0, 0, scene)
    if not victory:
        fill(p, 0, 0, W, H - 16, SCENE_TINT['light_rain'])
    left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    # 左边：名字、标题、结局、分数、雨天/晴天
    badge = QRectF(10, 8, 50, 10)
    pixel_box(p, badge, shadow=False)
    draw_text(p, badge, 'TokyoAme', 5, PAL['ol'], bold=True)
    draw_text(p, QRectF(10, 20, 156, 34), _tr("Are You Tokyo's Better Weather God?"), 11, PAL['white'], bold=True,
              align=left, outline=PAL['ol'], wrap=True)
    headline = _tr('All clear!') if victory else 'GAME OVER'
    draw_text(p, QRectF(10, 56, 156, 14), headline, 11, PAL['sun2'] if victory else PAL['white'], bold=True,
              align=left, outline=PAL['ol'])
    year, month = level_month(record.get('start_year', datetime.date.today().year), record['level'])
    if victory:
        reached = _tr('{n} levels').format(n=LEVEL_COUNT)
    else:
        reached = _tr('Level {n}').format(n=record['level']) + ' · ' + format_year_month(year, month)
    draw_text(p, QRectF(10, 70, 160, 9), reached + ' · ' + mode_label(record['mode']), 5, PAL['white'],
              bold=True, align=left, outline=PAL['ol'])
    tiles = (
        (None, _tr('Score'), format_score(record['score']), PAL['accent'], PAL['paper']),
        ('heavy_rain', _tr('Rain'), str(record['rain_total']), PAL['blue_lo'], '#e8f4ff'),
        ('sunny', _tr('Sunny'), str(record['sunny_total']), PAL['accent'], '#fff0c8'),
    )
    x = 10
    for kind, caption, value, color, face in tiles:
        w = 60 if kind is None else 48
        rect = QRectF(x, 84, w, 38)
        pixel_box(p, rect, face)
        draw_text(p, QRectF(rect.x() + 2, rect.y() + 2, rect.width() - 4, 7), caption, 4.2, PAL['ink_soft'],
                  bold=True)
        if kind is None:
            draw_text(p, QRectF(rect.x() + 2, rect.y() + 12, rect.width() - 4, 18), value, 11, color, bold=True)
        else:
            draw_image(p, rect.x() + 3, rect.y() + 13, SPRITES.weather(kind, 18, 15))
            draw_text(p, QRectF(rect.x() + 21, rect.y() + 11, rect.width() - 23, 18), value, 10, color, bold=True,
                      align=left)
            draw_text(p, QRectF(rect.x() + 21, rect.y() + 27, rect.width() - 23, 7), _tr('days'), 3.8,
                      PAL['ink_soft'], align=left)
        x += w + 4
    draw_text(p, QRectF(10, 126, 160, 7), _tr('Played on {date}').format(
        date=format_finished_at(record.get('finished_at', ''))[:10]), 4.2, PAL['white'], align=left,
        outline=PAL['ol'])
    # 右边：一整年的天气日记（每行一个月，每格一天）
    panel = QRectF(176, 8, 180, 150)
    pixel_box(p, panel)
    draw_text(p, QRectF(panel.x(), panel.y() + 2, panel.width(), 9), _tr('Weather diary'), 5.2, PAL['ol'], bold=True)
    months = decode_diary(record.get('diary', ''))
    start_year = record.get('start_year', datetime.date.today().year)
    gx, gy = panel.x() + 18, panel.y() + 14
    for m in range(LEVEL_COUNT):
        yy = gy + m * 10
        draw_text(p, QRectF(panel.x() + 2, yy + 1, 15, 8), month_name(m + 1), 3.6, PAL['ink_soft'], bold=True,
                  align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        days = days_in_month(start_year, m + 1)
        month = months[m] if m < len(months) else []
        for d in range(days):
            cx = gx + d * 5
            if month is None:
                fill(p, cx, yy + 1, 4, 8, (0, 0, 0, 40))
            elif d < len(month):
                kind = month[d]
                fill(p, cx, yy + 1, 4, 8, PAL['ol'] if kind == 'snow' else DIARY_COLORS[kind])
                if kind == 'snow':
                    fill(p, cx + 1, yy + 2, 2, 6, DIARY_COLORS['snow'])
            else:
                fill(p, cx, yy + 1, 4, 8, (0, 0, 0, 18))
    # 图例
    lx = panel.x() + 6
    for kind in WEATHER_ORDER:
        fill(p, lx, panel.bottom() - 11, 4, 6, PAL['ol'] if kind == 'snow' else DIARY_COLORS[kind])
        if kind == 'snow':
            fill(p, lx + 1, panel.bottom() - 10, 2, 4, DIARY_COLORS['snow'])
        draw_text(p, QRectF(lx + 5, panel.bottom() - 13, 24, 9), _tr(WEATHER_INFO[kind]['label']), 3.4,
                  PAL['ink_soft'], align=left)
        lx += 28
    p.end()
    return image


def share_file_name(record: dict) -> str:
    stamp = format_finished_at(record.get('finished_at', '')).replace(':', '').replace(' ', '_')
    return 'TokyoAme_{0}.png'.format(stamp or 'result')


def default_share_dir() -> str:
    for folder in (os.path.join(str(Path.home()), 'Pictures'), os.path.join(str(Path.home()), 'Desktop'),
                   str(Path.home())):
        if os.path.isdir(folder):
            return folder
    return str(Path.home())


# ── 浮层：设置 / 玩法说明 / 确认 ─────────────────────────────────────
class SettingsOverlay(Overlay):
    PANEL_W = 216

    def __init__(self, ui):
        super().__init__(ui)
        self.in_game = False
        self.mode_buttons = [self.add_button('mode:' + m, MODES[m]['label'], 'choice', 5.4) for m in MODE_ORDER]
        self.btn_minus = self.add_button('speed:-', lambda: '−', 'normal', 7)
        self.btn_plus = self.add_button('speed:+', lambda: '+', 'normal', 7)
        self.btn_timer = self.add_button('timer', self._timer_label, 'choice', 5.2)
        self.btn_music = self.add_button('music', self._music_label, 'choice', 5.2)
        self.lang_buttons = [self.add_button('lang:' + code, (lambda name=name: name), 'choice', 5.4)
                             for code, name in UI_LANGUAGES]
        self.btn_reset = self.add_button('reset', N_('Reset'), 'normal', 5.4)
        self.btn_done = self.add_button('done', N_('Done'), 'primary', 5.4)
        self.slider_rect = QRectF()
        self._dragging = False

    def _timer_label(self) -> str:
        return _tr('ON') if self.ui.settings.get('day_timer', True) else _tr('OFF')

    def _music_label(self) -> str:
        return _tr('ON') if self.ui.settings.get('music', True) else _tr('OFF')

    def panel_height(self, W, H):
        # 内容：标题到语言按钮 137 格，再加按钮 14 格、底边 6 格；有音乐开关时多一行 16 格
        return 157 + (16 if self.ui.music.available else 0)

    def _change(self, **changes):
        settings = dict(self.ui.settings)
        settings.update(changes)
        self.ui.apply_settings(settings)

    def on_button(self, key: str):
        settings = self.ui.settings
        if key.startswith('mode:'):
            self._change(mode=key.split(':', 1)[1])
        elif key == 'speed:-':
            self._change(speed_percent=clamp_speed_percent(settings['speed_percent'] - SPEED_PERCENT_STEP))
        elif key == 'speed:+':
            self._change(speed_percent=clamp_speed_percent(settings['speed_percent'] + SPEED_PERCENT_STEP))
        elif key == 'timer':
            self._change(day_timer=not settings.get('day_timer', True))
        elif key == 'music':
            self._change(music=not settings.get('music', True))
        elif key.startswith('lang:'):
            self._change(language=key.split(':', 1)[1])
        elif key == 'reset':
            defaults = default_settings()
            self._change(mode=defaults['mode'], speed_percent=defaults['speed_percent'],
                         day_timer=defaults['day_timer'])
        elif key in ('done', 'close'):
            self.ui.close_overlay(self)

    # 速度格：点哪一格就是哪一档，也可以按住拖
    def _speed_from_x(self, x: float) -> int:
        steps = (SPEED_PERCENT_MAX - SPEED_PERCENT_MIN) // SPEED_PERCENT_STEP + 1
        ratio = clamp((x - self.slider_rect.x()) / max(1.0, self.slider_rect.width()), 0.0, 0.999)
        return SPEED_PERCENT_MIN + int(ratio * steps) * SPEED_PERCENT_STEP

    def press(self, point: QPointF) -> bool:
        if self.slider_rect.adjusted(0, -3, 0, 3).contains(point):
            self._dragging = True
            self._change(speed_percent=self._speed_from_x(point.x()))
            return True
        return super().press(point)

    def move(self, point: QPointF) -> bool:
        if self._dragging:
            value = self._speed_from_x(point.x())
            if value != self.ui.settings['speed_percent']:
                self._change(speed_percent=value)
            return True
        return super().move(point)

    def release(self, point: QPointF):
        if self._dragging:
            self._dragging = False
            return
        super().release(point)

    def clear_hover(self):
        super().clear_hover()
        self._dragging = False

    def key(self, key: int, auto_repeat: bool) -> bool:
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if not auto_repeat:
                self.ui.close_overlay(self)
            return True
        return super().key(key, auto_repeat)

    def paint_panel(self, p: QPainter, r: QRectF):
        settings = self.ui.settings
        left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        x, w = r.x() + 10, r.width() - 20
        y = r.y() + 5
        draw_text(p, QRectF(r.x(), y, r.width(), 12), _tr('Settings'), 8, PAL['white'], bold=True, outline=PAL['ol'])
        y += 15
        draw_text(p, QRectF(x, y, w, 7), _tr('Difficulty'), 5, PAL['ol'], bold=True, align=left)
        y += 8
        bw = (w - 8) / 3
        for i, button in enumerate(self.mode_buttons):
            button.rect = QRectF(int(x + i * (bw + 4)), int(y), int(bw), 13)
            button.selected = settings['mode'] == MODE_ORDER[i]
        y += 15
        draw_text(p, QRectF(x, y, w, 7), _tr(MODES[settings['mode']]['desc']), 4.2, PAL['ink_soft'], align=left)
        y += 7
        if self.in_game:
            draw_text(p, QRectF(x, y, w, 6), _tr('A game is in progress: difficulty applies from the next game'),
                      3.8, PAL['accent'], align=left)
        y += 8
        draw_text(p, QRectF(x, y, w - 30, 7), _tr('Scroll speed'), 5, PAL['ol'], bold=True, align=left)
        draw_text(p, QRectF(x + w - 30, y, 30, 7), '{0}%'.format(settings['speed_percent']), 5, PAL['ol'], bold=True,
                  align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        y += 9
        self.btn_minus.rect = QRectF(int(x), int(y), 12, 11)
        self.btn_plus.rect = QRectF(int(x + w - 12), int(y), 12, 11)
        steps = (SPEED_PERCENT_MAX - SPEED_PERCENT_MIN) // SPEED_PERCENT_STEP + 1
        track_x = x + 16
        track_w = w - 32
        cell = track_w / steps
        self.slider_rect = QRectF(track_x, y, track_w, 11)
        current = (settings['speed_percent'] - SPEED_PERCENT_MIN) // SPEED_PERCENT_STEP
        for i in range(steps):
            cx = int(track_x + i * cell)
            cw = max(2, int(cell) - 1)
            height = 4 + int(6 * i / (steps - 1))
            color = PAL['sun2'] if i == current else (PAL['accent'] if i < current else PAL['grey1'])
            fill(p, cx, y + 11 - height, cw, height, PAL['ol'])
            fill(p, cx + 1, y + 12 - height, cw - 2, height - 2, color)
        y += 13
        draw_text(p, QRectF(x, y, w, 6),
                  _tr('Speed has a ceiling: even level {n} stays readable and clickable').format(n=LEVEL_COUNT), 3.8,
                  PAL['ink_soft'], align=left)
        y += 10
        draw_text(p, QRectF(x, y, w - 40, 7), _tr('Daily time limit'), 5, PAL['ol'], bold=True, align=left)
        draw_text(p, QRectF(x, y + 7, w - 40, 12), _tr("When time runs out, the weather above Tokyo becomes today's"),
                  3.8, PAL['ink_soft'], align=left, wrap=True)
        self.btn_timer.rect = QRectF(int(x + w - 32), int(y + 2), 32, 13)
        self.btn_timer.selected = bool(settings.get('day_timer', True))
        y += 22
        self.btn_music.visible = self.ui.music.available
        if self.btn_music.visible:
            draw_text(p, QRectF(x, y, w - 40, 13), _tr('Background music'), 5, PAL['ol'], bold=True, align=left)
            self.btn_music.rect = QRectF(int(x + w - 32), int(y), 32, 13)
            self.btn_music.selected = bool(settings.get('music', True))
            y += 16
        draw_text(p, QRectF(x, y, w, 7), _tr('Language'), 5, PAL['ol'], bold=True, align=left)
        y += 8
        for i, button in enumerate(self.lang_buttons):
            button.rect = QRectF(int(x + i * (bw + 4)), int(y), int(bw), 13)
            button.selected = settings['language'] == UI_LANGUAGES[i][0]
        y += 17
        bottom = int(min(y, r.bottom() - 19))
        self.btn_reset.rect = QRectF(int(r.center().x() - 64), bottom, 60, 14)
        self.btn_done.rect = QRectF(int(r.center().x() + 4), bottom, 60, 14)


class HelpOverlay(Overlay):
    PANEL_W = 236

    def __init__(self, ui):
        super().__init__(ui)
        self.btn_ok = self.add_button('ok', N_('Got it'), 'primary', 5.6)

    def panel_height(self, W, H):
        return 198

    def rules(self) -> list:
        return [
            _tr('The weather strip at the top keeps sliding from left to right.'),
            _tr("Click anywhere (or press Space): the weather right above Tokyo Tower becomes today's weather."),
            _tr('One level = one month. Decide every day of the month to clear it. {n} levels, January to December, '
                'each one faster.').format(n=LEVEL_COUNT),
            _tr('Light rain and heavy rain both count as rain. Every {n} rainy days in total (in a row or not) '
                'cost you a star.').format(n=RAIN_DAYS_PER_STAR),
            _tr('Lose all {s} stars ({d} rainy days) and the game is over. Stars carry over between levels and '
                'never come back.').format(s=STAR_COUNT, d=STAR_COUNT * RAIN_DAYS_PER_STAR),
            _tr('A picked cloud falls on Tokyo and cannot be picked again.'),
            _tr('Each day has a time limit (can be turned off in Settings): when it runs out, the weather above '
                'Tokyo is picked for you.'),
            _tr('Progress is saved automatically. Press Esc to pause.'),
        ]

    def on_button(self, key: str):
        if key in ('ok', 'close'):
            self.ui.close_overlay(self)

    def key(self, key: int, auto_repeat: bool) -> bool:
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if not auto_repeat:
                self.ui.close_overlay(self)
            return True
        return super().key(key, auto_repeat)

    def paint_panel(self, p: QPainter, r: QRectF):
        draw_text(p, QRectF(r.x(), r.y() + 5, r.width(), 12), _tr('How to Play'), 8, PAL['white'], bold=True,
                  outline=PAL['ol'])
        rules = self.rules()
        top = r.y() + 20
        bottom = r.bottom() - 30
        row_h = (bottom - top) / len(rules)
        for i, text in enumerate(rules):
            y = top + i * row_h
            badge = QRectF(r.x() + 8, int(y + 1), 8, 8)
            fill(p, badge.x(), badge.y(), badge.width(), badge.height(), PAL['ol'])
            fill(p, badge.x() + 1, badge.y() + 1, badge.width() - 2, badge.height() - 2, PAL['accent'])
            draw_text(p, badge, str(i + 1), 4.4, PAL['white'], bold=True)
            draw_text(p, QRectF(r.x() + 20, y, r.width() - 28, row_h - 1), text, 4.5, PAL['ol'],
                      align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, wrap=True)
        if self.ui.music.available:
            draw_text(p, QRectF(r.x() + 8, r.bottom() - 29, r.width() - 16, 7),
                      _tr('Music') + ': ' + MUSIC_CREDIT, 3.6, PAL['ink_soft'])
        self.btn_ok.rect = QRectF(int(r.center().x() - 30), int(r.bottom() - 19), 60, 14)


class ShareOverlay(Overlay):
    """分享图预览：保存成 PNG，或者复制到剪贴板（再粘贴到聊天软件、社交平台）。"""

    PANEL_W = 300

    def __init__(self, ui):
        super().__init__(ui)
        self.record = None
        self.image = None
        self.status = ''
        self.status_color = PAL['ink_soft']
        self.btn_save = self.add_button('save', N_('Save Image…'), 'primary', 5.4)
        self.btn_copy = self.add_button('copy', N_('Copy Image'), 'normal', 5.4)
        self.btn_done = self.add_button('done', N_('Close'), 'normal', 5.4)

    def set_record(self, record: dict):
        self.record = dict(record)
        self.image = render_share_card(self.record)
        self.status = ''

    def panel_height(self, W, H):
        return 196

    def save_to(self, path: str) -> bool:
        ok = bool(self.image is not None and path and self.image.save(path, 'PNG'))
        if ok:
            self.status = _tr('Saved: {name}').format(name=os.path.basename(path))
            self.status_color = PAL['blue_lo']
        else:
            self.status = _tr('Could not save the image')
            self.status_color = PAL['danger']
        return ok

    def on_button(self, key: str):
        if key == 'save' and self.image is not None:
            default = os.path.join(default_share_dir(), share_file_name(self.record or {}))
            path, _ = QFileDialog.getSaveFileName(self.ui, _tr('Save Image…'), default, 'PNG (*.png)')
            if path:
                if not path.lower().endswith('.png'):
                    path += '.png'
                self.save_to(path)
        elif key == 'copy' and self.image is not None:
            QGuiApplication.clipboard().setImage(self.image)
            self.status = _tr('Copied! Paste it anywhere to share')
            self.status_color = PAL['blue_lo']
        elif key in ('done', 'close'):
            self.ui.close_overlay(self)

    def paint_panel(self, p: QPainter, r: QRectF):
        draw_text(p, QRectF(r.x(), r.y() + 4, r.width(), 12), _tr('Share Image'), 8, PAL['white'], bold=True,
                  outline=PAL['ol'])
        if self.image is not None:
            ph = min(r.height() - 19 - 36, (r.width() - 16) * self.image.height() / self.image.width())
            pw = ph * self.image.width() / self.image.height()
            target = QRectF(int(r.center().x() - pw / 2), r.y() + 19, pw, ph)
            fill(p, target.x() - 1, target.y() - 1, target.width() + 2, target.height() + 2, PAL['ol'])
            p.save()
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p.drawImage(target, self.image)
            p.restore()
            y = target.bottom() + 4
        else:
            y = r.y() + 40
        draw_text(p, QRectF(r.x() + 8, y, r.width() - 16, 7), self.status or _tr('1200 × 630 PNG, ready to post'),
                  4.4, self.status_color if self.status else PAL['ink_soft'])
        bw = (r.width() - 16 - 8) / 3
        for i, button in enumerate((self.btn_save, self.btn_copy, self.btn_done)):
            button.rect = QRectF(int(r.x() + 8 + i * (bw + 4)), int(r.bottom() - 20), int(bw), 14)


class ConfirmOverlay(Overlay):
    PANEL_W = 180
    INPUT_LOCK = 0.3

    def __init__(self, ui):
        super().__init__(ui)
        self.btn_cancel = self.add_button('cancel', N_('Cancel'), 'normal', 5.6)
        self.btn_ok = self.add_button('ok', N_('Start Over'), 'primary', 5.6)

    def panel_height(self, W, H):
        return 74

    def on_button(self, key: str):
        if key == 'ok':
            self.ui.close_overlay(self)
            self.ui.start_new_game()
        elif key in ('cancel', 'close'):
            self.ui.close_overlay(self)

    def key(self, key: int, auto_repeat: bool) -> bool:
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not auto_repeat and self.time >= self.INPUT_LOCK:
                self.on_button('ok')
            return True
        return super().key(key, auto_repeat)

    def paint_panel(self, p: QPainter, r: QRectF):
        draw_text(p, QRectF(r.x(), r.y() + 5, r.width(), 12), _tr('Start a new game?'), 7, PAL['white'], bold=True,
                  outline=PAL['ol'])
        draw_text(p, QRectF(r.x() + 10, r.y() + 20, r.width() - 20, 22),
                  _tr('Your saved progress will be replaced by the new game.'), 4.8, PAL['ol'], wrap=True)
        self.btn_cancel.rect = QRectF(int(r.center().x() - 66), int(r.bottom() - 21), 62, 14)
        self.btn_ok.rect = QRectF(int(r.center().x() + 4), int(r.bottom() - 21), 62, 14)


# ── 背景音乐 ─────────────────────────────────────────────────
class MusicPlayer:
    """主页/排行榜/结束画面放 menu 曲，游戏中放 game 曲，循环播放。没有 QtMultimedia 或缺文件就不放。"""

    def __init__(self, parent):
        self.player = None
        self.output = None
        self.current = None
        self.paths = {key: find_resource('music', name) for key, name in MUSIC_TRACKS.items()}
        self.available = QMediaPlayer is not None and any(self.paths.values())
        if not self.available:
            return
        try:
            self.output = QAudioOutput(parent)
            self.output.setVolume(MUSIC_VOLUME)
            self.player = QMediaPlayer(parent)
            self.player.setAudioOutput(self.output)
            self.player.setLoops(QMediaPlayer.Loops.Infinite)
        except Exception:
            self.available = False
            self.player = None

    def play(self, track: str, enabled: bool):
        if not self.available:
            return
        path = self.paths.get(track) or next((p for p in self.paths.values() if p), None)
        if not enabled or path is None:
            self.stop()
            return
        if self.current == path and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            return
        if self.current != path:
            self.player.setSource(QUrl.fromLocalFile(path))
            self.current = path
        self.player.play()

    def stop(self):
        if self.player is not None:
            self.player.stop()
        self.current = None


# ── 画布：唯一的界面控件，管理画面切换、输入、帧循环 ─────────────────────────
class GameCanvas(QWidget):
    FRAME_MS = 16

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.settings = load_settings()
        apply_ui_language(self.settings['language'])
        self._geometry = (1.0, 0.0, 0.0, float(ART_W), float(ART_H))
        self.music = MusicPlayer(self)
        self.title = TitleScreen(self)
        self.play = PlayScreen(self)
        self.result = ResultScreen(self)
        self.leaderboard = LeaderboardScreen(self)
        self.settings_overlay = SettingsOverlay(self)
        self.help_overlay = HelpOverlay(self)
        self.confirm_overlay = ConfirmOverlay(self)
        self.share_overlay = ShareOverlay(self)
        self.screen = self.title
        self.overlays = []
        self._press_origin = None
        self._over_record = None
        self.clock = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self.quit_callback = None
        self.title.refresh()

    # ── 几何：像素格 ↔ 屏幕 ──
    def _compute_geometry(self):
        """算出每个像素格多大。能用整数倍就用整数倍（像素方正），整数倍会让画面缩小超过 10% 时才用小数倍。"""
        dpr = max(1.0, self.devicePixelRatioF())
        pw, ph = max(1.0, self.width() * dpr), max(1.0, self.height() * dpr)
        k = min(pw / ART_W, ph / ART_H)
        if k >= 2 and math.floor(k) / k >= 0.9:
            k = float(math.floor(k))
        art_w, art_h = math.floor(pw / k), math.floor(ph / k)
        ox = math.floor((pw - art_w * k) / 2.0) / dpr
        oy = math.floor((ph - art_h * k) / 2.0) / dpr
        self._geometry = (k / dpr, ox, oy, float(art_w), float(art_h))

    def art_size(self):
        return self._geometry[3], self._geometry[4]

    def to_art(self, pos) -> QPointF:
        s, ox, oy, _, _ = self._geometry
        return QPointF((pos.x() - ox) / s, (pos.y() - oy) / s)

    def resizeEvent(self, event):
        self._compute_geometry()
        super().resizeEvent(event)

    def showEvent(self, event):
        self._compute_geometry()
        super().showEvent(event)
        self.update_music()
        self.kick()

    def hideEvent(self, event):
        self.timer.stop()
        self.music.stop()
        super().hideEvent(event)

    # ── 帧循环 ──
    def kick(self):
        """有东西在动就开着帧循环；全都静止（例如暂停中）就停掉省电。"""
        self.update()
        if self.isVisible() and self._needs_frames() and not self.timer.isActive():
            self.clock.restart()
            self.timer.start(self.FRAME_MS)

    def _needs_frames(self) -> bool:
        if any(overlay.animating() for overlay in self.overlays):
            return True
        return self.screen.animating()

    def _tick(self):
        dt = min(0.05, self.clock.restart() / 1000.0)
        self.step(dt)
        self.update()
        if not self._needs_frames():
            self.timer.stop()

    def step(self, dt: float):
        self.screen.update(dt)
        for overlay in list(self.overlays):
            overlay.update(dt)

    # ── 绘制 ──
    def paintEvent(self, event):
        p = QPainter(self)
        try:
            self._compute_geometry()
            s, ox, oy, W, H = self._geometry
            p.fillRect(self.rect(), C(PAL['ol']))
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            p.translate(ox, oy)
            p.scale(s, s)
            p.setClipRect(QRectF(0, 0, W, H))
            self.screen.paint(p, W, H)
            for overlay in self.overlays:
                overlay.paint(p, W, H)
        finally:
            p.end()

    # ── 输入 ──
    def _target(self) -> Screen:
        return self.overlays[-1] if self.overlays else self.screen

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        target = self._target()
        self._press_origin = self._origin_token(target)     # 先记下按下前的画面和状态，再处理
        target.press(self.to_art(event.position()))
        self.kick()

    def _origin_token(self, target):
        return (id(target), getattr(target, 'state', None), len(self.overlays))

    def mouseDoubleClickEvent(self, event):
        # 双击 = 两次按下。第一下之后画面或状态变了（比如开始了本关、打开了浮层），第二下就不算，
        # 免得多定一天；什么都没变（比如连点速度 +）就照常算第二次点击。
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._origin_token(self._target()) != getattr(self, '_press_origin', None):
            return
        self.mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._target().release(self.to_art(event.position()))
        self.kick()

    def mouseMoveEvent(self, event):
        target = self._target()
        changed = target.move(self.to_art(event.position()))
        self.setCursor(Qt.CursorShape.PointingHandCursor if target.hovering_button() else Qt.CursorShape.ArrowCursor)
        if changed:
            self.kick()

    def leaveEvent(self, event):
        self._target().clear_hover()
        self.update()
        super().leaveEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_M and not event.isAutoRepeat() and self.music.available:
            self.toggle_music()
            return
        if self._target().key(event.key(), event.isAutoRepeat()):
            self.kick()
            return
        super().keyPressEvent(event)

    # ── 画面切换 ──
    def _switch(self, screen: Screen):
        self.screen.clear_hover()
        screen.clear_hover()
        self.screen = screen
        screen.time = 0.0
        self.update_music()
        self.kick()

    def update_music(self):
        self.music.play('game' if self.screen is self.play else 'menu', bool(self.settings.get('music', True)))

    def toggle_music(self):
        settings = dict(self.settings)
        settings['music'] = not settings.get('music', True)
        self.apply_settings(settings)

    def show_leaderboard(self, highlight_id=None):
        self.overlays = []
        self.leaderboard.refresh(highlight_id)
        self._switch(self.leaderboard)

    def open_share(self, record: dict):
        self.share_overlay.set_record(record)
        self.open_overlay(self.share_overlay)

    def show_title(self):
        self.overlays = []
        self.title.refresh()
        self._switch(self.title)

    def continue_game(self):
        session = load_game()
        if session is None:
            self.title.refresh()
            self.kick()
            return
        self.screen = self.play
        self.play.begin(session, resumed=True)
        self._switch(self.play)

    def request_new_game(self, confirm: bool = True):
        if confirm and load_game() is not None:
            self.open_overlay(self.confirm_overlay)
        else:
            self.start_new_game()

    def start_new_game(self):
        clear_save()
        self.overlays = []
        self.screen = self.play
        self.play.begin(GameSession(self.settings.get('mode', 'normal')))
        self._switch(self.play)

    def finish_game(self, result: dict):
        clear_save()
        record = self._over_record if self._over_record is not None else self.update_records(result)
        self._over_record = None
        self.result.set_result(result, record)
        self._switch(self.result)

    def game_over_reached(self):
        """星星用完的那一刻：删存档并立刻记下这一局（动画没播完就关窗口也不会丢）。"""
        clear_save()
        self._over_record = self.update_records(self.play.session.result())

    def autosave(self) -> bool:
        session = self.play.session
        if self.screen is not self.play or session is None or session.game_over or self.play.state in ('over', 'done'):
            return False
        return save_game(session)

    def update_records(self, result: dict) -> dict:
        mode = result.get('mode', 'normal')
        by_mode = self.settings.setdefault('best_by_mode', {m: 0 for m in MODE_ORDER})
        best_before = int(by_mode.get(mode, 0))
        level = LEVEL_COUNT + 1 if result.get('victory') else int(result['level'])
        by_mode[mode] = max(best_before, level)
        self.settings['best_sunny'] = max(int(self.settings.get('best_sunny', 0)), int(result['sunny_total']))
        self.settings['games_played'] = int(self.settings.get('games_played', 0)) + 1
        save_settings(self.settings)
        record = make_record(result)
        records = add_record(record)
        ranked = [r['id'] for r in sort_records(records, 'score')]
        rank = ranked.index(record['id']) + 1 if record['id'] in ranked else 0
        return {'new_record': best_before > 0 and level > best_before, 'best': by_mode[mode],
                'record': record, 'rank': rank, 'total': len(records)}

    # ── 浮层 ──
    def open_overlay(self, overlay: Overlay):
        if overlay in self.overlays:
            return
        self._target().clear_hover()
        overlay.time = 0.0
        overlay.clear_hover()
        if overlay is self.settings_overlay:
            # 游戏中、或者主页上有存档时：难度改动只对下一局生效（"继续游戏"沿用存档的难度）
            overlay.in_game = ((self.screen is self.play and self.play.session is not None)
                               or (self.screen is self.title and self.title.saved is not None))
        self.overlays.append(overlay)
        self.kick()

    def close_overlay(self, overlay: Overlay):
        if overlay in self.overlays:
            overlay.clear_hover()
            self.overlays.remove(overlay)
        self.kick()

    def open_settings(self):
        self.open_overlay(self.settings_overlay)

    def open_help(self):
        self.open_overlay(self.help_overlay)

    def apply_settings(self, settings: dict):
        language_changed = settings.get('language') != self.settings.get('language')
        self.settings = settings
        save_settings(settings)
        if language_changed:
            apply_ui_language(settings['language'])
            self.play.toasts = []
        if self.play.session is not None:
            self.play.apply_settings(settings)
        self.update_music()
        self.kick()

    def quit_requested(self):
        if self.quit_callback is not None:
            self.quit_callback()

    # ── 窗口事件 ──
    def on_deactivate(self):
        """切到别的窗口时自动暂停（并存档），免得白白掉星。"""
        if self.screen is self.play:
            self.play.pause()
            self.kick()

    def on_close(self):
        self.autosave()


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(NAME)
        self.setWindowIcon(make_app_icon())
        self.setMinimumSize(880, 590)
        self.resize(1000, 680)
        self.canvas = GameCanvas(self)
        self.canvas.quit_callback = self.close
        self.canvas.setGeometry(self.rect())
        self.canvas.setFocus()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.canvas.setGeometry(self.rect())

    def changeEvent(self, event):
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            self.canvas.on_deactivate()
        super().changeEvent(event)

    def closeEvent(self, event):
        self.canvas.on_close()
        super().closeEvent(event)


def main():
    # 大号文字走 Qt 的字形缓存（默认上限太小，Retina 上大标题会每帧重新描路径，很费电）
    os.environ.setdefault('QT_MAX_CACHED_GLYPH_SIZE', '512')
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(NAME)
    app.setApplicationDisplayName(NAME)
    app.setWindowIcon(make_app_icon())
    if FONT_FAMILY:
        app.setFont(QFont(FONT_FAMILY))
    window = MainWindow()
    window.show()
    window.raise_()
    window.activateWindow()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
