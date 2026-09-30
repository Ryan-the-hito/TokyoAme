#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 TokyoAme 的 Qt Linguist 翻译文件（.ts），再编译成 .qm。

做法与 Broccoli 的 i18n/gen_ts.py 相同：程序里所有要显示的英文都包在 _tr('...') 里，
表格里的字符串用 N_('...') 标记。pylupdate6 认不出这两个包装函数，所以由本脚本用 ast
把它们提取出来，再和下面的 TRANSLATIONS 对照表合并，输出
i18n/tokyoame_zh_CN.ts 和 i18n/tokyoame_ja_JP.ts；表里缺的字符串会标成 unfinished
（界面上回退显示英文，不会出错）。

用法：
    python3 i18n/gen_ts.py            # 重新生成两个 .ts，并尝试用 lrelease 编译 .qm
    python3 i18n/gen_ts.py --no-qm    # 只生成 .ts

以后加新的界面文字：包 _tr（或表格里用 N_）→ 在下面补中/日翻译 → 重跑本脚本。
占位符（{n}、{mode} 这类）必须原样保留；日期格式里中日文用 {m}（月份数字），英文用 {mon}（月份缩写）。
"""
import ast
import os
import shutil
import subprocess
import sys
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, '..', 'ame.py')
CONTEXT = 'TokyoAme'
MARKERS = ('_tr', 'N_')
LANGUAGES = (('zh_CN', 0), ('ja_JP', 1))

# {英文原文: (简体中文, 日本語)}
TRANSLATIONS = {
    # ---- 标题 / 主菜单 ----
    # 日文标题手动断在「東京の」之后，两行更好读
    "Are You Tokyo's Better Weather God?": ('你是东京更好的老天爷吗？', 'きみは東京の\nもっといい天気の神さま？'),
    "Click to decide Tokyo's weather, one day at a time": ('点一下，替东京决定今天的天气', 'クリックして、東京の天気を一日ずつ決めよう'),
    'Continue': ('继续游戏', 'つづきから'),
    'New Game': ('新游戏', 'はじめから'),
    'Settings': ('设置', '設定'),
    'How to Play': ('玩法说明', 'あそびかた'),
    'Quit': ('退出', '終了'),
    'Level {n} · {date} · {mode}': ('第 {n} 关 · {date} · {mode}', 'ステージ {n} · {date} · {mode}'),
    '{mode} · Speed {pct}%': ('{mode}模式 · 速度 {pct}%', '{mode}モード · スピード {pct}%'),
    'Best: {best}': ('最佳纪录：{best}', 'ベスト：{best}'),
    'All clear': ('全部通关', 'オールクリア'),
    'All clear!': ('全部通关！', 'オールクリア！'),
    'Level {n}': ('第 {n} 关', 'ステージ {n}'),
    '{n} levels': ('{n} 关', '{n} ステージ'),
    # ---- 日期 ----
    '{mon} {d} ({wd})': ('{m}月{d}日 {wd}', '{m}月{d}日（{wd}）'),
    '{mon} {y}': ('{y}年{m}月', '{y}年{m}月'),
    'Jan': ('1月', '1月'), 'Feb': ('2月', '2月'), 'Mar': ('3月', '3月'), 'Apr': ('4月', '4月'),
    'May': ('5月', '5月'), 'Jun': ('6月', '6月'), 'Jul': ('7月', '7月'), 'Aug': ('8月', '8月'),
    'Sep': ('9月', '9月'), 'Oct': ('10月', '10月'), 'Nov': ('11月', '11月'), 'Dec': ('12月', '12月'),
    'Mon': ('周一', '月'), 'Tue': ('周二', '火'), 'Wed': ('周三', '水'), 'Thu': ('周四', '木'),
    'Fri': ('周五', '金'), 'Sat': ('周六', '土'), 'Sun': ('周日', '日'),
    # ---- 难度 ----
    'Easy': ('简单', 'かんたん'),
    'Normal': ('普通', 'ふつう'),
    'Hard': ('困难', 'むずかしい'),
    'Slower, bigger clouds, less rain, more time each day': (
        '滑得慢、云朵大、雨少，每天时间更充裕', 'ゆっくり・雲が大きい・雨が少ない・一日の時間に余裕あり'),
    'Standard speed and rain': ('标准速度与雨量', '標準のスピードと雨の量'),
    'Faster, smaller clouds, more rain, less time each day': (
        '滑得快、云朵小、雨多，每天时间更紧', '速い・雲が小さい・雨が多い・一日の時間が短い'),
    # ---- 天气 ----
    'Sunny': ('晴天', '晴れ'),
    'Partly cloudy': ('多云', '晴れ時々くもり'),
    'Cloudy': ('阴天', 'くもり'),
    'Light rain': ('小雨', '小雨'),
    'Heavy rain': ('大雨', '大雨'),
    'Snow': ('雪天', '雪'),
    # ---- 游戏中 ----
    'Level {n} · {ym}': ('第 {n} 关 · {ym}', 'ステージ {n} · {ym}'),
    '{mode} · {done}/{total} days': ('{mode}模式 · 已定 {done}/{total} 天', '{mode}モード · {done}/{total} 日'),
    'Rain {a}/{b}': ('雨 {a}/{b}', '雨 {a}/{b}'),
    'That cloud already fell on Tokyo. Wait for the next one!': (
        '这朵云已经落到东京啦，等下一朵吧！', 'その雲はもう東京に降ったよ。次の雲を待とう！'),
    "Time's up! Today: {w}": ('时间到！今天是{w}', '時間切れ！今日は{w}'),
    '{w}… it rains in Tokyo': ('{w}……东京下雨了', '{w}…東京に雨が降った'),
    '{w}!': ('{w}！', '{w}！'),
    '{n} rainy days in total: you lost a star': ('累计下雨 {n} 天，失去 1 颗星', '雨が合計 {n} 日：星をひとつ失った'),
    'Welcome back!': ('欢迎回来！', 'おかえり！'),
    'Level {n} · continue from {date}': ('第 {n} 关 · 从 {date} 继续', 'ステージ {n} · {date} から再開'),
    '{ym} · {d} days': ('{ym} · 共 {d} 天', '{ym} · {d} 日間'),
    'Scroll speed': ('滚动速度', 'スクロール速度'),
    'Start Level {n}': ('开始第 {n} 关', 'ステージ {n} スタート'),
    'Click anywhere or press Space': ('点击任意处或按空格开始', 'どこかをクリック、またはスペースキー'),
    'Paused': ('暂停中', 'ポーズ中'),
    'Resume': ('继续游戏', 'ゲームに戻る'),
    'Save Progress': ('保存进度', 'セーブする'),
    'Saved!': ('已保存！', 'セーブしました！'),
    'Save & Back to Menu': ('保存并返回菜单', 'セーブしてメニューへ'),
    'All {n} levels cleared!': ('全部 {n} 关通关！', '全 {n} ステージクリア！'),
    'Level {n} cleared!': ('第 {n} 关通关！', 'ステージ {n} クリア！'),
    "Tokyo's weather in {ym}": ('{ym}的东京天气', '{ym}の東京の天気'),
    'This month: {s} sunny · {r} rainy': ('本月晴天 {s} 天 · 下雨 {r} 天', '今月：晴れ {s} 日・雨 {r} 日'),
    'Go to Level {n}': ('进入第 {n} 关', 'ステージ {n} へ'),
    'See the Ending': ('查看结局', 'エンディングを見る'),
    'Tokyo has had {n} rainy days…': ('东京已经累计下了 {n} 天雨……', '東京に雨が {n} 日も降ってしまった…'),
    # ---- 结束画面 ----
    "Tokyo's weather diary stopped at {ym}": ('东京的天气日记停在了{ym}', '東京の天気日記は{ym}で止まった'),
    'You decided a whole year of Tokyo weather': ('你决定了东京一整年的天气', '東京の一年分の天気を決めたよ'),
    'You made it through all': ('你走完了全部', '全部やりとげた'),
    'You reached': ('你坚持到了', '到達したのは'),
    'Rain you gave Tokyo': ('让东京下了', '東京に降らせた雨'),
    'Sunshine you won for Tokyo': ('为东京争取到', '東京に届けた晴れ'),
    'rainy days': ('天雨', '日'),
    'sunny days': ('天晴天', '日'),
    'Partly cloudy {a} · Cloudy {b} · Snow {c} · {d} days in all': (
        '多云 {a} 天 · 阴天 {b} 天 · 雪天 {c} 天 · 共 {d} 天',
        '晴れ時々くもり {a} 日・くもり {b} 日・雪 {c} 日・合計 {d} 日'),
    'New record! ({mode})': ('新纪录！（{mode}模式）', '新記録！（{mode}モード）'),
    '{mode} best: {best}': ('{mode}模式最佳纪录：{best}', '{mode}モードのベスト：{best}'),
    'Play Again': ('再来一次', 'もう一度'),
    'Back to Menu': ('返回菜单', 'メニューへ戻る'),
    # ---- 设置 ----
    'Difficulty': ('难度模式', '難易度'),
    'A game is in progress: difficulty applies from the next game': (
        '本局进行中：难度从下一局开始生效', 'プレイ中：難易度は次のゲームから反映されます'),
    'Speed has a ceiling: even level {n} stays readable and clickable': (
        '实际速度设有上限：到第 {n} 关也看得清、点得到', 'スピードには上限あり：ステージ {n} でも見やすく押しやすい'),
    'Daily time limit': ('每日限时', '一日の制限時間'),
    "When time runs out, the weather above Tokyo becomes today's": (
        '时间到了，东京正上方的天气会自动成为今天的天气', '時間切れになると、東京の真上の天気がその日の天気になります'),
    'ON': ('开', 'オン'),
    'OFF': ('关', 'オフ'),
    'Language': ('语言', '言語'),
    'Reset': ('恢复默认', 'リセット'),
    'Done': ('完成', '完了'),
    # ---- 玩法说明 ----
    'The weather strip at the top keeps sliding from left to right.': (
        '上方的天气条会从左往右一直滑过去。', '上の天気の帯は、左から右へずっと流れていきます。'),
    "Click anywhere (or press Space): the weather right above Tokyo Tower becomes today's weather.": (
        '点击屏幕任意处（或按空格），东京塔正上方那一格天气，就是今天的天气。',
        'どこかをクリック（またはスペースキー）すると、東京タワーの真上にある天気が今日の天気になります。'),
    'One level = one month. Decide every day of the month to clear it. {n} levels, January to December, '
    'each one faster.': (
        '一关 = 一个月：把这个月每一天的天气都定下来就过关。一共 {n} 关，从一月到十二月，越往后滑得越快。',
        '1ステージ＝1か月。その月の毎日の天気を決めればクリア。1月から12月まで全 {n} ステージ、先へ進むほど速くなります。'),
    'Light rain and heavy rain both count as rain. Every {n} rainy days in total (in a row or not) '
    'cost you a star.': (
        '小雨、大雨都算下雨。每累计 {n} 天雨（连续或不连续都算），失去 1 颗星。',
        '小雨も大雨も「雨」です。雨が合計 {n} 日になるたびに（連続でもそうでなくても）星をひとつ失います。'),
    'Lose all {s} stars ({d} rainy days) and the game is over. Stars carry over between levels and '
    'never come back.': (
        '{s} 颗星全部失去（累计 {d} 天雨）就游戏结束。星星会带到下一关，不会恢复。',
        '{s} つの星をすべて失う（雨が合計 {d} 日）とゲームオーバー。星は次のステージに引き継がれ、回復しません。'),
    'A picked cloud falls on Tokyo and cannot be picked again.': (
        '选过的云会落到东京，不能再选第二次。', '選んだ雲は東京に降るので、もう一度は選べません。'),
    'Each day has a time limit (can be turned off in Settings): when it runs out, the weather above '
    'Tokyo is picked for you.': (
        '每天有时间限制（可在设置里关掉）：时间到了，正上方的天气会自动成为今天的天气。',
        '一日ごとに制限時間があります（設定でオフにできます）。時間切れになると、真上の天気が自動で選ばれます。'),
    'Progress is saved automatically. Press Esc to pause.': (
        '进度会自动保存。按 Esc 暂停。', '進行状況は自動でセーブされます。Esc キーでポーズ。'),
    'Got it': ('知道了', 'わかった'),
    # ---- 保存失败 ----
    'Save failed': ('保存失败', 'セーブに失敗'),
    'Could not save progress': ('无法保存进度', '進行状況をセーブできませんでした'),
    # ---- 分数 / 分享 ----
    'Score': ('分数', 'スコア'),
    'Score {s}': ('分数 {s}', 'スコア {s}'),
    'Leaderboard: #{r} of {n} by score': ('排行榜：分数第 {r} 名（共 {n} 局）', 'ランキング：スコア {r} 位（全 {n} 回中）'),
    'Share Image': ('分享图片', 'シェア画像'),
    'Save Image…': ('保存图片…', '画像を保存…'),
    'Copy Image': ('复制图片', '画像をコピー'),
    'Close': ('关闭', '閉じる'),
    'Saved: {name}': ('已保存：{name}', '保存しました：{name}'),
    'Could not save the image': ('图片保存失败', '画像を保存できませんでした'),
    'Copied! Paste it anywhere to share': ('已复制！粘贴到任意地方即可分享', 'コピーしました！好きな場所に貼り付けてシェア'),
    '1200 × 630 PNG, ready to post': ('1200 × 630 PNG，可直接发到社交平台', '1200 × 630 PNG、そのまま投稿できます'),
    'Weather diary': ('天气日记', 'お天気日記'),
    'Played on {date}': ('游戏日期：{date}', 'プレイ日：{date}'),
    'Rain': ('下雨', '雨'),
    'days': ('天', '日'),
    # ---- 排行榜 ----
    'Leaderboard': ('排行榜', 'ランキング'),
    'Sort': ('排序', '並び順'),
    'Mode': ('难度', '難易度'),
    'All': ('全部', 'すべて'),
    'Level': ('关卡', 'ステージ'),
    'Sunny days': ('晴天数', '晴れの日数'),
    'Recent': ('最近', '新しい順'),
    'Date': ('日期', '日時'),
    'No games yet. Finish a game to get on the board!': (
        '还没有纪录。打完一局就会上榜！', 'まだ記録がありません。1回遊びきるとランキングに載ります！'),
    'Click a game to make a share image': ('点击任意一局可生成分享图', '記録をクリックするとシェア画像を作れます'),
    # ---- 音乐 ----
    'Background music': ('背景音乐', 'BGM'),
    'Music': ('音乐', '音楽'),
    # ---- 确认新游戏 ----
    'Start a new game?': ('开始新游戏？', '新しいゲームをはじめる？'),
    'Your saved progress will be replaced by the new game.': (
        '现在的存档会被新游戏覆盖。', '今のセーブデータは新しいゲームで上書きされます。'),
    'Cancel': ('取消', 'キャンセル'),
    'Start Over': ('重新开始', 'はじめから'),
}


def extract_source_strings() -> list:
    with open(SOURCE, encoding='utf-8') as handle:
        tree = ast.parse(handle.read())
    values = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in MARKERS
                and node.args and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            values.add(node.args[0].value)
    return sorted(values)


def emit_ts(path: str, language: str, index: int):
    strings = extract_source_strings()
    out = ['<?xml version="1.0" encoding="utf-8"?>', '<!DOCTYPE TS>',
           '<TS version="2.1" language="%s" sourcelanguage="en_US">' % language,
           '<context>', '    <name>%s</name>' % CONTEXT]
    missing = []
    for source in strings:
        pair = TRANSLATIONS.get(source)
        translation = pair[index] if pair else ''
        out.append('    <message>')
        out.append('        <source>%s</source>' % escape(source))
        if translation:
            out.append('        <translation>%s</translation>' % escape(translation))
        else:
            out.append('        <translation type="unfinished"></translation>')
            missing.append(source)
        out.append('    </message>')
    out.extend(['</context>', '</TS>', ''])
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write('\n'.join(out))
    return len(strings), missing


def find_lrelease():
    for candidate in (shutil.which('lrelease'), '/opt/homebrew/bin/lrelease', '/usr/local/bin/lrelease',
                      shutil.which('pyside6-lrelease')):
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def main() -> int:
    ts_paths = []
    missing_all = {}
    total = 0
    for language, index in LANGUAGES:
        ts_path = os.path.join(HERE, 'tokyoame_%s.ts' % language)
        total, missing = emit_ts(ts_path, language, index)
        ts_paths.append(ts_path)
        missing_all[language] = missing
    stale = sorted(set(TRANSLATIONS) - set(extract_source_strings()))
    print('source strings: %d' % total)
    for language, missing in missing_all.items():
        print('missing %s: %d' % (language, len(missing)))
        for item in missing[:30]:
            print('  MISSING:', repr(item))
    if stale:
        print('stale table entries (no longer in source): %d' % len(stale))
        for item in stale[:30]:
            print('  STALE:', repr(item))
    if '--no-qm' not in sys.argv:
        lrelease = find_lrelease()
        if lrelease is None:
            print('lrelease not found: install Qt tools (brew install qt) and run it on the .ts files')
            return 1
        for ts_path in ts_paths:
            qm_path = ts_path[:-3] + '.qm'
            subprocess.run([lrelease, ts_path, '-qm', qm_path], check=True)
    return 1 if any(missing_all.values()) else 0


if __name__ == '__main__':
    sys.exit(main())
